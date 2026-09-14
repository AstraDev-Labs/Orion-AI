"""Connections -- one place to link every account, key and service Orion can use.

The HUD's Connections screen is built entirely from ``CATALOG`` below, so a
contributor adding an integration adds one ``Connection`` entry (and, when the
service offers a cheap identity call, a verifier) and it appears in the UI with
a form, a status and a Verify button.

Where values live -- each integration keeps the storage its code already reads:

* ``credentials``  -> ``~/.orion/credentials.toml`` and ``os.environ`` (email,
  bot tokens, API keys). Loaded into the environment at ``orion serve`` start.
* ``connector``    -> ``~/.orion/connectors/<file>.json`` (data connectors).
* ``oauth``        -> client id/secret in the connector files, then a browser
  sign-in whose callback lands on a localhost port.
* ``whatsapp``     -> QR pairing handled by the channel bridge.

Secrets are write-only over the API: responses say whether a secret is set,
never what it is. The routes only answer loopback clients unless API-key auth
is enabled, because they read and write credentials.
"""

from __future__ import annotations

import json
import logging
import platform
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

_CONNECTORS_DIR = Path.home() / ".orion" / "connectors"
_VERIFY_TIMEOUT = 15.0


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    help: str = ""


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    category: str
    unlocks: str
    kind: str  # "credentials" | "connector" | "oauth" | "whatsapp"
    fields: Tuple[Field, ...] = ()
    setup_url: str = ""
    setup_steps: str = ""
    # credentials: section in credentials.toml; connector: json filename
    store: str = ""
    # oauth: connector id whose provider runs the sign-in
    oauth_connector: str = ""
    restart_required: bool = False
    cloud: bool = False
    platforms: Tuple[str, ...] = ()  # empty = every platform
    # Non-empty = shown but not usable yet; the text says why.
    coming_soon: str = ""
    verifier: Optional[Callable[[Dict[str, str]], Tuple[bool, str]]] = field(default=None, compare=False)


# ---------------------------------------------------------------------------
# Verifiers: one cheap, read-only identity call per service
# ---------------------------------------------------------------------------


def _service_reason(resp: httpx.Response) -> str:
    """The service's own explanation, e.g. OpenWeatherMap's "Invalid API key"."""
    try:
        data = resp.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    reason = data.get("message") or data.get("error_description") or data.get("error") or data.get("detail")
    if isinstance(reason, dict):
        reason = reason.get("message", "")
    return str(reason or "").strip()[:200]


def _http_check(
    method: str,
    url: str,
    ok_message: Callable[[dict], str],
    hints: Optional[Dict[int, str]] = None,
    **kwargs: Any,
) -> Tuple[bool, str]:
    try:
        resp = httpx.request(method, url, timeout=_VERIFY_TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        return False, f"Could not reach the service: {exc}"
    if resp.status_code >= 400:
        reason = _service_reason(resp)
        base = (
            "The service rejected these credentials"
            if resp.status_code in (401, 403)
            else f"The service returned HTTP {resp.status_code}"
        )
        message = f"{base}: {reason}" if reason else f"{base}."
        hint = (hints or {}).get(resp.status_code)
        return False, f"{message} {hint}" if hint else message
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return True, ok_message(data if isinstance(data, dict) else {})


def _verify_email(values: Dict[str, str]) -> Tuple[bool, str]:
    import smtplib

    from orion.tools.email_send import is_valid_address, smtp_server_for

    user = values.get("EMAIL_USERNAME", "").strip()
    password = values.get("EMAIL_PASSWORD", "").replace(" ", "")
    if not is_valid_address(user):
        return False, f"'{user}' is not a valid email address."
    host = values.get("EMAIL_SMTP_HOST", "").strip()
    port_s = values.get("EMAIL_SMTP_PORT", "").strip()
    if host:
        port = int(port_s) if port_s.isdigit() else 587
    else:
        host, port = smtp_server_for(user)
    try:
        if port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=_VERIFY_TIMEOUT)
        else:
            server = smtplib.SMTP(host, port, timeout=_VERIFY_TIMEOUT)
        with server:
            if port != 465:
                server.starttls()
            server.login(user, password)
    except smtplib.SMTPAuthenticationError:
        return False, (
            f"{host} rejected the login. For Gmail, use an app password with 2-Step "
            "Verification on -- not your normal password."
        )
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"Could not sign in to {host}: {exc}"
    return True, f"Signed in to {host} as {user}."


