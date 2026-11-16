"""Compose input_tool expected values without embedding detection rules."""
from __future__ import annotations

import numpy as np

from ...stage_types import fields_for_stage
from . import colored_guidance, guidance_line, lane_arrows, lane_count, road_geometry, stop_line


def extract_input_tool_features(image: np.ndarray, stage: str) -> tuple[dict, np.ndarray, dict]:
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("입력툴 BGR 스크린샷을 읽을 수 없습니다.")

    features: dict[str, dict] = {}
    overlay = image.copy()
    route = {"status": "unknown", "expected_turn": "unknown"}
    if stage != "before":
        presence, overlay, route = road_geometry.extract_road_connection(image, stage)
        features["road_exists"] = presence

    for field in fields_for_stage(stage):
        if field == "stop_line":
            features[field] = stop_line.detect_stop_line(image, overlay, stage)
        elif field in ("entry_lane_count", "exit_lane_count"):
            features[field] = lane_count.detect_lane_count(stage)
        elif field == "lane_arrows":
            features[field] = lane_arrows.detect_lane_arrows()
        elif field == "guidance_line":
            features[field] = guidance_line.detect_guidance_line()
        elif field == "colored_guidance":
            features[field] = colored_guidance.detect_colored_guidance()
        elif field != "road_exists":
            raise ValueError(f"정의되지 않은 input_tool 검수 항목: {field}")
    return features, overlay, route
