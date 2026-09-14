"""Send email over SMTP with an app password (Gmail by default).

Runs only as the executor of an approved ``email_send`` action -- see
``ExecutePendingActionsTool`` in proactive_tools.py. Nothing here can send
without a human's "yes".

Credentials live in ~/.orion/credentials.toml under ``[email]``
(``EMAIL_USERNAME`` / ``EMAIL_PASSWORD``) and are written by
``orion email setup``, which reads the app password from the terminal so it
never passes through a chat transcript or a model prompt.
"""

from __future__ import annotations

import re
import smtplib
import socket
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Dict, Tuple

_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$")

# Providers whose SMTP host follows from the address. Anything else needs
# EMAIL_SMTP_HOST set explicitly.
_KNOWN_SMTP = {
    "gmail.com": ("smtp.gmail.com", 587),
    "googlemail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587),
    "live.com": ("smtp-mail.outlook.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587),
}

SETUP_HINT = "Run `orion email setup` in a terminal to connect your Gmail with an app password."

_TIMEOUT_S = 20


def is_valid_address(address: str) -> bool:
    return bool(_ADDRESS.match((address or "").strip()))


def _credential(key: str) -> str:
    from orion.core.credentials import get_tool_credential

    return (get_tool_credential("email", key) or "").strip()


def smtp_server_for(username: str) -> Tuple[str, int]:
    """SMTP host and port: explicit settings first, then the address's provider."""
    host = _credential("EMAIL_SMTP_HOST")
    port = _credential("EMAIL_SMTP_PORT")
    if host:
        return host, int(port) if port.isdigit() else 587
    domain = username.rsplit("@", 1)[-1].lower() if "@" in username else ""
    return _KNOWN_SMTP.get(domain, ("smtp.gmail.com", 587))


def _default_subject(body: str) -> str:
    words = body.split()
    subject = " ".join(words[:8])
    return (subject + "...") if len(words) > 8 else (subject or "Message")


def send_email(
    to: str,
    body: str,
    subject: str = "",
    *,
    username: str | None = None,
    password: str | None = None,
    sender_name: str = "",
) -> Tuple[bool, str]:
    """Send one plain-text email. Returns ``(success, message)``; never raises."""
    to = (to or "").strip()
    body = (body or "").strip()
    if not is_valid_address(to):
        return False, f"'{to}' is not a valid email address, so nothing was sent."
    if not body:
        return False, "The email has no message text, so nothing was sent."

    username = (username if username is not None else _credential("EMAIL_USERNAME")).strip()
    # Gmail shows app passwords in groups of four ("abcd efgh ijkl mnop").
    password = (password if password is not None else _credential("EMAIL_PASSWORD")).replace(" ", "")
    if not username or not password:
        return False, f"Email isn't set up yet, so nothing was sent. {SETUP_HINT}"

    host, port = smtp_server_for(username)
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, username)) if sender_name else username
    msg["To"] = to
    msg["Subject"] = (subject or "").strip() or _default_subject(body)
    msg["Message-ID"] = make_msgid(domain=username.rsplit("@", 1)[-1])
    msg.set_content(body)

    try:
        if port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_S)
        else:
            server = smtplib.SMTP(host, port, timeout=_TIMEOUT_S)
        with server:
            if port != 465:
                server.starttls()
            server.login(username, password)
            refused = server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return False, (
            f"{host} rejected the login for {username}, so nothing was sent. Gmail needs an "
            "app password (not your normal password) with 2-Step Verification on. "
            + SETUP_HINT
        )
    except smtplib.SMTPRecipientsRefused:
        return False, f"The mail server refused the recipient {to}, so nothing was sent."
    except (socket.timeout, TimeoutError):
        return False, f"Timed out reaching {host}; check the internet connection. Nothing was sent."
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"Sending failed ({type(exc).__name__}: {exc}). Nothing was sent."

    if refused:
        return False, f"The mail server refused {', '.join(refused)}."
    return True, f"Email sent to {to} from {username} (subject: {msg['Subject']})."


def exec_email_send(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Executor for an approved ``email_send`` action.

    Models name the fields inconsistently (a real queue held both ``body`` and
    ``content``), so the common spellings are all accepted.
    """
    to = payload.get("recipient") or payload.get("to") or payload.get("email") or ""
    body = payload.get("body") or payload.get("content") or payload.get("message") or ""
    subject = payload.get("subject") or ""
    if isinstance(to, list):
        to = to[0] if to else ""
    sender_name = ""
    try:
        from orion.server.live_context import user_name

        sender_name = user_name()
    except Exception:
        pass
    return send_email(str(to), str(body), str(subject), sender_name=sender_name)


__all__ = ["exec_email_send", "is_valid_address", "send_email", "smtp_server_for", "SETUP_HINT"]