def _verify_telegram(values: Dict[str, str]) -> Tuple[bool, str]:
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    return _http_check(
        "GET",
        f"https://api.telegram.org/bot{token}/getMe",
        lambda d: f"Connected to bot @{(d.get('result') or {}).get('username', '?')}.",
    )


def _verify_discord(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "GET",
        "https://discord.com/api/v10/users/@me",
        lambda d: f"Connected to bot {d.get('username', '?')}.",
        headers={"Authorization": f"Bot {values.get('DISCORD_BOT_TOKEN', '')}"},
    )


def _verify_slack(values: Dict[str, str]) -> Tuple[bool, str]:
    ok, msg = _http_check(
        "POST",
        "https://slack.com/api/auth.test",
        lambda d: json.dumps(d),
        headers={"Authorization": f"Bearer {values.get('SLACK_BOT_TOKEN', '')}"},
    )
    if not ok:
        return ok, msg
    data = json.loads(msg)
    if not data.get("ok"):
        return False, f"Slack rejected the bot token ({data.get('error', 'unknown error')})."
    return True, f"Connected to Slack workspace {data.get('team', '?')}."


def _verify_tavily(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "POST",
        "https://api.tavily.com/search",
        lambda d: "Tavily accepted the key.",
        json={"api_key": values.get("TAVILY_API_KEY", ""), "query": "test", "max_results": 1},
    )


def _verify_openai(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "GET",
        "https://api.openai.com/v1/models",
        lambda d: "OpenAI accepted the key.",
        headers={"Authorization": f"Bearer {values.get('OPENAI_API_KEY', '')}"},
    )


def _verify_github(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "GET",
        "https://api.github.com/user",
        lambda d: f"Connected as GitHub user {d.get('login', '?')}.",
        headers={"Authorization": f"Bearer {values.get('token', '')}", "Accept": "application/vnd.github+json"},
    )


def _verify_notion(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "GET",
        "https://api.notion.com/v1/users/me",
        lambda d: f"Connected to Notion integration {d.get('name', '?')}.",
        headers={"Authorization": f"Bearer {values.get('token', '')}", "Notion-Version": "2022-06-28"},
    )


def _verify_weather(values: Dict[str, str]) -> Tuple[bool, str]:
    location = values.get("location", "") or "London"
    return _http_check(
        "GET",
        "https://api.openweathermap.org/data/2.5/weather",
        lambda d: f"OpenWeatherMap accepted the key -- found {d.get('name', location)}.",
        hints={
            401: (
                "A newly created OpenWeatherMap key takes up to 2 hours to activate, and only "
                "after you confirm your email. Try again later."
            ),
            404: "City not found. Use \"City,CountryCode\", for example Palayamkottai,IN.",
        },
        params={"q": location, "appid": values.get("api_key", "")},
    )


def _verify_oura(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "GET",
        "https://api.ouraring.com/v2/usercollection/personal_info",
        lambda d: "Oura accepted the token.",
        headers={"Authorization": f"Bearer {values.get('token', '')}"},
    )


def _verify_dropbox(values: Dict[str, str]) -> Tuple[bool, str]:
    return _http_check(
        "POST",
        "https://api.dropboxapi.com/2/users/get_current_account",
        lambda d: f"Connected to Dropbox as {(d.get('name') or {}).get('display_name', '?')}.",
        headers={"Authorization": f"Bearer {values.get('token', '')}"},
    )


def _verify_obsidian(values: Dict[str, str]) -> Tuple[bool, str]:
    path = Path(values.get("vault_path", "")).expanduser()
    if not path.is_dir():
        return False, f"'{path}' is not a folder on this computer."
    notes = sum(1 for _ in path.rglob("*.md"))
    if notes == 0:
        return False, f"No markdown notes found in '{path}'."
    return True, f"Found {notes} notes in the vault."


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

