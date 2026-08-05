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
        " is present. Cite sources where applicable.\n\n" + context_text
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

    # Filter by minimum score
    results = [r for r in results if r.score >= cfg.min_score]

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

    # Build context message and prepend. Also attach the context to the last
    # user message because small local chat models sometimes underweight
    # system-only memory instructions.
    ctx_msg = build_context_message(truncated)
    context_text = format_context(truncated)
    enriched_messages = list(messages)
    for index in range(len(enriched_messages) - 1, -1, -1):
        msg = enriched_messages[index]
        if msg.role == Role.USER:
            enriched_messages[index] = Message(
                role=msg.role,
                content=(
                    "Use this retrieved memory to answer the question.\n\n"
                    f"{context_text}\n\n"
                    f"Question: {msg.content}"
                ),
                name=msg.name,
                tool_call_id=msg.tool_call_id,
            )
            break
    return [ctx_msg] + enriched_messages


__all__ = [
    "ContextConfig",
    "build_context_message",
    "format_context",
    "inject_context",
]
