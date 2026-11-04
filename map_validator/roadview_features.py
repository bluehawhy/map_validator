"""Stage-specific roadview evidence using existing segmentation and cautious paint cues.

No confidence-free lane count or arrow recognition is invented. A prominent
central building with very little road is a *non-road candidate*, not a proof.
"""
from __future__ import annotations

import cv2
import numpy as np

from .input_features import candidate, unknown
from .stop_line import detect_roadview_stop_line
from .stage_types import fields_for_stage


def _forward_presence(road: np.ndarray, building: np.ndarray) -> dict:
    h, w = road.shape
    # User manually aims the camera along the direction under review.
    # Only the forward-center zone is used to decide road vs building;
    # buildings off to either side do not count as a missing road.
    y0, y1 = int(h * .30), int(h * .68)
    x0, x1 = int(w * .32), int(w * .68)
    a = road[y0:y1, x0:x1]
    b = building[y0:y1, x0:x1]
    if not a.size:
        return unknown("전방 도로 존재 영역이 너무 작습니다.")
    road_ratio = float(np.mean(a))
    building_ratio = float(np.mean(b))
    scores = {"forward_road_ratio": round(road_ratio, 4),
              "forward_building_ratio": round(building_ratio, 4)}
    if road_ratio >= .24:
        result = candidate(
            True, "segformer_forward_road_candidate",
            "촬영 방향 전방 중앙에 도로 영역이 검출됐습니다.", min(.82, .55 + road_ratio * .4)
        )
    elif building_ratio >= .46 and road_ratio < .055:
        result = candidate(
            False, "segformer_building_obstruction_candidate",
            "촬영 방향의 전방 중앙에 건물 영역이 우세하고 도로 영역이 거의 없습니다. "
            "입력툴에 해당 방향 도로가 있으면 불일치 의심입니다. 건물 옆 도로나 카메라 위치를 직접 확인하세요.",
            min(.83, .53 + building_ratio * .36)
        )
    else:
        result = unknown(
            "전방 중앙에서 도로 또는 건물에 의한 비도로를 확실하게 구분하지 못했습니다."
        )
    result["evidence_scores"] = scores
    result["roi"] = [x0, y0, x1, y1]
    return result


def _painted_color_candidate(image: np.ndarray) -> tuple[dict, list]:
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # Loose candidate colors (not confirmed colors/count). Restrict to a
    # forward-center road band, to exclude much of the sky/sidewalk/UI.
    x0, x1 = int(w * .25), int(w * .75)
    y0, y1 = int(h * .46), int(h * .86)
    crop = hsv[y0:y1, x0:x1]
    mask = cv2.inRange(crop, (0, 135, 95), (179, 255, 255))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    strokes = []
    for i in range(1, n):
        x, y, ww, hh, area = (int(value) for value in stats[i])
        longer = max(ww, hh)
        shorter = max(1, min(ww, hh))
        if longer >= w * .12 and longer / shorter >= 4.0 and area >= 24:
            strokes.append((x + x0, y + y0, ww, hh))
    if not strokes:
        return unknown("길게 이어진 컬러 노면선 후보가 명확하지 않습니다."), []
    return candidate(
        True, "high_saturation_elongated_marking_candidate",
        "유색의 긴 노면표시 후보입니다. 실제 컬러유도선인지 차량·광고 색상인지 직접 확인하세요.",
        .42
    ), strokes


def extract_roadview_features(
    image: np.ndarray, stage: str, masks: dict[str, np.ndarray],
    stop_line_threshold: float = .68,
) -> tuple[dict, np.ndarray, dict]:
    """Return field-value evidence, overlay and pixel-ratio metadata."""
    road = masks.get("road")
    building = masks.get("building")
    if image.ndim != 3 or road is None or building is None:
        raise ValueError("로드뷰 분석에 필요한 도로·건물 마스크가 없습니다.")
    if road.shape != image.shape[:2] or building.shape != road.shape:
        raise ValueError("로드뷰 분할 마스크의 크기가 다릅니다.")

    result = {
        key: unknown("해당 노면표시 또는 차로 수의 자동 인식이 아직 검증되지 않았습니다.")
        for key in fields_for_stage(stage)
    }
    overlay = image.copy()
    area = building.astype(bool)
    overlay[area] = (
        overlay[area].astype(np.float32) * .7 + np.array([35, 45, 240]) * .3
    ).astype(np.uint8)
    meta = {"road_ratio": round(float(np.mean(road)), 4),
            "building_ratio": round(float(np.mean(building)), 4)}

    if stage == "before":
        result["stop_line"] = detect_roadview_stop_line(
            image, road, overlay, threshold=stop_line_threshold
        )
        meta["stop_line_threshold"] = stop_line_threshold
        result["entry_lane_count"] = unknown(
            "현재 SegFormer 도로 영역만으로 차로 경계 개수는 계산하지 않습니다."
        )
        result["lane_arrows"] = unknown(
            "좌/직/우 복합 화살표를 읽는 검증된 모델이 아직 없습니다."
        )
    else:
        existence = _forward_presence(road, building)
        result["road_exists"] = existence
        meta["forward_presence"] = existence
        x0, y0, x1, y1 = existence.get(
            "roi", [int(image.shape[1]*.32), int(image.shape[0]*.30),
                    int(image.shape[1]*.68), int(image.shape[0]*.68)]
        )
        color = (40, 200, 40) if existence.get("value") is True else (
            (20, 20, 255) if existence.get("value") is False else (0, 170, 255)
        )
        cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 2)
        result["exit_lane_count"] = unknown(
            "촬영 시점에 따라 양방향 차로가 섞일 수 있어 진출 차로 수를 확정하지 않습니다."
        )
        result["guidance_line"] = unknown(
            "교차로 유도선과 일반 차선 경계선의 인식 기준이 아직 검증되지 않았습니다."
        )

    guidance, strokes = _painted_color_candidate(image)
    result["colored_guidance"] = guidance
    for x, y, w, h in strokes:
        cv2.rectangle(overlay, (x, y), (x+w, y+h), (255, 0, 255), 2)
    return result, overlay, meta
