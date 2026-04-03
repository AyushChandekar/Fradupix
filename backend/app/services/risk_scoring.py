"""
Risk Scoring Service (SRS Section 3.7 & Appendix A)
Composite Risk Score = (0.30 x Forgery) + (0.25 x Duplicate) + (0.25 x ML Anomaly) + (0.20 x Rule-Based)
Weights and thresholds are configurable via admin settings panel.
"""
import logging
from typing import Dict, Any
from app.models import RiskLevel
from app.config import get_settings

logger = logging.getLogger(__name__)


class RiskScoringService:
    """Calculate and classify invoice risk scores per SRS FR-700."""

    def __init__(self):
        settings = get_settings()
        # SRS Appendix A: configurable weights
        self.weights = {
            "forgery": settings.RISK_WEIGHT_FORGERY,
            "duplicate": settings.RISK_WEIGHT_DUPLICATE,
            "anomaly": settings.RISK_WEIGHT_ANOMALY,
            "rules": settings.RISK_WEIGHT_RULES,
        }
        # SRS FR-702: configurable thresholds
        self.thresholds = {
            "low": (0, settings.RISK_THRESHOLD_LOW),
            "medium": (settings.RISK_THRESHOLD_LOW + 1, settings.RISK_THRESHOLD_MEDIUM),
            "high": (settings.RISK_THRESHOLD_MEDIUM + 1, settings.RISK_THRESHOLD_HIGH),
            "critical": (settings.RISK_THRESHOLD_HIGH + 1, settings.RISK_THRESHOLD_CRITICAL),
        }

    def update_weights(self, forgery: float = None, duplicate: float = None,
                       anomaly: float = None, rules: float = None):
        """FR-706: Allow administrators to configure risk score weights."""
        if forgery is not None:
            self.weights["forgery"] = forgery
        if duplicate is not None:
            self.weights["duplicate"] = duplicate
        if anomaly is not None:
            self.weights["anomaly"] = anomaly
        if rules is not None:
            self.weights["rules"] = rules

    def update_thresholds(self, low_max: int = None, medium_max: int = None,
                          high_max: int = None):
        """FR-706: Allow administrators to configure classification thresholds."""
        if low_max is not None:
            self.thresholds["low"] = (0, low_max)
            self.thresholds["medium"] = (low_max + 1, self.thresholds["medium"][1])
        if medium_max is not None:
            self.thresholds["medium"] = (self.thresholds["medium"][0], medium_max)
            self.thresholds["high"] = (medium_max + 1, self.thresholds["high"][1])
        if high_max is not None:
            self.thresholds["high"] = (self.thresholds["high"][0], high_max)
            self.thresholds["critical"] = (high_max + 1, 100)

    def compute_rule_based_score(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        SRS Appendix A: Rule-Based Flag Score derived from business rules:
        - Invoice amount exceeds vendor historical avg by >3 std deviations
        - Payment terms shorter than vendor norm
        - Invoice date on weekend/holiday
        - Round-number amounts exceeding threshold
        """
        score = 0
        flags = []

        total = float(invoice_data.get("total_amount", 0) or 0)
        tax = float(invoice_data.get("tax_amount", 0) or 0)

        # Round number amounts > $10,000
        if total > 10000 and total == int(total):
            score += 20
            flags.append("round_number_high_amount")

        # Unusual tax rate (outside 3-25% range)
        if total > 0 and tax > 0:
            tax_rate = tax / total
            if tax_rate > 0.25 or tax_rate < 0.03:
                score += 15
                flags.append(f"unusual_tax_rate_{tax_rate:.2%}")

        # Weekend invoice date
        invoice_date = invoice_data.get("invoice_date")
        if invoice_date and hasattr(invoice_date, "weekday"):
            if invoice_date.weekday() >= 5:  # Saturday=5, Sunday=6
                score += 15
                flags.append("weekend_invoice_date")

        # Very high amount
        if total > 100000:
            score += 15
            flags.append("very_high_amount")

        # Payment terms shorter than 15 days
        due_date = invoice_data.get("due_date")
        if invoice_date and due_date:
            try:
                days = (due_date - invoice_date).days
                if 0 < days < 15:
                    score += 15
                    flags.append(f"short_payment_terms_{days}_days")
            except (TypeError, AttributeError):
                pass

        # Vendor amount deviation (if provided from historical data)
        vendor_avg = float(invoice_data.get("vendor_avg_amount", 0) or 0)
        vendor_std = float(invoice_data.get("vendor_std_amount", 0) or 0)
        if vendor_avg > 0 and vendor_std > 0 and total > vendor_avg + 3 * vendor_std:
            score += 25
            flags.append("amount_exceeds_3_std_deviations")

        # Missing critical fields
        missing = []
        for field in ["invoice_number", "vendor_name", "total_amount"]:
            if not invoice_data.get(field):
                missing.append(field)
                score += 5
        if missing:
            flags.append(f"missing_fields:{','.join(missing)}")

        return {
            "rule_score": min(100, score),
            "flags": flags,
        }

    def calculate_risk_score(
        self,
        forgery_score: float = 0,
        duplicate_score: float = 0,
        anomaly_score: float = 0,
        invoice_data: Dict[str, Any] = None,
        # Legacy compatibility
        ocr_confidence: float = 100,
        metadata_flags: int = 0,
    ) -> Dict[str, Any]:
        """
        SRS Appendix A: Calculate composite risk score.
        Composite Risk Score = (0.30 x Forgery) + (0.25 x Duplicate) +
                               (0.25 x ML Anomaly) + (0.20 x Rule-Based)
        """
        # Compute rule-based score
        if invoice_data:
            rules_result = self.compute_rule_based_score(invoice_data)
            rules_score = rules_result["rule_score"]
            rule_flags = rules_result["flags"]
        else:
            # Legacy fallback: use ocr_confidence and metadata_flags
            ocr_risk = max(0, 100 - ocr_confidence)
            rules_score = min(100, ocr_risk * 0.5 + metadata_flags * 20)
            rule_flags = []

        # SRS Appendix A: Weighted aggregation
        risk_score = (
            forgery_score * self.weights["forgery"] +
            duplicate_score * self.weights["duplicate"] +
            anomaly_score * self.weights["anomaly"] +
            rules_score * self.weights["rules"]
        )

        risk_score = round(min(100, max(0, risk_score)), 2)
        risk_level = self._classify_risk(risk_score)

        # Determine recommended action (SRS FR-703/704/705)
        action = self._recommend_action(risk_level)

        # Build breakdown
        breakdown = {
            "forgery": {
                "score": round(forgery_score, 2),
                "weight": self.weights["forgery"],
                "contribution": round(forgery_score * self.weights["forgery"], 2),
            },
            "duplicate": {
                "score": round(duplicate_score, 2),
                "weight": self.weights["duplicate"],
                "contribution": round(duplicate_score * self.weights["duplicate"], 2),
            },
            "anomaly": {
                "score": round(anomaly_score, 2),
                "weight": self.weights["anomaly"],
                "contribution": round(anomaly_score * self.weights["anomaly"], 2),
            },
            "rules": {
                "score": round(rules_score, 2),
                "weight": self.weights["rules"],
                "contribution": round(rules_score * self.weights["rules"], 2),
                "flags": rule_flags,
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
        """SRS FR-702: Classify risk level from score."""
        if score <= self.thresholds["low"][1]:
            return RiskLevel.LOW
        elif score <= self.thresholds["medium"][1]:
            return RiskLevel.MEDIUM
        elif score <= self.thresholds["high"][1]:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    def _recommend_action(self, level: RiskLevel) -> str:
        """SRS FR-703/704/705: Recommended action based on risk level."""
        actions = {
            RiskLevel.LOW: "auto_approve",         # FR-703
            RiskLevel.MEDIUM: "manual_review",      # FR-704
            RiskLevel.HIGH: "manual_review",        # FR-704
            RiskLevel.CRITICAL: "block_and_alert",  # FR-705
        }
        return actions.get(level, "manual_review")

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
