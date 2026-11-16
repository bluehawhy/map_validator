"""Common evidence values shared by feature-specific detectors."""
from __future__ import annotations


def unknown(reason: str) -> dict:
    """Unknown is distinct from confirmed absence (False) and count zero."""
    return {"value": None, "confidence": None, "method": "unverified", "reason": reason}


def candidate(value, method: str, reason: str, confidence: float) -> dict:
    return {
        "value": value,
        "confidence": round(float(confidence), 3),
        "method": method,
        "reason": reason,
    }
