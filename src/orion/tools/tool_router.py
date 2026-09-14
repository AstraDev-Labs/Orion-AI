"""Query-aware tool subsetting.

A small local model given 44 tool schemas plus a long system prompt does
not reliably pick the right one -- it will confidently call something
adjacent instead. Measured on qwen3.5:2b: asked to use `calculator`, it
reached for desktop typing. The same model given only the calculator
schema calls it perfectly. Capacity, not capability.

So rank tools by relevance to the current query and hand the model a
short list instead of the whole catalogue. Deliberately lexical, not a
second model call: routing must not add a round trip to every turn.

`propose_new_tool` is treated specially -- it is appended only when
nothing else scores well, which is exactly the condition it exists for
(no existing tool covers the request). Including it unconditionally makes
it an attractor for small models, which is the failure this module was
written to fix.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Iterable, List, Optional, Sequence

if TYPE_CHECKING:
    from orion.tools._stubs import BaseTool

logger = logging.getLogger(__name__)

FORGE_TOOL = "propose_new_tool"

# Below this, nothing in the catalogue is a good match for the query.
_WEAK_MATCH = 1.5

# A tool whose name or alias the query uses. Anything below this only shares a
# single word with its description ("in", "screen") and is almost never the
# tool wanted.
_STRONG_MATCH = 2.0

# Fewest tools offered, so a vaguely worded request still has a working set.
_MIN_TOOLS = 3

# Words too common to carry signal about which tool is wanted.
_STOPWORDS = frozenset(
    """a an the and or but if then than that this these those of for to from in on at by with
    without into onto is are was were be been being do does did doing done have has had having
    can could should would will shall may might must i you he she it we they me my your our
    please use using used get got make made want need help me about as it's its what which who
    whom when where why how all any both each few more most other some such no nor not only own
    same so too very just now also here there tool tool's tools""".split()
)

# Generally-useful tools that win ties when the query gives little signal,
# so a low-signal query still gets a sane working set rather than an
# arbitrary alphabetical slice.
_CORE_PRIORITY = {
    "think": 9,
    "web_search": 8,
    "calculator": 7,
    "memory_retrieve": 6,
    "memory_search": 6,
    "file_read": 5,
    "system_info": 5,
    "obsidian_search_notes": 4,
    "code_interpreter": 4,
    "http_request": 3,
}

# Domain keywords a tool's own description does not contain.
#
# Some of Orion's routing knowledge lives in the system prompt rather than
# in tool descriptions -- e.g. "to message someone, call queue_action with
# action_type='channel_send'". Pure lexical matching cannot see that, and
# without these aliases a "send a WhatsApp message" query drops
# queue_action entirely, making the task impossible rather than merely
# harder. Each entry encodes that missing link.
_ALIASES: dict[str, tuple[str, ...]] = {
    "queue_action": (
        "send", "message", "msg", "text", "whatsapp", "telegram", "discord",
        "slack", "email", "mail", "sms", "reply", "draft", "notify", "tell",
    ),
    # Chat messages specifically (not email, which is queue_action's).
    "channel_send": ("message", "msg", "text", "whatsapp", "telegram", "discord", "slack", "tell", "ping"),
    "execute_pending_actions": ("approve", "approved", "confirm", "yes", "send", "proceed"),
    "get_pending_actions": ("pending", "queued", "waiting", "approval", "drafts"),
    "web_search": (
        "news", "latest", "current", "today", "recent", "search", "google",
        "weather", "price", "stock", "score", "who", "when", "happened",
    ),
    "system_info": (
        "time", "date", "day", "battery", "cpu", "memory", "disk", "uptime",
        "network", "wifi", "online", "clipboard", "clock",
    ),
    "system_control": (
        "volume", "mute", "unmute", "louder", "quieter", "brightness", "brighter",
        "dimmer", "lock", "sleep", "wifi", "bluetooth",
    ),
    "play_music": ("play", "song", "music", "track", "album", "artist", "spotify"),
    "play_video": ("play", "video", "youtube", "watch", "movie", "episode"),
    "open_app": ("open", "launch", "start", "app", "application", "browser", "chrome"),
    # Deliberately does NOT claim "install"/"download": those belong to
    # install_app, and taking them made install_game outrank it for "install
    # vlc". The router scores keywords, not meaning -- it cannot tell that
    # Elden Ring is a game and VLC is not -- so each tool owns only the words
    # that are unambiguously its own.
    # Not "play" either: that is play_music's and play_video's, and with it
    # "play shape of you" put the game installer on the menu.
    "install_game": (
        "game", "games", "gaming", "steam", "epic", "ubisoft", "uplay",
        "origin", "library", "launcher", "playable",
    ),
    "calculator": (
        "calculate", "calc", "math", "percent", "sum", "multiply", "divide",
        "plus", "minus", "times", "sqrt", "average",
    ),
    "memory_search": ("told", "said", "mentioned", "remember", "recall", "forgot", "earlier"),
    "memory_retrieve": ("told", "said", "mentioned", "remember", "recall", "forgot", "earlier"),
    "install_app": (
        "install", "installing", "download", "setup", "get", "add", "app",
        "application", "program", "software", "package", "winget", "msi",
    ),
    "vision_capture": ("see", "look", "screen", "screenshot", "camera", "webcam"),
    "reminder": ("remind", "reminder", "alarm", "schedule", "later"),
    "away_mode": ("away", "back", "stepping", "out", "afk", "return"),
    "obsidian_write_note": ("note", "notes", "vault", "save", "jot", "write"),
    "obsidian_search_notes": ("note", "notes", "vault", "recall", "find", "remember"),
    "code_interpreter": ("python", "code", "script", "run", "execute", "compute"),
    "shell_exec": ("shell", "command", "terminal", "bash", "powershell"),
    "web_fetch": ("fetch", "url", "page", "website", "link"),
    "http_request": ("api", "endpoint", "request", "http", "url", "post", "get"),
}