CATALOG: Tuple[Connection, ...] = (
    # -- Messaging & email -------------------------------------------------
    Connection(
        id="email",
        name="Email",
        category="Messaging & email",
        unlocks="Send emails you approve, and (for Gmail) read and search your inbox -- one login.",
        kind="credentials",
        store="email",
        fields=(
            Field("EMAIL_USERNAME", "Email address", placeholder="you@gmail.com"),
            Field(
                "EMAIL_PASSWORD",
                "App password",
                secret=True,
                placeholder="16-character app password",
                help="Not your normal password. Gmail: turn on 2-Step Verification, then create one.",
            ),
            Field("EMAIL_SMTP_HOST", "SMTP host", required=False, placeholder="auto (gmail, outlook, yahoo, icloud)"),
            Field("EMAIL_SMTP_PORT", "SMTP port", required=False, placeholder="587"),
        ),
        setup_url="https://myaccount.google.com/apppasswords",
        setup_steps="Google Account → Security → 2-Step Verification → App passwords → create one named Orion.",
        verifier=_verify_email,
    ),
    Connection(
        id="whatsapp",
        name="WhatsApp",
        category="Messaging & email",
        unlocks="Message contacts and auto-reply while you're away.",
        kind="whatsapp",
    ),
    Connection(
        id="telegram",
        name="Telegram",
        category="Messaging & email",
        unlocks="Chat with Orion and get notifications through your own Telegram bot.",
        kind="credentials",
        store="telegram",
        fields=(
            Field("TELEGRAM_BOT_TOKEN", "Bot token", secret=True, placeholder="123456:ABC-DEF..."),
            Field(
                "TELEGRAM_NOTIFY_CHAT_ID",
                "Your chat ID",
                required=False,
                placeholder="e.g. 123456789",
                help="Where notifications go. Message @userinfobot to find yours.",
            ),
        ),
        setup_url="https://t.me/BotFather",
        setup_steps="Open @BotFather in Telegram, send /newbot, and copy the token it gives you.",
        restart_required=True,
        verifier=_verify_telegram,
    ),
    Connection(
        id="discord",
        name="Discord",
        category="Messaging & email",
        unlocks="Chat with Orion through your own Discord bot.",
        kind="credentials",
        store="discord",
        fields=(
            Field("DISCORD_BOT_TOKEN", "Bot token", secret=True),
            Field("DISCORD_OWNER_USER_ID", "Your user ID", required=False, help="Only you can command the bot."),
        ),
        setup_url="https://discord.com/developers/applications",
        setup_steps="New Application → Bot → Reset Token, and enable the Message Content intent.",
        restart_required=True,
        verifier=_verify_discord,
    ),
    Connection(
        id="slack",
        name="Slack",
        category="Messaging & email",
        unlocks="Chat with Orion in your Slack workspace.",
        kind="credentials",
        store="slack",
        fields=(
            Field("SLACK_BOT_TOKEN", "Bot token", secret=True, placeholder="xoxb-..."),
            Field("SLACK_APP_TOKEN", "App-level token", secret=True, placeholder="xapp-...", help="Needed for Socket Mode."),
        ),
        setup_url="https://api.slack.com/apps",
        setup_steps="Create an app, enable Socket Mode, add bot scopes, install it, and copy both tokens.",
        restart_required=True,
        verifier=_verify_slack,
    ),
    # -- Knowledge & search --------------------------------------------------
    Connection(
        id="web_search",
        name="Web search (Tavily)",
        category="Knowledge & search",
        unlocks="Better live web results. Without a key Orion falls back to DuckDuckGo.",
        kind="credentials",
        store="web_search",
        fields=(Field("TAVILY_API_KEY", "API key", secret=True, placeholder="tvly-..."),),
        setup_url="https://app.tavily.com",
        setup_steps="Sign up and copy your API key (the free tier includes monthly searches).",
        restart_required=True,
        cloud=True,
        verifier=_verify_tavily,
    ),
    Connection(
        id="obsidian",
        name="Obsidian vault",
        category="Knowledge & search",
        unlocks="Search and write notes in your vault.",
        kind="connector",
        store="obsidian.json",
        fields=(Field("vault_path", "Vault folder", placeholder=r"C:\Users\you\Documents\MyVault"),),
        setup_steps="Paste the full path of the folder that contains your .obsidian directory.",
        verifier=_verify_obsidian,
    ),
    Connection(
        id="notion",
        name="Notion",
        category="Knowledge & search",
        unlocks="Search your Notion pages.",
        kind="connector",
        store="notion.json",
        fields=(Field("token", "Integration secret", secret=True, placeholder="ntn_..."),),
        setup_url="https://www.notion.so/my-integrations",
        setup_steps="Create an internal integration, copy its secret, then share pages with it.",
        verifier=_verify_notion,
    ),
    Connection(
        id="github",
        name="GitHub",
        category="Knowledge & search",
        unlocks="Read your GitHub notifications.",
        kind="connector",
        store="github.json",
        fields=(Field("token", "Personal access token", secret=True, placeholder="github_pat_..."),),
        setup_url="https://github.com/settings/tokens?type=beta",
        setup_steps="Create a fine-grained token with read access to notifications.",
        verifier=_verify_github,
    ),
    Connection(
        id="weather",
        name="Weather",
        category="Knowledge & search",
        unlocks="Current weather and forecasts for your city.",
        kind="connector",
        store="weather.json",
        fields=(
            Field("api_key", "OpenWeatherMap API key", secret=True),
            Field(
                "location",
                "City",
                placeholder="Chennai,IN",
                help="City and 2-letter country code, e.g. Palayamkottai,IN. State names are only used for US cities.",
            ),
        ),
        setup_url="https://home.openweathermap.org/api_keys",
        setup_steps="Sign up, confirm your email, then copy the default key. New keys can take up to 2 hours to start working.",
        verifier=_verify_weather,
    ),
    Connection(
        id="dropbox",
        name="Dropbox",
        category="Knowledge & search",
        unlocks="Search files in your Dropbox.",
        kind="connector",
        store="dropbox.json",
        fields=(Field("token", "Access token", secret=True),),
        setup_url="https://www.dropbox.com/developers/apps",
        setup_steps="Create an app, then generate an access token on its settings page.",
        verifier=_verify_dropbox,
    ),
    Connection(
        id="oura",
        name="Oura",
        category="Knowledge & search",
        unlocks="Sleep and readiness data from your Oura ring.",
        kind="connector",
        store="oura.json",
        fields=(Field("token", "Personal access token", secret=True),),
        setup_url="https://cloud.ouraring.com/personal-access-tokens",
        verifier=_verify_oura,
    ),
    # -- Accounts (browser sign-in) ----------------------------------------------
    Connection(
        id="google",
        name="Google account",
        category="Accounts",
        unlocks=(
            "Calendar, contacts and tasks with one Google sign-in (Drive too with your own "
            "OAuth client). Not needed for email -- that uses the Email connection above."
        ),
        coming_soon=(
            "Work in progress: Google requires Orion's own website (homepage and privacy "
            "policy) before it approves sign-in for everyone. Email already works through "
            "the Email connection above."
        ),
        kind="oauth",
        oauth_connector="gcalendar",
        fields=(
            Field("client_id", "OAuth client ID", placeholder="....apps.googleusercontent.com"),
            Field("client_secret", "OAuth client secret", secret=True),
        ),
        setup_url="https://console.cloud.google.com/apis/credentials",
        setup_steps=(
            "Own OAuth client: create a project, enable the Calendar/Drive/People/Tasks APIs, "
            "then Create credentials → OAuth client ID → Desktop app. Paste the ID and secret, "
            "then Sign in."
        ),
    ),
    Connection(
        id="spotify",
        name="Spotify",
        category="Accounts",
        unlocks="Your recently played music.",
        kind="oauth",
        oauth_connector="spotify",
        fields=(
            Field("client_id", "Client ID"),
            Field("client_secret", "Client secret", secret=True),
        ),
        setup_url="https://developer.spotify.com/dashboard",
        setup_steps="Create an app with redirect URI http://127.0.0.1:8888/callback, then paste its ID and secret.",
    ),
    Connection(
        id="strava",
        name="Strava",
        category="Accounts",
        unlocks="Your workouts and activities.",
        kind="oauth",
        oauth_connector="strava",
        fields=(
            Field("client_id", "Client ID"),
            Field("client_secret", "Client secret", secret=True),
        ),
        setup_url="https://www.strava.com/settings/api",
        setup_steps="Create an API application with callback domain localhost, then paste its ID and secret.",
    ),
    # -- Optional cloud AI ---------------------------------------------------------
    Connection(
        id="openai",
        name="OpenAI (optional)",
        category="Optional cloud AI",
        unlocks="Image generation. Requests using it leave this computer.",
        kind="credentials",
        store="image_generate",
        fields=(Field("OPENAI_API_KEY", "API key", secret=True, placeholder="sk-..."),),
        setup_url="https://platform.openai.com/api-keys",
        restart_required=True,
        cloud=True,
        verifier=_verify_openai,
    ),
)

