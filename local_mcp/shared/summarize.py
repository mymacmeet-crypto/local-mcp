"""Lightweight, deterministic extractive summarization helpers.

These helpers build short summaries and key-point lists from source text
(search snippets or fetched page content) *without* an LLM. They are
intentionally simple: the goal is to orient the calling model to the evidence
so it can decide what to read and synthesize, not to replace the model's own
answer. Summaries are extractive (real sentences from the source), scored by a
term-frequency heuristic and biased toward any focus ``query`` terms.
"""

from __future__ import annotations

import re
from collections import Counter

DEFAULT_SUMMARY_CHARS = 900
DEFAULT_SUMMARY_SENTENCES = 4
DEFAULT_KEY_POINTS = 5
DEFAULT_KEY_POINT_CHARS = 220
MIN_SENTENCE_CHARS = 20

_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "other",
    "over",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "were",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def summarize_text(
    text: str,
    *,
    query: str = "",
    max_chars: int = DEFAULT_SUMMARY_CHARS,
    max_sentences: int = DEFAULT_SUMMARY_SENTENCES,
) -> str:
    """Return a short extractive summary of ``text``.

    The highest-scoring sentences are selected, then re-ordered by their
    original position so the summary still reads top-to-bottom. When no scored
    sentence can be found the leading text is returned, trimmed to ``max_chars``.
    """
    candidates = _sentence_candidates(text)
    if not candidates:
        return ""

    focus_terms = set(keywords(query))
    scored = _score_sentences(candidates, focus_terms)
    if not scored:
        return _limit_text(" ".join(candidates), max_chars)

    top = sorted(scored, reverse=True)[:max_sentences]
    ordered = sorted(top, key=lambda item: item[1])
    return _limit_text(" ".join(sentence for _score, _index, sentence in ordered), max_chars)


def extract_key_points(
    text: str,
    *,
    query: str = "",
    max_points: int = DEFAULT_KEY_POINTS,
    max_chars_each: int = DEFAULT_KEY_POINT_CHARS,
) -> list[str]:
    """Return up to ``max_points`` distinct key sentences, most relevant first."""
    candidates = _sentence_candidates(text)
    if not candidates:
        return []

    focus_terms = set(keywords(query))
    scored = _score_sentences(candidates, focus_terms)
    if not scored:
        scored = [(0.0, index, sentence) for index, sentence in enumerate(candidates)]

    points: list[str] = []
    seen: set[str] = set()
    for _score, _index, sentence in sorted(scored, reverse=True):
        trimmed = _limit_text(sentence, max_chars_each)
        key = trimmed.lower()
        if not trimmed or key in seen:
            continue
        seen.add(key)
        points.append(trimmed)
        if len(points) >= max_points:
            break
    return points


def keywords(text: str) -> list[str]:
    """Tokenize ``text`` into lowercase content words, dropping short stopwords."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", (text or "").lower())
    return [word for word in words if word not in _STOPWORDS]


def _score_sentences(candidates: list[str], focus_terms: set[str]) -> list[tuple[float, int, str]]:
    word_counts = Counter(word for candidate in candidates for word in keywords(candidate))
    scored: list[tuple[float, int, str]] = []
    for index, candidate in enumerate(candidates):
        words = keywords(candidate)
        if not words:
            continue
        unique_words = set(words)
        score = sum(word_counts[word] for word in unique_words) / max(len(unique_words), 1)
        score += len(unique_words & focus_terms) * 4
        scored.append((score, index, candidate))
    return scored


def _sentence_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        cleaned = " ".join(chunk.split())
        if len(cleaned) < MIN_SENTENCE_CHARS:
            continue
        candidates.append(cleaned)
    return candidates


def _limit_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if limit <= 0 or len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