_WORD_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> List[str]:
    # Single letters carry nothing: the "s" of "what's" matched "user's" in
    # tool descriptions.
    return [w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 1 and w not in _STOPWORDS]


def _name_variants(name: str) -> set[str]:
    """A tool's name plus its underscore-separated parts."""
    parts = {name.lower()}
    parts.update(p for p in name.lower().split("_") if p and p not in _STOPWORDS)
    return parts


def score_tool(tool: "BaseTool", query_tokens: Sequence[str]) -> float:
    """Relevance of one tool to a tokenized query.

    Name matches dominate: a user naming a tool ("use the calculator
    tool") should pin it to the top regardless of description wording.
    """
    if not query_tokens:
        return 0.0
    try:
        spec = tool.spec
    except Exception:  # a tool whose spec raises should not break routing
        return 0.0

    qset = set(query_tokens)
    score = 0.0

    variants = _name_variants(spec.name)
    if spec.name.lower() in qset:
        score += 10.0  # explicit, unambiguous mention of the tool itself
    score += 3.0 * len(qset & variants)

    desc_tokens = set(_tokenize(spec.description)[:120])
    score += 1.0 * len(qset & desc_tokens)

    # Domain keywords the description itself never mentions. Weighted
    # between a name hit and a description hit: strong enough to surface a
    # workflow-critical tool, not so strong it outranks an explicit
    # mention of a different tool by name.
    alias_hits = qset & set(_ALIASES.get(spec.name, ()))
    score += 2.0 * len(alias_hits)

    if spec.category and spec.category.lower() in qset:
        score += 1.0
    return score