_BY_ID: Dict[str, Connection] = {c.id: c for c in CATALOG}


def get_connection(connection_id: str) -> Connection:
    conn = _BY_ID.get(connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Unknown connection '{connection_id}'")
    return conn


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _connector_file(conn: Connection) -> Path:
    return _CONNECTORS_DIR / conn.store


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _oauth_provider(conn: Connection):
    from orion.connectors.oauth import get_provider_for_connector

    return get_provider_for_connector(conn.oauth_connector)


def stored_values(conn: Connection) -> Dict[str, str]:
    """Current values for every field (secrets included -- server side only)."""
    if conn.kind == "credentials":
        from orion.core.credentials import get_tool_credential

        return {f.key: get_tool_credential(conn.store, f.key) or "" for f in conn.fields}
    if conn.kind == "connector":
        data = _read_json(_connector_file(conn))
        return {f.key: str(data.get(f.key, "") or "") for f in conn.fields}
    if conn.kind == "oauth":
        from orion.connectors.oauth import get_client_credentials

        provider = _oauth_provider(conn)
        creds = get_client_credentials(provider) if provider else None
        client_id, client_secret = creds if creds else ("", "")
        return {"client_id": client_id, "client_secret": client_secret}
    return {}


def save_values(conn: Connection, values: Dict[str, str]) -> None:
    """Persist submitted fields. Blank secrets keep the stored value."""
    allowed = {f.key: f for f in conn.fields}
    unknown = set(values) - set(allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown fields: {', '.join(sorted(unknown))}")
    cleaned = {k: str(v).strip() for k, v in values.items() if str(v).strip()}
    if conn.kind == "credentials":
        from orion.core.credentials import save_credential

        for key, value in cleaned.items():
            save_credential(conn.store, key, value)
    elif conn.kind == "connector":
        path = _connector_file(conn)
        data = _read_json(path)
        data.update(cleaned)
        if conn.id == "obsidian" and "vault_path" in cleaned:
            data["path"] = cleaned["vault_path"]  # older readers use "path"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    elif conn.kind == "oauth":
        from orion.connectors.oauth import save_client_credentials

        current = stored_values(conn)
        client_id = cleaned.get("client_id") or current["client_id"]
        client_secret = cleaned.get("client_secret") or current["client_secret"]
        provider = _oauth_provider(conn)
        if provider and client_id and client_secret:
            save_client_credentials(provider, client_id, client_secret)
    else:
        raise HTTPException(status_code=400, detail=f"{conn.name} is not configured with fields")


def clear_values(conn: Connection) -> None:
    if conn.kind == "credentials":
        from orion.core.credentials import delete_credentials

        delete_credentials(conn.store, [f.key for f in conn.fields])
    elif conn.kind == "connector":
        path = _connector_file(conn)
        if path.exists():
            path.unlink()
    elif conn.kind == "oauth":
        provider = _oauth_provider(conn)
        for filename in provider.credential_files if provider else ():
            path = _CONNECTORS_DIR / filename
            if path.exists():
                path.unlink()


def _whatsapp_live_status() -> str:
    """Status of the running WhatsApp bridge ("connected", "connecting", ...)."""
    try:
        from orion.channels.live import get_live_channel

        channel = get_live_channel("whatsapp")
        if channel is None:
            return "not_configured"
        inner = getattr(channel, "_channels", {}).get("whatsapp_baileys", channel)
        return str(inner.status().value)
    except Exception:
        return "unknown"


def _oauth_connected(conn: Connection) -> bool:
    from orion.core.registry import ConnectorRegistry

    provider = _oauth_provider(conn)
    for cid in provider.connector_ids if provider else ():
        try:
            import orion.connectors  # noqa: F401  (registers connectors)

            if ConnectorRegistry.contains(cid) and ConnectorRegistry.get(cid)().is_connected():
                return True
        except Exception:
            continue
    return False


# OAuth sign-ins run in a thread (they wait for the browser callback).
_OAUTH_STATE: Dict[str, Dict[str, str]] = {}
_OAUTH_LOCK = threading.Lock()


def _run_oauth(conn: Connection) -> None:
    from orion.connectors.oauth import run_connector_oauth

    try:
        run_connector_oauth(conn.oauth_connector)
        state = {"state": "done", "message": f"Signed in to {conn.name}."}
    except Exception as exc:  # the flow reports every failure mode as an exception
        state = {"state": "error", "message": f"Sign-in failed: {exc}"}
    with _OAUTH_LOCK:
        _OAUTH_STATE[conn.id] = state


def describe(conn: Connection) -> Dict[str, Any]:
    """Public view: field metadata plus which values are set -- never secret values."""
    values = stored_values(conn)
    fields = []
    for f in conn.fields:
        value = values.get(f.key, "")
        fields.append(
            {
                "key": f.key,
                "label": f.label,
                "secret": f.secret,
                "required": f.required,
                "placeholder": f.placeholder,
                "help": f.help,
                "set": bool(value),
                "value": "" if f.secret else value,
            }
        )
    configured = all(values.get(f.key) for f in conn.fields if f.required) if conn.fields else False
    status = "connected" if configured else "not_connected"
    extra: Dict[str, Any] = {}
    if conn.kind == "whatsapp":
        # No saved fields to judge by: WhatsApp is connected exactly when the
        # live bridge says so. Using the field check made this card read
        # "Not connected" right above the pairing panel saying "Connected".
        status = "connected" if _whatsapp_live_status() == "connected" else "not_connected"
    if conn.kind == "oauth":
        from orion.connectors.oauth import shipped_client

        provider = _oauth_provider(conn)
        one_click = bool(provider and shipped_client(provider)[0])
        can_sign_in = configured or one_click
        status = "connected" if _oauth_connected(conn) else ("ready" if can_sign_in else "not_connected")
        extra["one_click"] = one_click
        # Your own client is optional when Orion ships one.
        if one_click:
            for f in fields:
                f["required"] = False
        with _OAUTH_LOCK:
            extra["oauth"] = _OAUTH_STATE.get(conn.id)
    if conn.coming_soon:
        status = "coming_soon"
    return {
        "id": conn.id,
        "coming_soon": conn.coming_soon,
        "name": conn.name,
        "category": conn.category,
        "unlocks": conn.unlocks,
        "kind": conn.kind,
        "fields": fields,
        "status": status,
        "setup_url": conn.setup_url,
        "setup_steps": conn.setup_steps,
        "restart_required": conn.restart_required,
        "cloud": conn.cloud,
        "can_verify": conn.verifier is not None,
        **extra,
    }


def available(conn: Connection) -> bool:
    return not conn.platforms or platform.system().lower() in conn.platforms


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/connections", tags=["connections"])

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_local(request: Request) -> None:
    """Credentials are only readable/writable from this machine.

    With API-key auth enabled the auth middleware already gates every request,
    so a remote client holding the key is allowed too.
    """
    if getattr(request.app.state, "api_key", ""):
        return
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK:
        raise HTTPException(status_code=403, detail="Connections can only be managed from this computer.")


@router.get("")
async def list_connections(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    _require_local(request)
    from starlette.concurrency import run_in_threadpool

    items = await run_in_threadpool(lambda: [describe(c) for c in CATALOG if available(c)])
    return {"connections": items}


@router.put("/{connection_id}")
async def update_connection(connection_id: str, request: Request) -> Dict[str, Any]:
    """Save fields, then verify them when the service supports it."""
    _require_local(request)
    conn = get_connection(connection_id)
    body = await request.json()
    values = body.get("values", {}) if isinstance(body, dict) else {}
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="'values' must be an object")

    from starlette.concurrency import run_in_threadpool

    # Verify the merged result before keeping it, so a typo never replaces a
    # working secret: blank secret fields fall back to what is stored.
    merged = {**stored_values(conn), **{k: str(v).strip() for k, v in values.items() if str(v).strip()}}
    missing = [f.label for f in conn.fields if f.required and not merged.get(f.key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {', '.join(missing)}")

    verified: Optional[Tuple[bool, str]] = None
    if conn.verifier is not None and body.get("verify", True):
        verified = await run_in_threadpool(conn.verifier, merged)
        if not verified[0]:
            return {"saved": False, "ok": False, "message": verified[1], "connection": describe(conn)}

    await run_in_threadpool(save_values, conn, values)
    message = verified[1] if verified else "Saved."
    if conn.restart_required:
        message += " Restart Orion to start using it."
    return {"saved": True, "ok": True, "message": message, "connection": describe(conn)}


@router.post("/{connection_id}/verify")
async def verify_connection(connection_id: str, request: Request) -> Dict[str, Any]:
    _require_local(request)
    conn = get_connection(connection_id)
    if conn.verifier is None:
        return {"ok": describe(conn)["status"] == "connected", "message": "This connection has no online check."}
    from starlette.concurrency import run_in_threadpool

    ok, message = await run_in_threadpool(conn.verifier, stored_values(conn))
    return {"ok": ok, "message": message}


@router.post("/{connection_id}/authorize")
async def authorize_connection(connection_id: str, request: Request) -> Dict[str, Any]:
    """Start a browser sign-in for an OAuth account; poll the list for the result."""
    _require_local(request)
    conn = get_connection(connection_id)
    if conn.coming_soon:
        raise HTTPException(status_code=400, detail=conn.coming_soon)
    if conn.kind != "oauth":
        raise HTTPException(status_code=400, detail=f"{conn.name} does not use browser sign-in")
    values = stored_values(conn)
    from orion.connectors.oauth import shipped_client

    provider = _oauth_provider(conn)
    has_shipped = bool(provider and shipped_client(provider)[0])
    if not (values["client_id"] and values["client_secret"]) and not has_shipped:
        raise HTTPException(
            status_code=400,
            detail="This build has no built-in Google sign-in yet. Add your own OAuth client ID and secret first.",
        )
    with _OAUTH_LOCK:
        if (_OAUTH_STATE.get(conn.id) or {}).get("state") == "waiting":
            return {"state": "waiting", "message": "Already waiting for the browser sign-in."}
        _OAUTH_STATE[conn.id] = {"state": "waiting", "message": "Finish signing in in the browser window that opened."}
    threading.Thread(target=_run_oauth, args=(conn,), name=f"oauth-{conn.id}", daemon=True).start()
    return _OAUTH_STATE[conn.id]


@router.delete("/{connection_id}")
async def disconnect_connection(connection_id: str, request: Request) -> Dict[str, Any]:
    _require_local(request)
    conn = get_connection(connection_id)
    if conn.kind == "whatsapp":
        raise HTTPException(status_code=400, detail="Unlink WhatsApp from your phone: Linked Devices → Log out.")
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(clear_values, conn)
    with _OAUTH_LOCK:
        _OAUTH_STATE.pop(conn.id, None)
    return {"ok": True, "message": f"Disconnected {conn.name}.", "connection": describe(conn)}


@router.post("/restart")
async def restart_backend(request: Request) -> Dict[str, str]:
    """Restart so channels and tools pick up newly saved keys."""
    _require_local(request)
    from orion.system.self_restart import schedule_self_restart

    schedule_self_restart()
    return {"restart": "scheduled"}


__all__ = ["CATALOG", "Connection", "Field", "describe", "router"]
