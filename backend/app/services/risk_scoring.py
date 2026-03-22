"""
Risk Scoring Service
Combines all fraud analysis results into a unified risk score
"""
import logging
from typing import Dict, Any
from app.models import RiskLevel

logger = logging.getLogger(__name__)


class RiskScoringService:
    """Calculate and classify invoice risk scores."""

    # Weight configuration
    WEIGHTS = {
        "forgery": 0.30,
        "duplicate": 0.25,
        "anomaly": 0.25,
        "ocr_confidence": 0.10,
        "metadata": 0.10,
    }

    # Risk level thresholds
    THRESHOLDS = {
        "low": (0, 30),
        "medium": (31, 60),
        "high": (61, 80),
        "critical": (81, 100),
    }

    def calculate_risk_score(
        self,
        forgery_score: float = 0,
        duplicate_score: float = 0,
        anomaly_score: float = 0,
        ocr_confidence: float = 100,
        metadata_flags: int = 0,
    ) -> Dict[str, Any]:
        """
        Calculate composite risk score from individual analysis results.
        
        Score = Σ(wi × si):
        - Forgery score (0-100)      × 0.30
        - Duplicate score (0-100)    × 0.25
        - Anomaly score (0-100)      × 0.25
        - OCR confidence (inverted)  × 0.10
        - Metadata flags             × 0.10
        """
        # Invert OCR confidence (low confidence = higher risk)
        ocr_risk = max(0, 100 - ocr_confidence)
        
        # Normalize metadata flags to 0-100
        metadata_score = min(100, metadata_flags * 20)

        # Weighted sum
        risk_score = (
            forgery_score * self.WEIGHTS["forgery"] +
            duplicate_score * self.WEIGHTS["duplicate"] +
            anomaly_score * self.WEIGHTS["anomaly"] +
            ocr_risk * self.WEIGHTS["ocr_confidence"] +
            metadata_score * self.WEIGHTS["metadata"]
        )

        risk_score = round(min(100, max(0, risk_score)), 2)
        risk_level = self._classify_risk(risk_score)

        # Determine recommended action
        action = self._recommend_action(risk_score, risk_level)

        # Build breakdown
        breakdown = {
            "forgery": {
                "score": round(forgery_score, 2),
                "weight": self.WEIGHTS["forgery"],
                "contribution": round(forgery_score * self.WEIGHTS["forgery"], 2),
            },
            "duplicate": {
                "score": round(duplicate_score, 2),
                "weight": self.WEIGHTS["duplicate"],
                "contribution": round(duplicate_score * self.WEIGHTS["duplicate"], 2),
            },
            "anomaly": {
                "score": round(anomaly_score, 2),
                "weight": self.WEIGHTS["anomaly"],
                "contribution": round(anomaly_score * self.WEIGHTS["anomaly"], 2),
            },
            "ocr_confidence": {
                "score": round(ocr_risk, 2),
                "weight": self.WEIGHTS["ocr_confidence"],
                "contribution": round(ocr_risk * self.WEIGHTS["ocr_confidence"], 2),
            },
            "metadata": {
                "score": round(metadata_score, 2),
                "weight": self.WEIGHTS["metadata"],
                "contribution": round(metadata_score * self.WEIGHTS["metadata"], 2),
            },
        }

        return {
            "risk_score": risk_score,
            "risk_level": risk_level.value,
            "recommended_action": action,
            "breakdown": breakdown,
            "dominant_risk": self._find_dominant_risk(breakdown),
        }

    def _classify_risk(self, score: float) -> RiskLevel:
        """Classify risk level from score."""
        if score <= 30:
            return RiskLevel.LOW
        elif score <= 60:
            return RiskLevel.MEDIUM
        elif score <= 80:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    def _recommend_action(self, score: float, level: RiskLevel) -> str:
        """Recommend action based on risk level."""
        actions = {
            RiskLevel.LOW: "auto_approve",
            RiskLevel.MEDIUM: "flag_for_review",
            RiskLevel.HIGH: "requires_audit",
            RiskLevel.CRITICAL: "block_and_alert",
        }
        return actions.get(level, "flag_for_review")

    def _find_dominant_risk(self, breakdown: Dict) -> str:
        """Find the highest contributing risk factor."""
        max_contribution = 0
        dominant = "none"
        
        for factor, data in breakdown.items():
            if data["contribution"] > max_contribution:
                max_contribution = data["contribution"]
                dominant = factor
        
        return dominant


# Singleton
risk_scoring_service = RiskScoringService()
