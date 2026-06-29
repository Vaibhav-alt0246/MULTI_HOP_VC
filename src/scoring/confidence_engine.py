"""Confidence scoring for VC risk evidence chains."""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class ConfidenceEngine:
    """
    Centralized mathematical engine for venture-capital risk scoring.

    It calculates final confidence from a category-specific base score, a
    semantic similarity value when available, and a path-length decay penalty.
    """

    def __init__(self, base_decay_rate: float = 0.90) -> None:
        self.decay_rate = base_decay_rate

    def compute_risk_metrics(
        self,
        category: str,
        path_length: int,
        base_similarity: float = 1.0,
    ) -> tuple[float, str]:
        """Return ``(final_confidence_score, severity_level)``."""
        if category == "Commercial License":
            base_score = 1.00
        elif category == "Proprietary Claim Mismatch":
            base_score = 0.95
        elif category == "IP Overlap":
            base_score = base_similarity
        else:
            base_score = 0.50

        penalty_hops = max(0, path_length - 1)
        decay_multiplier = self.decay_rate ** penalty_hops
        final_confidence = round(base_score * decay_multiplier, 3)
        severity = self._map_severity(final_confidence, category)
        return final_confidence, severity

    def _map_severity(self, confidence: float, category: str) -> str:
        """Map a numeric confidence value to a VC-standard severity label."""
        if category == "Commercial License" and confidence >= 0.80:
            return "CRITICAL"
        if confidence >= 0.85:
            return "CRITICAL"
        if confidence >= 0.65:
            return "HIGH"
        if confidence >= 0.40:
            return "MODERATE"
        return "LOW"


def score_confidence(
    category: str,
    path_length: int,
    base_similarity: float = 1.0,
    base_decay_rate: float = 0.90,
) -> dict:
    """Functional wrapper for callers that do not need to hold engine state."""
    confidence, severity = ConfidenceEngine(base_decay_rate).compute_risk_metrics(
        category=category,
        path_length=path_length,
        base_similarity=base_similarity,
    )
    return {"confidence_score": confidence, "severity": severity}
