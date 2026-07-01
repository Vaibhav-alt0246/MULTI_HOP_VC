"""Evaluation metric helpers for retrieval and generation checks."""

from __future__ import annotations

from collections.abc import Sequence


def recall_at_k(
    ranked_results: Sequence[Sequence[dict]],
    expected_sources: Sequence[str],
    k: int,
    source_key: str = "source",
) -> float:
    """
    Compute Recall@K for ranked retrieval outputs.

    ``ranked_results[i]`` is the ordered result list for query ``i`` and
    ``expected_sources[i]`` is the source label that should appear in the top K.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if len(ranked_results) != len(expected_sources):
        raise ValueError("ranked_results and expected_sources must have equal length")
    if not expected_sources:
        return 0.0

    hits = 0
    for results, expected in zip(ranked_results, expected_sources):
        top_k = results[:k]
        if any(result.get(source_key) == expected for result in top_k):
            hits += 1
    return hits / len(expected_sources)


def recall_at_ks(
    ranked_results: Sequence[Sequence[dict]],
    expected_sources: Sequence[str],
    ks: Sequence[int] = (1, 3, 5),
    source_key: str = "source",
) -> dict[str, float]:
    """Compute Recall@K for several K values."""
    return {
        f"recall@{k}": recall_at_k(ranked_results, expected_sources, k, source_key)
        for k in ks
    }


def audit_trail_coverage(questions: Sequence[dict]) -> float:
    """Fraction of generated questions that include a non-empty audit trail."""
    if not questions:
        return 0.0
    covered = sum(1 for q in questions if q.get("audit_trail"))
    return covered / len(questions)
