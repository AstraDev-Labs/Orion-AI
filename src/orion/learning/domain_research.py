"""Turn real web research into real SFT training pairs.

Feeds the same `LearningOrchestrator` pipeline that already mines SFT
pairs from conversation traces (`training/data.py`), but from genuinely
retrieved, cited web content instead of only what the user has said in
chat. Topics are picked autonomously from real current news (Hacker News,
zero-config, no API key -- always available; plus any RSS feeds the user
has separately connected) so this runs without the user ever having to
feed it a topic or a conversation to mine from. The real memory graph
(`tools/storage/knowledge_graph.py`) supplements this when it has
something relevant, but is never required. Every produced pair carries
its source URLs in metadata so it can be audited, not taken on faith.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from orion.core.json_extract import extract_json_list

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT = """You are extracting real, factual training material from the SOURCE TEXT below, which was retrieved from the web about "{topic}".

Write 1-3 question/answer pairs that:
- Ask something a person might genuinely ask about {topic}.
- Answer ONLY using facts actually present in the source text below. Never add anything the source doesn't say.
- If the source text doesn't contain enough real information to write a grounded pair, return an empty list -- do not invent content to fill the quota.

Respond with ONLY a JSON array, no other text:
[{{"question": "...", "answer": "..."}}, ...]

SOURCE TEXT:
{sources}
"""


def pick_topics_from_news(*, limit: int = 3) -> List[str]:
    """Real current topics with zero user input required.

    Hacker News needs no auth/config and is always attempted. Any RSS
    feeds the user has separately connected (`orion connect news_rss`)
    are added on top when present, for broader-than-tech coverage -- but
    their absence is never an error, since requiring that setup would
    contradict "the user must not feed any data".
    """
    topics: List[str] = []
    try:
        from orion.connectors.hackernews import HackerNewsConnector

        for doc in HackerNewsConnector().sync():
            if doc.title:
                topics.append(doc.title)
    except Exception:
        logger.debug("Hacker News topic fetch failed", exc_info=True)

    try:
        from orion.connectors.news_rss import NewsRSSConnector

        rss = NewsRSSConnector()
        if rss.is_connected():
            for doc in rss.sync():
                if doc.title:
                    topics.append(doc.title)
    except Exception:
        logger.debug("News RSS topic fetch failed", exc_info=True)

    return topics[:limit]


def pick_topics(*, kg_path, limit: int = 3) -> List[str]:
    """Real topics from the memory graph's most-connected recent entities --
    what the user has actually talked to Orion about, not an invented
    curriculum. Returns an empty list (honestly) if the graph doesn't exist
    yet or has nothing worth researching.
    """
    if not kg_path.exists():
        return []
    try:
        from orion.tools.storage.knowledge_graph import KnowledgeGraphMemory

        kg = KnowledgeGraphMemory(db_path=kg_path)
        try:
            rows = kg._conn.execute(
                """
                SELECT e.entity_id, e.name, COUNT(r.id) as degree
                FROM entities e
                LEFT JOIN relations r ON r.source_id = e.entity_id OR r.target_id = e.entity_id
                WHERE e.entity_type = 'memory'
                GROUP BY e.entity_id
                ORDER BY degree DESC, e.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [r[1] for r in rows if r[1]]
        finally:
            kg.close()
    except Exception:
        logger.debug("pick_topics failed", exc_info=True)
        return []


def research_topic(topic: str, *, max_results: int = 3) -> List[Dict[str, str]]:
    """Real web search for *topic*, returning [{"url", "text"}] -- an empty
    list if search fails or returns nothing, never fabricated content.
    """
    try:
        from orion.tools.web_search import WebSearchTool

        result = WebSearchTool(max_results=max_results).execute(query=topic, max_results=max_results)
        if not result.success or not result.content:
            return []
        # web_search's own format is "**Title**\nURL\nsnippet" blocks
        # separated by blank lines -- split back into (url, text) pairs
        # rather than re-fetching each URL, which keeps this dependency-free
        # (no Playwright/browser session required).
        sources = []
        for block in result.content.split("\n\n"):
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if len(lines) >= 2:
                url = next((ln for ln in lines if ln.startswith("http")), "")
                text = "\n".join(
                    ln
                    for ln in lines
                    if not ln.startswith("http") and not ln.startswith("**")
                )
                if url and text.strip():
                    sources.append({"url": url, "text": text.strip()})
        return sources
    except Exception:
        logger.debug("research_topic(%r) failed", topic, exc_info=True)
        return []


