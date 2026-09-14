"""Per-turn live context: the real clock, who the user is, and greeting rules.

A local model has no clock and no idea who it is talking to. Left alone it
asks the user for the date before opening an app, calls the user "Orion",
and opens every reply with "Greetings!". Each turn therefore gets a short
system note built from real signals: the machine's local time, the name
stored in ~/.orion/USER.md, and whether this is the first turn.
"""

from __future__ import annotations

import logging
import platform
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

USER_PATH = Path("~/.orion/USER.md").expanduser()

_NAME_LINE = re.compile(r"^-\s*Name:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# "my name is Alex", "call me Alex", "name's Alex", "I am called Alex".
# "I'm X" is deliberately excluded: "I'm fine" / "I'm busy" are not names.
_NAME_STATEMENT = re.compile(
    r"\b(?:my name is|my name's|call me|name's|i am called|i'm called|you can call me)\s+"
    r"([A-Za-z][A-Za-z'\-]{1,30}(?:\s+[A-Za-z][A-Za-z'\-]{1,30})?)",
    re.IGNORECASE,
)

# Words that follow "call me" / "my name is" without being a name. A misheard
# "...call me? Not me." once saved the user's name as "Not Me".
_NOT_NAMES = frozenset(
    """later back tomorrow when now soon please maybe sometime again after before not no
    me you i we he she it they him her us them my your the a an and or but is are was be
    just really actually also so sure okay ok yes yeah fine good great here there this that
    what who how why orion called anything something nothing someone anyone nobody""".split()
)


def user_name(path: Path = USER_PATH) -> str:
    """The user's name: learned in USER.md, else ``channel.owner_name`` from config."""
    try:
        match = _NAME_LINE.search(path.read_text(encoding="utf-8"))
        if match and match.group(1).strip():
            return match.group(1).strip()
    except OSError:
        pass
    if path != USER_PATH:
        return ""  # an explicit profile path (tests) never falls back to live config
    try:
        from orion.core.config import load_config

        return (getattr(load_config().channel, "owner_name", "") or "").strip()
    except Exception:
        return ""


def capture_name(text: str, path: Path = USER_PATH) -> str:
    """Store a name the user states about themselves; return it, or ""."""
    match = _NAME_STATEMENT.search(text or "")
    if not match:
        return ""
    words = match.group(1).split()
    if not words or any(w.lower().strip("'-") in _NOT_NAMES for w in words):
        return ""
    name = " ".join(w[:1].upper() + w[1:] for w in words)
    if name.lower() == "orion":
        return ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if _NAME_LINE.search(existing):
            updated = _NAME_LINE.sub(f"- Name: {name}", existing, count=1)
        else:
            updated = existing.rstrip() + ("\n" if existing.strip() else "") + f"- Name: {name}\n"
        path.write_text(updated, encoding="utf-8")
    except OSError:
        logger.warning("Could not save user name to %s", path, exc_info=True)
        return ""
    return name


def build_live_context(user_text: str, first_turn: bool, path: Path = USER_PATH) -> str:
    """System note with the real local time, the user's identity, and tone rules."""
    just_learned = capture_name(user_text, path)
    name = just_learned or user_name(path)

    now = datetime.now().astimezone()
    lines = [
        "LIVE CONTEXT (real, read from this computer right now; trust it):",
        f"- Local date and time: {now.strftime('%A, %d %B %Y, %I:%M %p')} ({now.tzname()})",
        f"- Operating system: {platform.system()} {platform.release()}",
        "You are Orion, the assistant. The user is a different person; never call the user Orion.",
    ]
    if just_learned:
        lines.append(
            f"The user just told you their name is {name}. It is saved permanently. "
            f"Acknowledge it warmly and call them {name} from now on."
        )
    elif name:
        lines.append(f"The user's name is {name}. Address them as {name} where natural.")
    else:
        lines.append(
            "You do not know the user's name yet. After answering, politely ask what "
            "you should call them (once, not every message)."
        )
    if first_turn:
        lines.append("This is the start of the conversation: a brief greeting is fine.")
    else:
        lines.append(
            "The conversation is already underway: do NOT greet again. Never open with "
            "'Greetings', 'Hello' or similar; answer directly."
        )
    lines.append(
        "Use the date and time above whenever they are relevant; never ask the user for "
        "them and never claim you cannot know them."
    )
    return "\n".join(lines)


def speech_prompt(path: Path = USER_PATH) -> str:
    """Vocabulary hint for Whisper: who is talking and how addresses are written.

    Measured on whisper-base with a spoken "12345678 at example dot edu":
    no hint gave "example.e" (live, "exampel.edu"); this hint gave "example.edu"
    and spelled "Alex" correctly, at no extra latency.
    """
    name = user_name(path)
    who = f" The user's name is {name}." if name else ""
    return (
        f"Conversation with Orion, a voice assistant.{who} Email addresses are written "
        "like 12345678@college.edu.in or name@gmail.com."
    )


def is_prompt_echo(transcript: str, prompt: str) -> bool:
    """True when a transcript is mostly Whisper repeating its initial prompt.

    Whisper conditions on the prompt as if it were earlier speech; given near
    silence it sometimes emits that text back ("The user's name is Alex.
    Email addresses are written like 12345678..."). Real speech shares few
    words with the hint, so a high overlap means there was nothing to hear.
    """
    words = re.findall(r"[a-z0-9']+", (transcript or "").lower())
    if not words:
        return False
    hint = set(re.findall(r"[a-z0-9']+", (prompt or "").lower()))
    overlap = sum(1 for w in words if w in hint) / len(words)
    return len(words) >= 3 and overlap >= 0.7


# "12345678 at example.edu" / "name at gmail dot com" -> a real address. The
# domain must end in a letters-only TLD, so "meet at 5.30" is left alone.
_SPOKEN_DOT = re.compile(r"\s+dot\s+", re.IGNORECASE)
_SPOKEN_EMAIL = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._%+-]*)\s+at\s+([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,6})\b",
    re.IGNORECASE,
)


def normalize_transcript(text: str) -> str:
    """Rewrite spoken email addresses into their written form."""
    if not text or " at " not in f" {text.lower()} ":
        return text
    text = re.sub(
        r"\b(at\s+[A-Za-z0-9-]+(?:\s+dot\s+[A-Za-z0-9-]+)+)\b",
        lambda m: _SPOKEN_DOT.sub(".", m.group(1)),
        text,
        flags=re.IGNORECASE,
    )
    # "look at google.com" must stay a sentence: a plain word before "at" is
    # only an address when the user is talking about email.
    about_email = bool(re.search(r"\b(e-?mail|mail|address|inbox)\b", text, re.IGNORECASE))

    def _join(m: "re.Match[str]") -> str:
        local, domain = m.group(1), m.group(2)
        if not (about_email or any(ch.isdigit() for ch in local)):
            return m.group(0)
        return f"{local}@{domain.lower()}"

    return _SPOKEN_EMAIL.sub(_join, text)


__all__ = [
    "build_live_context",
    "capture_name",
    "is_prompt_echo",
    "normalize_transcript",
    "speech_prompt",
    "user_name",
]
