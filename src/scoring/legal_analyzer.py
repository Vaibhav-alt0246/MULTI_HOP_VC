"""Legal risk scoring for patent evidence."""

from __future__ import annotations


class LegalRiskAnalyzer:
    """
    Scores a patent metadata dict for IP infringement risk.

    Expected input keys include ``status``, ``license_type``, ``jurisdiction``,
    ``assignee``, ``legal_claims``, and ``legal_risk_flag``.
    """

    _W_ACTIVE = 0.40
    _W_COMMERCIAL = 0.30
    _W_JURISDICTION = 0.20
    _W_ASSIGNEE = 0.10

    _RESTRICTED_LICENSES = {
        "commercial restricted",
        "commercial",
        "proprietary",
        "all rights reserved",
    }

    _PERMISSIVE_LICENSES = {
        "apache-2.0",
        "mit",
        "bsd",
        "bsd-2",
        "bsd-3",
        "open",
        "public domain",
        "cc0",
        "lgpl",
    }

    def analyze(self, patent_data: dict) -> dict:
        """Return risk score, level, reasons, and overlapping legal signals."""
        status = (patent_data.get("status") or "UNKNOWN").upper()
        license_type = (patent_data.get("license_type") or "").lower()
        jurisdiction = (patent_data.get("jurisdiction") or "").upper()
        assignee = patent_data.get("assignee") or "UNKNOWN"
        legal_claims = patent_data.get("legal_claims") or []

        if status in ("EXPIRED", "PENDING"):
            return {
                "legal_risk_score": 0.0,
                "risk_level": "LOW",
                "reasons": [f"Patent is {status} - no enforceable claims exist"],
                "overlap_signals": [],
            }

        if patent_data.get("legal_risk_flag") is False:
            return {
                "legal_risk_score": 0.0,
                "risk_level": "LOW",
                "reasons": ["Patent flagged non-risky by parser"],
                "overlap_signals": [],
            }

        if any(perm in license_type for perm in self._PERMISSIVE_LICENSES):
            return {
                "legal_risk_score": 0.0,
                "risk_level": "LOW",
                "reasons": [f"Permissive license ({patent_data.get('license_type')})"],
                "overlap_signals": [],
            }

        score = 0.0
        reasons: list[str] = []

        if status == "ACTIVE":
            score += self._W_ACTIVE
            reasons.append("Patent is active - claims are enforceable")

        if any(restr in license_type for restr in self._RESTRICTED_LICENSES):
            score += self._W_COMMERCIAL
            reasons.append(
                f"License type '{patent_data.get('license_type')}' restricts commercial use"
            )

        if jurisdiction == "US":
            score += self._W_JURISDICTION
            reasons.append("US jurisdiction - strong ITC / federal court enforcement")
        elif jurisdiction in ("EU", "GB", "UK", "DE", "FR"):
            score += self._W_JURISDICTION * 0.6
            reasons.append(f"{jurisdiction} jurisdiction - moderate enforcement risk")

        if assignee.upper() not in ("UNKNOWN", "", "N/A"):
            score += self._W_ASSIGNEE
            reasons.append(f"Patent held by named entity: '{assignee}'")

        score = round(min(score, 1.0), 2)
        if score >= 0.7:
            risk_level = "HIGH"
        elif score >= 0.4:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return {
            "legal_risk_score": score,
            "risk_level": risk_level,
            "reasons": reasons,
            "overlap_signals": legal_claims,
        }


def analyze_legal_risk(patent_data: dict) -> dict:
    """Functional wrapper around ``LegalRiskAnalyzer``."""
    return LegalRiskAnalyzer().analyze(patent_data)