def synthesize_sft_pairs(
    topic: str,
    sources: List[Dict[str, str]],
    *,
    backend: Any,
    model: str,
) -> List[Dict[str, Any]]:
    """One real LLM call turning cited source text into SFT pairs shaped
    exactly like `TrainingDataMiner.extract_sft_pairs()`'s output (compatible
    as-is with `LoRATrainer.train()`), tagged with real source URLs.
    """
    if not sources:
        return []
    joined = "\n\n".join(f"[{s['url']}]\n{s['text'][:1500]}" for s in sources[:3])
    prompt = _SYNTHESIS_PROMPT.format(topic=topic, sources=joined)

    try:
        result = backend.generate_full(prompt, model=model, temperature=0.2, max_tokens=800)
        content = (result.get("content") or "").strip()
    except Exception:
        logger.warning("SFT synthesis for topic %r failed", topic, exc_info=True)
        return []

    # Tolerant extraction rather than a bare json.loads: models routinely wrap
    # the array in a fence or append a sentence of explanation, and a strict
    # parse raised "Extra data" and discarded the whole response -- so this
    # returned [] and the learning loop silently received no training data.
    parsed = extract_json_list(content)
    if parsed is None:
        logger.warning(
            "SFT synthesis for topic %r returned no parseable JSON (%d chars)",
            topic,
            len(content),
        )
        return []

    urls = [s["url"] for s in sources]
    pairs: List[Dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        q, a = item.get("question", "").strip(), item.get("answer", "").strip()
        if not q or not a:
            continue
        pairs.append(
            {
                "input": q,
                "output": a,
                "query_class": "domain_knowledge",
                "model": model,
                "feedback": None,  # not conversation feedback -- see metadata.source below
                "metadata": {"source": "web_research", "topic": topic, "sources": urls},
            }
        )
    return pairs


def run_research_cycle(*, config, limit_topics: int = 3) -> List[Dict[str, Any]]:
    """End-to-end: pick real topics, research each, synthesize grounded
    pairs. Autonomous by default -- current news (Hacker News, zero
    config) is the primary topic source, so this produces real training
    data with no user conversation history and no user-supplied topic
    required at all. Topics from the memory graph (what the user has
    actually discussed) are added on top when available, purely as a
    bonus signal, never as a requirement.

    Returns whatever real pairs were produced -- an empty list is an
    honest outcome (e.g. offline, or research turned up nothing
    groundable), not an error.
    """
    from orion.core.config import DEFAULT_CONFIG_DIR

    topics = pick_topics_from_news(limit=limit_topics)
    remaining = max(0, limit_topics - len(topics))
    if remaining:
        topics += pick_topics(kg_path=DEFAULT_CONFIG_DIR / "knowledge_graph.db", limit=remaining)
    if not topics:
        return []

    try:
        from orion.evals.backends.orion_direct import OrionDirectBackend

        backend = OrionDirectBackend(engine_key=config.engine.default)
    except Exception:
        logger.warning("Could not build inference backend for domain research", exc_info=True)
        return []

    all_pairs: List[Dict[str, Any]] = []
    for topic in topics:
        sources = research_topic(topic)
        if not sources:
            continue
        pairs = synthesize_sft_pairs(topic, sources, backend=backend, model=config.intelligence.default_model)
        all_pairs.extend(pairs)
    return all_pairs


__all__ = ["pick_topics", "research_topic", "synthesize_sft_pairs", "run_research_cycle"]
