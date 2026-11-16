"""Presence-only stop-line comparison, with REVIEW for uncertain imagery."""
from .common import compare_basic


def compare(expected: dict, observed: dict) -> dict:
    result = compare_basic(expected, observed, "stop_line")
    lhs, rhs = result["expected_value"], result["observed_value"]
    if lhs is None or rhs is None:
        result["verdict"] = "REVIEW"
        result["reason"] = "정지선 유무를 확정할 수 없습니다. 횡단보도는 정지선이 아니므로 사람이 확인해야 합니다."
    elif lhs == rhs:
        result["verdict"] = "PASS"
        result["reason"] = "입력툴의 시안색 가로 정지선과 로드뷰 정지선 존재 여부가 같습니다."
    else:
        result["verdict"] = "FAIL"
        result["reason"] = "입력툴의 시안색 가로 정지선과 로드뷰 정지선 존재 여부가 다릅니다."
    return result
