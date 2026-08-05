"""12-Model Ensemble STT Verifier for J.A.R.V.I.S.

Fires all 12 NVIDIA NIM models in parallel against a raw Whisper transcription.
Uses edit-distance clustering + majority voting to pick the best interpretation.

Usage:
    from orion.speech.ensemble_verifier import EnsembleVerifier
    verifier = EnsembleVerifier(engine)
    result = verifier.verify("Tomeradu CM")
    # result.text      → "Tamil Nadu CM"
    # result.status    → "CORRECTED"
    # result.votes     → 9
    # result.confident → True
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The 12-model ensemble — all available on NVIDIA NIM (free cloud tier)
# ---------------------------------------------------------------------------

ENSEMBLE_MODELS: list[str] = [
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.2-3b-instruct",
    "meta/llama-3.3-70b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "google/gemma-2-9b-it",
    "google/gemma-2-27b-it",
    "microsoft/phi-4-mini-instruct",
    "microsoft/phi-3.5-moe-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "ibm/granite-3.0-8b-instruct",
    "deepseek-ai/deepseek-v4-flash",
]

# Per-model call timeout (seconds)
MODEL_TIMEOUT = 6.0

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    status: str          # "CLEAR" | "CORRECTED" | "UNCLEAR"
    text: str            # Final chosen text
    original: str        # Raw Whisper output
    votes: int           # Votes for winning interpretation (0-12)
    total: int           # How many models responded
    confidence: str      # "HIGH" | "MEDIUM" | "LOW"
    corrections: list[str] = field(default_factory=list)  # Per-model answers
    elapsed_ms: float = 0.0

    @property
    def confident(self) -> bool:
        return self.confidence in ("HIGH", "MEDIUM")


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a speech-to-text error corrector for J.A.R.V.I.S., an AI assistant "
    "running in India. The user speaks in English with Indian accent and terminology."
)

_USER_TEMPLATE = """The following text was captured from a microphone and likely has transcription errors:

Transcribed: "{text}"

Your task: figure out what the user MOST LIKELY said, given:
- Indian geography, politics, culture (e.g. Tamil Nadu, Modi, Sensex, Reliance)
- Tech/PC terms (File Explorer, Chrome, Task Manager, notepad, etc.)
- Common voice assistant commands (open, search, play, what is, who is, what time)

Respond with EXACTLY ONE of these three formats (no explanation, no extra text):
  CORRECTED: <what they actually said>
  CLEAR
  UNCLEAR

