"""Conservative expected-feature extraction from HD_3D Tool snapshots.

Only visually supported findings are emitted. The cyan path itself does not
prove lane count, guidance line count, or arrow symbols.
"""
from __future__ import annotations

import cv2
import numpy as np

from .line_geometry import extract_line_geometry
from .stop_line import detect_input_stop_line
from .stage_types import fields_for_stage


def unknown(reason: str) -> dict:
    return {"value": None, "confidence": None, "method": "unverified", "reason": reason}


def candidate(value, method: str, reason: str, confidence: float) -> dict:
    return {
        "value": value, "confidence": round(float(confidence), 3),
        "method": method, "reason": reason,
    }


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
        features["stop_line"] = detect_input_stop_line(image, overlay)
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
