"""Expected road-connection candidate from colored route topology."""
import numpy as np

from ..findings import candidate, unknown
from ...line_geometry import extract_line_geometry

_EXPECTED_TURN = {
    "after_left": "left",
    "after_straight": "straight",
    "after_right": "right",
}


def extract_road_connection(image: np.ndarray, stage: str) -> tuple[dict, np.ndarray, dict]:
    if stage == "before":
        return unknown("진입 단계는 도로 연결 후보 비교 대상이 아닙니다."), image.copy(), {
            "status": "unknown", "expected_turn": "unknown"
        }
    route, overlay = extract_line_geometry(image)
    expected = _EXPECTED_TURN[stage]  # Legacy four-stage camera workflow only.
    if route.get("status") == "candidate" and route.get("expected_turn") == expected:
        result = candidate(
            True, "colored_route_topology_candidate",
            "하늘색 진입→주황색 연결→파란색 진출 경로가 해당 촬영 시점과 이어지는 후보입니다.",
            .62,
        )
    else:
        result = unknown("진출 경로를 확정할 수 없습니다. 입력툴 링크와 촬영 시점을 확인하세요.")
    return result, overlay, route