Examples:
  "Tomeradu CM" → CORRECTED: Tamil Nadu Chief Minister
  "orion can you here me" → CORRECTED: Orion can you hear me
  "5x Pro Explorer" → CORRECTED: File Explorer
  "what is the capital of France" → CLEAR
  "xzqp brrr fnarg" → UNCLEAR"""


class EnsembleVerifier:
    """Parallel 12-model STT verification with majority-vote consensus."""

    def __init__(self, engine, models: Optional[list[str]] = None) -> None:
        self._engine = engine
        self._virtual_personas = []
        if models:
            self._models = models
        else:
            try:
                available = self._engine.list_models()
                if available:
                    intersected = [m for m in ENSEMBLE_MODELS if m in available]
                    if intersected:
                        self._models = intersected
                    else:
                        # Find a strong local model for virtual ensembling
                        local_model = available[0]
                        for m in available:
                            if "orion" in m.lower():
                                local_model = m
                                break
                        # Create 5 virtual experts using the same model to save VRAM
                        self._models = [local_model] * 5
                        self._virtual_personas = [
                            "General Assistant",
                            "Indian Geography and Culture Expert",
                            "Software and Tech Support Engineer",
                            "Linguistics and Grammar Expert",
                            "Voice Command Intent Analyzer"
                        ]
                else:
                    self._models = ENSEMBLE_MODELS
            except Exception:
                self._models = ENSEMBLE_MODELS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, raw_text: str, timeout: float = MODEL_TIMEOUT) -> VerificationResult:
        """Run all models in parallel and return the consensus result."""
        t0 = time.monotonic()
        raw_responses: list[str] = []

        # Determine early exit threshold (majority of attempted models)
        early_exit_threshold = max(2, (len(self._models) // 2) + 1)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(self._models)))
        future_map = {}
        for i, model in enumerate(self._models):
            delay = i * 0.2  # stagger
            persona = self._virtual_personas[i] if self._virtual_personas else None

            def task(m=model, d=delay, p=persona):
                if d > 0:
                    time.sleep(d)
                return self._query_model(m, raw_text, timeout, p)

            future_map[pool.submit(task)] = model

        # Temporary store for early exit counting
        current_counts: dict[str, int] = {}
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=timeout + 1.0):
                try:
                    resp = future.result()
                    if resp:
                        raw_responses.append(resp)
                        # Normalize just for quick early-exit counting
                        quick_norm = self._normalize(resp)
                        current_counts[quick_norm] = current_counts.get(quick_norm, 0) + 1

                        if current_counts[quick_norm] >= early_exit_threshold:
                            logger.debug("Early exit threshold reached: %d votes", early_exit_threshold)
                            break
                except Exception as exc:
                    model = future_map[future]
                    logger.debug("Model %s failed: %s", model, exc)
        except concurrent.futures.TimeoutError:
            logger.debug("Ensemble verification timed out before all models completed.")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "Ensemble: %d/%d models responded in %.0fms",
            len(raw_responses),
            len(self._models),
            elapsed_ms,
        )
        return self._vote(raw_text, raw_responses, elapsed_ms)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _query_model(self, model: str, raw_text: str, timeout: float, persona: Optional[str] = None) -> str:
        """Call one model and return its raw response string."""
        from orion.core.types import Message, Role

        sys_prompt = _SYSTEM_PROMPT
        temp = 0.0
        if persona:
            sys_prompt += f"\nYour specific role in this ensemble is: {persona}."
            temp = 0.7  # Use higher temperature to get diverse opinions from the same model

        messages = [
            Message(role=Role.SYSTEM, content=sys_prompt),
            Message(role=Role.USER, content=_USER_TEMPLATE.format(text=raw_text)),
        ]
        result = self._engine.generate(
            messages,
            model=model,
            temperature=temp,
            max_tokens=60,
        )
        return result.get("content", "").strip()

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase + collapse whitespace + strip punctuation for comparison."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _edit_distance(a: str, b: str) -> int:
        """Simple Levenshtein distance."""
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, n + 1):
                tmp = dp[j]
                if a[i - 1] == b[j - 1]:
                    dp[j] = prev
                else:
                    dp[j] = 1 + min(prev, dp[j], dp[j - 1])
                prev = tmp
        return dp[n]

    def _parse_response(self, raw: str) -> tuple[str, str]:
        """Parse a model response into (status, text).
        Returns ("CORRECTED", text) | ("CLEAR", "") | ("UNCLEAR", "") | ("FAILED", "")
        """
        line = raw.strip().splitlines()[0].strip() if raw else ""
        upper = line.upper()

        if upper.startswith("CORRECTED:"):
            text = line[len("CORRECTED:"):].strip()
            return ("CORRECTED", text) if text else ("FAILED", "")
        if upper == "CLEAR" or upper.startswith("CLEAR "):
            return ("CLEAR", "")
        if upper == "UNCLEAR" or upper.startswith("UNCLEAR "):
            return ("UNCLEAR", "")

        # Model didn't follow format — treat as FAILED
        logger.debug("Unparseable response: %r", line[:80])
        return ("FAILED", "")

    def _vote(
        self, raw_text: str, responses: list[str], elapsed_ms: float
    ) -> VerificationResult:
        """Cluster parsed responses and pick the majority winner."""
        parsed: list[tuple[str, str]] = [self._parse_response(r) for r in responses]

        # Separate votes
        unclear_count = sum(1 for s, _ in parsed if s == "UNCLEAR")
        clear_count   = sum(1 for s, _ in parsed if s == "CLEAR")
        corrected_texts = [t for s, t in parsed if s == "CORRECTED" and t]
        total_responded = len(responses)

        # --- Cluster CORRECTED answers by edit distance ---
        if corrected_texts:
            clusters = self._cluster(corrected_texts, threshold=4)
            clusters.sort(key=lambda c: len(c), reverse=True)
            best_cluster = clusters[0]

            norm_counts: dict[str, int] = {}
            for t in best_cluster:
                key = self._normalize(t)
                norm_counts[key] = norm_counts.get(key, 0) + 1
            top_norm = max(norm_counts, key=lambda k: norm_counts[k])
            top_count = norm_counts[top_norm]
            winner_text = next(t for t in best_cluster if self._normalize(t) == top_norm)

            if top_count == 0:
                return VerificationResult(
                    original=raw_text,
                    text=raw_text,
                    status="UNCLEAR",
                    votes=0,
                    total=total_responded,
                    confidence="LOW",
                    elapsed_ms=elapsed_ms,
                )

            # If UNCLEAR or CLEAR have strictly more votes than the top correction, they win
            if unclear_count > top_count or clear_count > top_count:
                if unclear_count >= clear_count:
                    return VerificationResult(
                        status="UNCLEAR", text=raw_text, original=raw_text,
                        votes=unclear_count, total=total_responded,
                        confidence="LOW", elapsed_ms=elapsed_ms,
                    )
                else:
                    return VerificationResult(
                        status="CLEAR", text=raw_text, original=raw_text,
                        votes=clear_count, total=total_responded,
                        confidence="LOW", elapsed_ms=elapsed_ms,
                    )

            # Dynamic confidence thresholds based on actual successful responses
            votes_high = max(3, int(total_responded * 0.55))
            votes_medium = max(2, int(total_responded * 0.35))

            if top_count >= votes_high:
                conf = "HIGH"
                status = "CORRECTED" if top_norm != self._normalize(raw_text) else "VERIFIED"
            elif top_count >= votes_medium:
                conf = "MEDIUM"
                status = "CORRECTED" if top_norm != self._normalize(raw_text) else "VERIFIED"
            else:
                conf = "LOW"
                status = "UNCLEAR"

            return VerificationResult(
                status=status,
                text=winner_text if status != "UNCLEAR" else raw_text,
                original=raw_text,
                votes=top_count,
                total=total_responded,
                confidence=conf,
                corrections=best_cluster,
                elapsed_ms=elapsed_ms,
            )

        # Fallback: no useful CORRECTED responses
        # If models explicitly voted UNCLEAR more than CLEAR, mark it UNCLEAR.
        if unclear_count > clear_count:
            return VerificationResult(
                status="UNCLEAR", text=raw_text, original=raw_text,
                votes=unclear_count, total=total_responded,
                confidence="LOW", elapsed_ms=elapsed_ms,
            )

        return VerificationResult(
            status="CLEAR", text=raw_text, original=raw_text,
            votes=clear_count, total=total_responded,
            confidence="LOW" if total_responded == 0 else "MEDIUM", elapsed_ms=elapsed_ms,
        )

    def _cluster(self, texts: list[str], threshold: int = 4) -> list[list[str]]:
        """Group texts where normalized edit-distance ≤ threshold."""
        clusters: list[list[str]] = []
        norms: list[str] = [self._normalize(t) for t in texts]

        assigned = [False] * len(texts)
        for i, t in enumerate(texts):
            if assigned[i]:
                continue
            cluster = [t]
            assigned[i] = True
            for j in range(i + 1, len(texts)):
                if not assigned[j]:
                    if self._edit_distance(norms[i], norms[j]) <= threshold:
                        cluster.append(texts[j])
                        assigned[j] = True
            clusters.append(cluster)
        return clusters


__all__ = ["EnsembleVerifier", "VerificationResult", "ENSEMBLE_MODELS"]
