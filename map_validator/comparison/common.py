"""Shared conservative candidate comparison and evidence metadata."""
from __future__ import annotations

from ..stage_types import FIELD_LABELS


def compare_basic(expected: dict, observed: dict, field: str) -> dict:
    lhs, rhs = expected.get("value"), observed.get("value")
    if lhs is None or rhs is None:
        status = "insufficient_evidence"
        reason = "입력툴 기대값 또는 실제 로드뷰 관측값의 근거가 부족합니다."
    elif lhs == rhs:
        status = "match_candidate"
        reason = "입력툴·로드뷰 후보 값이 같습니다. 실제 현장 검수가 필요합니다."
    else:
        status = "mismatch_review"
        reason = "입력툴 기대값과 로드뷰 관측값이 다릅니다. 사람 검수가 필요합니다."
    return {
        "status": status,
        "verdict": None,
        "expected_value": lhs,
        "observed_value": rhs,
        "field": field,
        "label": FIELD_LABELS[field],
        "reason": reason,
        "expected_confidence": expected.get("confidence"),
        "observed_confidence": observed.get("confidence"),
    }
