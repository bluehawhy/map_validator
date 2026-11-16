"""Road-present versus forward-obstruction candidate comparison."""
from .common import compare_basic


def compare(expected: dict, observed: dict) -> dict:
    result = compare_basic(expected, observed, "road_exists")
    if result["expected_value"] is True and result["observed_value"] is False:
        result["reason"] = (
            "입력툴에는 도로가 있지만 로드뷰 전방 중앙에는 건물 등 비도로 영역이 "
            "우세합니다. 촬영 위치와 해당 도로를 사람이 확인하세요."
        )
    return result