def select_tools(
    tools: Sequence["BaseTool"],
    query: str,
    *,
    max_tools: int = 12,
    always_include: Optional[Iterable[str]] = None,
) -> List["BaseTool"]:
    """Return the most relevant `max_tools` for `query`.

    max_tools <= 0 disables routing and returns everything, so the whole
    feature can be switched off in config without code changes.
    """
    tools = list(tools)
    if max_tools <= 0 or len(tools) <= max_tools:
        return tools

    forced = {n for n in (always_include or ()) if n}
    query_tokens = _tokenize(query)

    scored = []
    for t in tools:
        try:
            name = t.spec.name
        except Exception:
            continue
        scored.append((score_tool(t, query_tokens), _CORE_PRIORITY.get(name, 0), name, t))

    # forced tools first, then by score, then core priority, then name for
    # a stable, reproducible ordering
    scored.sort(key=lambda r: (r[2] in forced, r[0], r[1], r[2]), reverse=True)

    best_score = max((r[0] for r in scored if r[2] != FORGE_TOOL), default=0.0)
    include_forge = best_score < _WEAK_MATCH

    # Resolve the forge tool up front. Looking for it inside the selection
    # loop below fails: that loop stops at max_tools, and propose_new_tool
    # scores near zero on an unmatched query, so the loop exits long before
    # reaching it and the fallback silently never fires.
    forge_tool = next((t for _s, _p, n, t in scored if n == FORGE_TOOL), None)

    # Offer only tools the query actually points at. Padding the menu to
    # max_tools with one-word description matches sent ~2,500 tokens of
    # schemas per request (open_app, install_app, install_game... for "what's
    # the weather") -- on a 4B model partly on CPU, about 4 s before the first
    # word, and more choices for a small model to confuse.
    candidates = [r for r in scored if r[2] != FORGE_TOOL]
    selected: List["BaseTool"] = []
    chosen: set[str] = set()
    for score, _prio, name, tool in candidates:
        if len(selected) >= max_tools:
            break
        if name in forced or score >= _STRONG_MATCH:
            selected.append(tool)
            chosen.add(name)

    # Too few for a vague request: top up with the generally useful core
    # tools first, then the best of the weak matches.
    floor = min(_MIN_TOOLS, max_tools)
    if len(selected) < floor:
        fill = sorted(
            (r for r in candidates if r[2] not in chosen and (r[0] > 0 or r[1] > 0)),
            key=lambda r: (r[1] > 0, r[0], r[1], r[2]),
            reverse=True,
        )
        for _score, _prio, name, tool in fill:
            if len(selected) >= floor:
                break
            selected.append(tool)
            chosen.add(name)

    # Nothing matched well -> the request may need a capability that does
    # not exist yet, which is precisely when tool creation is worth
    # offering. Swap it in for the weakest pick rather than growing the list.
    if include_forge and forge_tool is not None and FORGE_TOOL not in forced:
        if len(selected) >= max_tools and selected:
            selected.pop()
        selected.append(forge_tool)

    logger.debug(
        "Tool routing: %d/%d selected (best_score=%.1f, forge=%s)",
        len(selected),
        len(tools),
        best_score,
        include_forge,
    )
    return selected


# Words that signal the user wants Orion to *do* or *look up* something,
# beyond the per-tool aliases above.
_ACTION_WORDS = frozenset(
    """open close launch run install uninstall download upload search find look browse fetch
    send email message call remind schedule create write save delete remove move copy rename
    edit update change set turn switch enable disable start stop kill restart shutdown reboot
    play pause resume skip volume screenshot screen camera see file files folder directory
    read show list check calculate compute convert translate summarize summarise research
    weather news price stock time date today tomorrow yesterday latest current git commit
    code python script terminal command memory remember recall note notes vault approve deny
    queue pending clipboard battery wifi network cpu disk url website link http api""".split()
)

_CONVERSATIONAL_MAX_WORDS = 20


def is_conversational(query: str) -> bool:
    """True when `query` is plain conversation that needs no tool.

    The tool agent costs a full extra model round trip (tool selection,
    then the answer) and, for a small local model, invites spurious calls:
    "can you hear me?" triggered a Wi-Fi status lookup and took ~48 s.
    Plain conversation streams straight from the engine instead. This
    errs toward the agent: any action word, tool alias, or long request
    goes through it.
    """
    words = _WORD_RE.findall((query or "").lower())
    if not words or len(words) > _CONVERSATIONAL_MAX_WORDS:
        return False
    signal = _ACTION_WORDS | {a for aliases in _ALIASES.values() for a in aliases}
    return not any(w in signal for w in words)


# Facts that change from moment to moment. A remembered answer to one of these
# is stale by definition.
_LIVE_DATA_WORDS = frozenset(
    """weather temperature forecast rain raining humidity now today tonight tomorrow current
    currently latest live news headlines price prices stock stocks score scores battery cpu
    wifi volume brightness uptime clipboard traffic""".split()
)


def wants_live_data(query: str) -> bool:
    """True when `query` asks about something that changes over time.

    Recalled memories are skipped for these: asked "what's the weather in
    Chennai right now", the model repeated a remembered answer from hours
    earlier instead of calling a tool.
    """
    words = set(_WORD_RE.findall((query or "").lower()))
    return bool(words & _LIVE_DATA_WORDS) or "right now" in (query or "").lower()


__all__ = ["select_tools", "score_tool", "is_conversational", "wants_live_data", "FORGE_TOOL"]
