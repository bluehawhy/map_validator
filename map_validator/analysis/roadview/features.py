"""Compose per-feature roadview evidence using one precomputed semantic mask."""
from __future__ import annotations

import cv2
import numpy as np

from ...stage_types import fields_for_stage
from . import colored_guidance, guidance_line, lane_arrows, lane_count, road_presence, stop_line


def extract_roadview_features(
    image: np.ndarray, stage: str, masks: dict[str, np.ndarray],
    stop_line_threshold: float = .68,
) -> tuple[dict, np.ndarray, dict]:
    road, building = masks.get("road"), masks.get("building")
    if image.ndim != 3 or road is None or building is None:
        raise ValueError("로드뷰 분석에 필요한 도로·건물 마스크가 없습니다.")
    if road.shape != image.shape[:2] or building.shape != road.shape:
        raise ValueError("로드뷰 분할 마스크의 크기가 다릅니다.")

    overlay = image.copy()
    area = building.astype(bool)
    overlay[area] = (
        overlay[area].astype(np.float32) * .7 + np.array([35, 45, 240]) * .3
    ).astype(np.uint8)
    meta = {
        "road_ratio": round(float(np.mean(road)), 4),
        "building_ratio": round(float(np.mean(building)), 4),
    }
    features: dict[str, dict] = {}
    presence = None
    if stage != "before":
        presence = road_presence.detect_road_presence(road, building)
        meta["forward_presence"] = presence
        x0, y0, x1, y1 = presence.get(
            "roi", [
                int(image.shape[1] * .32), int(image.shape[0] * .30),
                int(image.shape[1] * .68), int(image.shape[0] * .68),
            ]
        )
        color = (40, 200, 40) if presence.get("value") is True else (
            (20, 20, 255) if presence.get("value") is False else (0, 170, 255)
        )
        cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 2)

    for field in fields_for_stage(stage):
        if field == "road_exists":
            features[field] = presence
        elif field == "stop_line":
            features[field] = stop_line.detect_stop_line(
                image, road, overlay, stage, stop_line_threshold
            )
            if stage == "before":
                meta["stop_line_threshold"] = stop_line_threshold
        elif field in ("entry_lane_count", "exit_lane_count"):
            features[field] = lane_count.detect_lane_count(stage)
        elif field == "lane_arrows":
            features[field] = lane_arrows.detect_lane_arrows()
        elif field == "guidance_line":
            features[field] = guidance_line.detect_guidance_line()
        elif field == "colored_guidance":
            features[field], strokes = colored_guidance.detect_colored_guidance(image)
            for x, y, w, h in strokes:
                cv2.rectangle(overlay, (x, y), (x+w, y+h), (255, 0, 255), 2)
        else:
            raise ValueError(f"정의되지 않은 roadview 검수 항목: {field}")
    return features, overlay, meta
