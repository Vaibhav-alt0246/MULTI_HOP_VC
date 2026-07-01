"""Formal VC risk taxonomy and confidence analysis."""

from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from scoring.confidence_engine import ConfidenceEngine
except ImportError:  # direct script execution from this folder
    from src.scoring.confidence_engine import ConfidenceEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class RiskAnalyzer:
    """Convert structured evidence and contradictions into scored VC risks."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.confidence_engine = ConfidenceEngine()

    def analyze_evidence(self) -> list[dict]:
        logger.info("Initializing formal risk taxonomy and confidence analysis...")
        analyzed_risks: list[dict] = []

        evidence_path = self.data_dir / "processed" / "structured_evidence.json"
        if evidence_path.exists():
            data = json.loads(evidence_path.read_text(encoding="utf-8"))
            for ev in data.get("evidence_objects", []):
                risk_node = ev["risk_node"]
                category = ev["risk_type"]
                path_length = ev["path_length"]
                raw_similarity = ev.get("confidence_score", 1.0)
                path = ev["reasoning_path"]

                final_confidence, severity = self.confidence_engine.compute_risk_metrics(
                    category=category,
                    path_length=path_length,
                    base_similarity=raw_similarity,
                )

                action_required = "Standard review."
                if category == "Commercial License" and severity == "CRITICAL":
                    action_required = (
                        "Immediate legal review: codebase may be affected by strict obligations."
                    )
                # TODO Phase 3: replace raw FAISS cosine score with LegalRiskAnalyzer.analyze()
                # weighted score (active=0.40, commercial=0.30, jurisdiction=0.20, assignee=0.10).
                # Requires patent metadata (status, jurisdiction, assignee) from PatentsView API.
                # Currently unavailable — knowledge_base.json only contains head/tail/relationship triples.
                # Do NOT wire legal_analyzer.py here until patent_downloader fetches this metadata.
                elif category == "IP Overlap" and severity in ["HIGH", "MODERATE"]:
                    action_required = (
                        "Freedom-to-operate analysis required for semantic overlap."
                    )

                if severity in ["CRITICAL", "HIGH", "MODERATE"]:
                    analyzed_risks.append({
                        "severity": severity,
                        "category": category,
                        "target_entity": risk_node,
                        "confidence_score": final_confidence,
                        "recommended_action": action_required,
                        "evidence_chain": " -> ".join(path),
                    })

        contradiction_path = self.data_dir / "processed" / "contradiction_evidence.json"
        if contradiction_path.exists():
            logger.info("Scoring proprietary contradictions...")
            contra_data = json.loads(contradiction_path.read_text(encoding="utf-8"))
            for contra in contra_data.get("contradictions", []):
                final_confidence, severity = self.confidence_engine.compute_risk_metrics(
                    category=contra["risk_type"],
                    path_length=1,
                )
                analyzed_risks.append({
                    "severity": severity,
                    "category": contra["risk_type"],
                    "target_entity": contra["contradictory_module"],
                    "confidence_score": final_confidence,
                    "recommended_action": (
                        "Technical clarification: require founders to explain the discrepancy."
                    ),
                    "evidence_chain": (
                        f"Marketing Pitch: '{contra['claim_text'][:50]}...' -> "
                        f"Review Indicator: '{contra['contradictory_module']}'"
                    ),
                })

        output_path = self.data_dir / "processed" / "vc_risk_report.json"
        output_path.write_text(
            json.dumps({"identified_risks": analyzed_risks}, indent=2),
            encoding="utf-8",
        )
        logger.info("Escalated %d actionable risks.", len(analyzed_risks))
        logger.info("Formal VC risk report saved to %s", output_path)
        return analyzed_risks


def analyze_risk(data_dir: Path | str) -> list[dict]:
    """Functional wrapper for risk analysis."""
    return RiskAnalyzer(Path(data_dir)).analyze_evidence()


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    analyzer = RiskAnalyzer(project_root / "data")
    analyzer.analyze_evidence()
