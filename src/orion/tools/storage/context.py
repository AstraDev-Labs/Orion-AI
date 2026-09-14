"""Context injection — retrieve relevant memory and inject into prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from orion.core.events import EventType, get_event_bus
from orion.core.types import Message, Role
from orion.tools.storage._stubs import MemoryBackend, RetrievalResult


@dataclass(slots=True)
class ContextConfig:
    """Controls how retrieved context is injected into prompts."""

    enabled: bool = True
    top_k: int = 5
    min_score: float = 0.0
    max_context_tokens: int = 2048


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace split."""
    return len(text.split())


def format_context(results: List[RetrievalResult]) -> str:
    """Format retrieval results into a context block.

    Each result is prefixed with its source attribution.
    """
    if not results:
        return ""

    lines = []
    for r in results:
        source_tag = f"[Source: {r.source}]" if r.source else ""
        if source_tag:
            lines.append(f"{source_tag} {r.content}")
        else:
            lines.append(r.content)

    return "\n\n".join(lines)


def build_context_message(
    results: List[RetrievalResult],
) -> Message:
    """Create a system message with formatted context."""
    context_text = format_context(results)
    content = (
        "The following context was retrieved from the user's memory/knowledge"
        " base. If the user's question asks about their memory, notes, vault,"
        " preferences, plans, or personal context, answer directly from this"
        " retrieved context. Do not claim you lack memory when relevant context"
        " is present. Cite sources where applicable. Past replies in it may be"
        " out of date or wrong: current tool results and live facts win.\n\n" + context_text
    )
    return Message(role=Role.SYSTEM, content=content)


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "according",
    "about",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "memory",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
}


def _fallback_query(query: str) -> str:
    """Reduce a natural-language question to retrieval-heavy keywords."""
    words = re.findall(r"[A-Za-z0-9_.-]+", query)
    kept = [word for word in words if word.lower() not in _STOPWORDS]
    return " ".join(kept)


def _fallback_queries(query: str) -> List[str]:
    """Return progressively broader keyword queries."""
    fallback = _fallback_query(query)
    if not fallback:
        return []
    words = fallback.split()
    queries = [fallback]
    # FTS5 MATCH is strict, so try compact windows and finally single terms.
    for size in (3, 2):
        if len(words) <= size:
            continue
        for index in range(0, len(words) - size + 1):
            queries.append(" ".join(words[index : index + size]))
    queries.extend(words)

    seen = set()
    unique = []
    for item in queries:
        key = item.lower()
        if key not in seen and item != query:
            seen.add(key)
            unique.append(item)
    return unique


def inject_context(
    query: str,
    messages: List[Message],
    backend: MemoryBackend,
    *,
    config: Optional[ContextConfig] = None,
) -> List[Message]:
    """Retrieve relevant context and prepend it to *messages*.

    Returns a **new** list — the original list is not mutated.
    If no results pass the score threshold, returns the original
    messages unchanged.

    Parameters
    ----------
    query:
        The user query to search for.
    messages:
        The existing message list.
    backend:
        The memory backend to search.
    config:
        Context injection settings (uses defaults if ``None``).
    """
    cfg = config or ContextConfig()
    if not cfg.enabled:
        return messages

    results = backend.retrieve(query, top_k=cfg.top_k)
    if not results:
        for fallback in _fallback_queries(query):
            results = backend.retrieve(fallback, top_k=cfg.top_k)
            if results:
                break

    # Filter by minimum score. A backend can raise the floor for its own score
    # scale: dense cosine scores unrelated chit-chat at ~0.45-0.58, so with the
    # default 0 every request carried five random past exchanges.
    floor = max(cfg.min_score, float(getattr(backend, "context_score_floor", 0.0) or 0.0))
    results = [r for r in results if r.score >= floor]

    # The same exchange is often stored more than once.
    seen_content: set[str] = set()
    results = [
        r for r in results
        if not (r.content.strip() in seen_content or seen_content.add(r.content.strip()))
    ]

    if not results:
        return messages

    # Truncate to max_context_tokens
    truncated: List[RetrievalResult] = []
    total_tokens = 0
    for r in results:
        tokens = _count_tokens(r.content)
        if total_tokens + tokens > cfg.max_context_tokens:
            break
        truncated.append(r)
        total_tokens += tokens

    if not truncated:
        return messages

    # Publish event
    bus = get_event_bus()
    bus.publish(
        EventType.MEMORY_RETRIEVE,
        {
            "context_injection": True,
            "query": query,
            "num_results": len(truncated),
            "total_tokens": total_tokens,
        },
    )

    # One copy, as a system message right after the existing system prompt.
    # It used to be pasted into the user's message as well ("Use this retrieved
    # memory to answer the question. ... Question: set volume to 40"): every
    # memory was sent twice, an action request was reframed as a memory
    # question, and the tool router scored the memories instead of the request.
    ctx_msg = build_context_message(truncated)
    enriched_messages = list(messages)
    insert_at = 0
    while insert_at < len(enriched_messages) and enriched_messages[insert_at].role == Role.SYSTEM:
        insert_at += 1
    enriched_messages.insert(insert_at, ctx_msg)
    return enriched_messages


__all__ = [
    "ContextConfig",
    "build_context_message",
    "format_context",
    "inject_context",
]
