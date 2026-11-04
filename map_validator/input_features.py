"""Conservative expected-feature extraction from HD_3D Tool snapshots.

Only visually supported findings are emitted. The cyan path itself does not
prove lane count, guidance line count, or arrow symbols.
"""
from __future__ import annotations

import cv2
import numpy as np

from .line_geometry import _canvas, extract_line_geometry
from .stage_types import fields_for_stage


def unknown(reason: str) -> dict:
    return {"value": None, "confidence": None, "method": "unverified", "reason": reason}


def candidate(value, method: str, reason: str, confidence: float) -> dict:
    return {
        "value": value, "confidence": round(float(confidence), 3),
        "method": method, "reason": reason,
    }


def _cyan_stop_line(image: np.ndarray, overlay: np.ndarray) -> dict:
    """Identify clear cyan horizontal segments; no segment != confirmed absent."""
    height, width = image.shape[:2]
    top, bottom = _canvas(image)
    hsv = cv2.cvtColor(image[top:bottom], cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, (78, 105, 125), (101, 255, 255))
    lines = cv2.HoughLinesP(
        cyan, 1, np.pi / 180, threshold=max(18, width // 38),
        minLineLength=max(27, int(width * .065)), maxLineGap=8,
    )
    if lines is None:
        return unknown("입력툴의 시안색 가로 정지선 후보가 명확하게 확인되지 않았습니다.")

    horizontal = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = map(int, line)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx < max(27, width * .065) or dy > max(4, dx * .18):
            continue
        # Avoid HUD/toolbars and extreme margins of the map viewport.
        cy = (y1 + y2) / 2 + top
        if cy < top + (bottom - top) * .18 or cy > bottom - (bottom - top) * .10:
            continue
        horizontal.append((dx, (x1, y1 + top), (x2, y2 + top)))
    if not horizontal:
        return unknown("시안색 선형은 보이나 명확한 가로 정지선 후보는 아닙니다.")

    longest = max(horizontal, key=lambda item: item[0])
    cv2.line(overlay, longest[1], longest[2], (20, 20, 255), 3)
    cv2.putText(
        overlay, "STOP LINE? REVIEW", (longest[1][0], max(20, longest[1][1] - 12)),
        cv2.FONT_HERSHEY_SIMPLEX, .48, (20, 20, 255), 2, cv2.LINE_AA,
    )
    return candidate(
        True, "cyan_horizontal_hough_candidate",
        "시안색 가로선 후보를 검출했습니다. 진입 선형 또는 다른 선과 구별해 직접 확인해야 합니다.",
        .50,
    )


def extract_input_features(image: np.ndarray, stage: str) -> tuple[dict, np.ndarray, dict]:
    """Return expected map markings, evidence drawing and optional route hint."""
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("입력툴 BGR 스크린샷을 읽을 수 없습니다.")

    features = {
        key: unknown("입력툴 스크린샷에서 이 항목을 신뢰성 있게 판독하지 못했습니다.")
        for key in fields_for_stage(stage)
    }
    overlay = image.copy()
    route = {"status": "unknown", "expected_turn": "unknown"}

    if stage == "before":
        features["stop_line"] = _cyan_stop_line(image, overlay)
        features["entry_lane_count"] = unknown(
            "진입 차로 수는 도로 경계선·차로 구분 데이터를 확보하기 전까지 임의 산출하지 않습니다."
        )
        features["lane_arrows"] = unknown(
            "방향 화살표/복합 화살표 모델 및 차로별 대응 정보가 아직 검증되지 않았습니다."
        )
        features["colored_guidance"] = unknown(
            "입력툴의 선형 색상과 실제 컬러유도선 표시는 다른 개념이므로 구분 검증이 필요합니다."
        )
    else:
        route, route_overlay = extract_line_geometry(image)
        # Keep extracted route visualization as an additional evidence layer.
        overlay = route_overlay
        expected = {"after_left": "left", "after_straight": "straight", "after_right": "right"}[stage]
        if route.get("status") == "candidate" and route.get("expected_turn") == expected:
            features["road_exists"] = candidate(
                True, "colored_route_topology_candidate",
                "하늘색 진입→주황색 연결→파란색 진출 경로가 해당 방향으로 이어지는 후보입니다.",
                .62,
            )
        else:
            features["road_exists"] = unknown(
                "해당 방향의 진출 경로를 확정할 수 없습니다. 선택된 입력툴 링크·사진을 확인해야 합니다."
            )
        features["exit_lane_count"] = unknown(
            "선형 경로 한 개로 실제 해당 방향 진출 차로 수를 계산할 수 없습니다."
        )
        features["guidance_line"] = unknown(
            "일반 유도선은 일반 차로 경계선과 구별되는 근거가 아직 부족합니다."
        )
        features["colored_guidance"] = unknown(
            "색상 경로 선형과 컬러유도선의 의미를 분리해 인식해야 합니다."
        )
    return features, overlay, route
