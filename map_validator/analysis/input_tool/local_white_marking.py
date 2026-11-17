"""Unclassified white line fragments for visual review of saved input-tool images.

This is the detection stage only. No candidate is named a solid or dashed
lane, and no detected object is removed from another detection mask.
The original WGC PNG and other-colour detectors are unchanged.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from .color_config import hsv_mask


def local_white_marking_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, roi: list[int] | None, exclude_mask: np.ndarray | None = None,
) -> dict:
    if point is None or roi is None:
        return {
            **unknown("현재 위치 또는 ROI가 확인되지 않아 흰색 표시를 검출하지 않았습니다."),
            "line_candidates": [], "total_segments": 0, "shown_segments": 0,
            "omitted_segments": 0, "classification_status": "not_analyzed",
        }

    height, width = image.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return {
            **unknown("흰색 선 검색 ROI가 유효하지 않습니다."),
            "line_candidates": [], "total_segments": 0, "shown_segments": 0,
            "omitted_segments": 0, "classification_status": "not_analyzed",
        }

    # White is a *colour candidate*, not yet a lane marking. Text, symbols,
    # arrows, and other white objects are deliberately retained for review.
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    mask = hsv_mask(hsv, "white")
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    excluded_pixels = 0
    if exclude_mask is not None:
        if exclude_mask.shape != image.shape[:2] or exclude_mask.dtype != np.uint8:
            raise ValueError("제외 마스크는 원본 이미지 크기의 uint8 배열이어야 합니다.")
        local_exclusion = exclude_mask[y0:y1, x0:x1]
        excluded_pixels = cv2.countNonZero(
            cv2.bitwise_and(mask, local_exclusion)
        )
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(local_exclusion))
    min_length = 8
    max_hough_gap = 4
    found = cv2.HoughLinesP(
        mask, 1, np.pi / 180, threshold=5,
        minLineLength=min_length, maxLineGap=max_hough_gap,
    )
    candidates = []
    if found is not None:
        for ax, ay, bx, by in found[:, 0]:
            dx, dy = int(bx) - int(ax), int(by) - int(ay)
            length = float(np.hypot(dx, dy))
            if length < min_length:
                continue
            angle = float(np.degrees(np.arctan2(dy, dx)) % 180)
            axis = (
                "horizontal" if min(angle, 180 - angle) <= 22.5 else
                "vertical" if abs(angle - 90) <= 22.5 else "diagonal"
            )
            candidates.append({
                "endpoints": [[int(ax + x0), int(ay + y0)],
                              [int(bx + x0), int(by + y0)]],
                "length_px": round(length, 1),
                "angle_deg": round(angle, 2),
                "orientation": axis,
                "classification_status": "unclassified",
            })

    # No truncation/grouping: preserve every Hough fragment for a later
    # category-ordered detector to reconsider against the untouched raw image.
    candidates.sort(key=lambda item: item["length_px"], reverse=True)
    for number, segment in enumerate(candidates, 1):
        label = f"W{number}"
        segment["candidate_id"] = label
        a, b = segment["endpoints"]
        px, py = round((a[0] + b[0]) / 2), round((a[1] + b[1]) / 2)
        segment["point"] = [px, py]
        cv2.line(overlay, tuple(a), tuple(b), (205, 75, 245), 1, cv2.LINE_AA)
        cv2.circle(overlay, (px, py), 4, (205, 75, 245), -1, cv2.LINE_AA)
        # Small labels avoid entirely obscuring the raw line evidence.
        tx = max(2, min(px + 6, width - 35))
        ty = max(10, min(py - 5, height - 5))
        cv2.putText(overlay, label, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, .37, (230, 190, 255),
                    1, cv2.LINE_AA)

    return {
        "value": None,
        "confidence": None,
        "method": "white_hsv_raw_hough_candidates_v1",
        "classification_status": "unclassified",
        "stage": "detect_color_only",
        "reason": (
            "흰색 선 조각을 분류하지 않고 모두 표시했습니다. "
            "실선·점선·문자·기타 오브젝트 여부는 후속 검수 대상입니다."
            if candidates else
            "ROI에서 흰색 선 조각을 찾지 못했습니다. 흰색 오브젝트 없음으로 확정하지 않습니다."
        ),
        "roi": [x0, y0, x1, y1],
        "line_candidates": candidates,
        "total_segments": len(candidates),
        "shown_segments": len(candidates),
        "omitted_segments": 0,
        "line_groups": [],
        "group_count": 0,
        "grouping_complete": False,
        "excluded_objects": (["road_arrow_white_pixels"] if exclude_mask is not None else []),
        "excluded_white_pixels": excluded_pixels,
        "palette_source": "color_ranges.json",
        "detection_rules": {
            "hsv_hue_range": [0, 179],
            "hsv_saturation_range": [0, 65],
            "hsv_value_range": [185, 255],
            "min_segment_length_px": min_length,
            "hough_max_gap_px": max_hough_gap,
            "hough_threshold": 5,
            "angle_restriction": None,
            "coverage_filter": None,
            "classification": "deferred",
            "pixel_exclusion": ("road_arrow_white_pixels" if exclude_mask is not None
                                else "none"),
        },
    }
