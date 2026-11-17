"""Grouped axis-line candidates shared by yellow centre and white lane markings.

The detector supplies image-space candidates for human review, not definitive
road-line classifications or lane counts.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from ..line_grouping import group_line_segments, normalize_center_line_grouping
from .color_config import hsv_mask


def local_center_line_candidates(
    image: np.ndarray,
    point: list[float] | None,
    overlay: np.ndarray,
    *,
    roi: list[int] | None,
    grouping_rules: dict | None = None,
) -> dict:
    return _detect_axis_line_candidates(
        image, point, overlay, roi=roi, lane=False, grouping_rules=grouping_rules,
    )


def _detect_axis_line_candidates(
    image: np.ndarray,
    point: list[float] | None,
    overlay: np.ndarray,
    *,
    roi: list[int] | None,
    lane: bool,
    grouping_rules: dict | None = None,
) -> dict:
    marking = "흰색 차선" if lane else "노란 중앙선"
    if point is None or roi is None:
        return unknown(f"현재 위치 또는 검색 ROI가 확인되지 않아 {marking} 후보를 분석하지 않았습니다.")

    height, width = image.shape[:2]
    x0, y0, x1, y1 = (int(value) for value in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return unknown(f"{marking} 검색 ROI가 유효하지 않습니다.")

    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    # Same geometry for both classes; only HSV mask and marker style differ.
    # Bright low-saturation white may include text or other road symbols.
    mask = hsv_mask(hsv, "white" if lane else "yellow")
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    minimum = max(14, round(min(width, height) * .042))
    hough = cv2.HoughLinesP(
        mask, 1, np.pi / 180,
        threshold=max(9, minimum // 2),
        minLineLength=minimum,
        maxLineGap=5,
    )

    segments = []
    if hough is not None:
        for xa, ya, xb, yb in hough[:, 0]:
            dx, dy = int(xb) - int(xa), int(yb) - int(ya)
            length = float(np.hypot(dx, dy))
            if length < minimum:
                continue
            angle = float(np.degrees(np.arctan2(dy, dx)) % 180)
            horizontal = min(angle, 180 - angle) <= 18
            vertical = abs(angle - 90) <= 18
            if not (horizontal or vertical):
                continue
            segments.append({
                "endpoints": [[int(xa + x0), int(ya + y0)],
                              [int(xb + x0), int(yb + y0)]],
                "length_px": round(length, 1),
            })

    segments.sort(key=lambda item: item["length_px"], reverse=True)
    total_segments = len(segments)
    segments = segments[:72]
    for idx, segment in enumerate(segments, 1):
        segment["candidate_id"] = f"{'W' if lane else 'Y'}{idx}"

    # 1차: preserve the original fixed-parameter fragment grouping.
    # User-adjustable thresholds do not change the raw-fragment groups.
    first_pass_rules = {
        "angle_tolerance_deg": 8.0,
        "perpendicular_tolerance_px": 2.5 if lane else 5.0,
        "max_gap_px": 12.0,
    }
    first_pass_groups = group_line_segments(segments, **first_pass_rules)
    if lane:
        groups = first_pass_groups  # Keep white line behavior unchanged.
        grouping = first_pass_rules
    else:
        # 2차: regroup first-pass representative segments with UI settings.
        grouping = normalize_center_line_grouping(grouping_rules)
        for idx, group in enumerate(first_pass_groups, 1):
            group["group_id"] = f"CG{idx}"
            a, b = group["endpoints"]
            group["point"] = [round((a[0] + b[0]) / 2, 1),
                              round((a[1] + b[1]) / 2, 1)]
        first_by_id = {group["group_id"]: group for group in first_pass_groups}
        representatives = [
            {"candidate_id": group["group_id"], "endpoints": group["endpoints"]}
            for group in first_pass_groups
        ]
        groups = group_line_segments(representatives, **grouping)
        for group in groups:
            first_ids = list(group["member_ids"])
            source_ids = [
                original_id for first_id in first_ids
                for original_id in first_by_id[first_id]["member_ids"]
            ]
            group["first_pass_group_ids"] = first_ids
            group["first_pass_group_count"] = len(first_ids)
            group["member_ids"] = source_ids
            group["member_count"] = len(source_ids)
    for idx, group in enumerate(groups, 1):
        group["group_id"] = f"{'L' if lane else 'C'}{idx}"
        a, b = group["endpoints"]
        group["point"] = [round((a[0] + b[0]) / 2, 1),
                          round((a[1] + b[1]) / 2, 1)]
    lookup = {name: group["group_id"]
              for group in groups for name in group["member_ids"]}
    for segment in segments:
        segment["group_id"] = lookup[segment["candidate_id"]]
    if not lane:
        first_lookup = {
            name: group["group_id"]
            for group in first_pass_groups for name in group["member_ids"]
        }
        for segment in segments:
            segment["first_pass_group_id"] = first_lookup[segment["candidate_id"]]

    # Paint group-level representative points, not one marker per Hough
    # fragment; show a limited number to keep the stop-line overlay legible.
    shown = groups[:24]
    # BGR colours: yellow centre marker (blue/orange), white-lane marker (violet).
    line_color = (205, 75, 245) if lane else (255, 165, 0)
    point_color = (205, 75, 245) if lane else (255, 190, 0)
    text_color = (240, 210, 255) if lane else (255, 205, 40)
    for group in shown:
        a, b = group["endpoints"]
        pa = tuple(round(value) for value in a)
        pb = tuple(round(value) for value in b)
        px, py = (round(value) for value in group["point"])
        cv2.line(overlay, pa, pb, line_color, 2, cv2.LINE_AA)
        cv2.circle(overlay, (px, py), 8, point_color, -1, cv2.LINE_AA)
        cv2.circle(overlay, (px, py), 3, (255, 255, 255), -1, cv2.LINE_AA)
        label = group["group_id"]
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = .65, 2
        (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
        tx = max(4, min(px + 12, width - tw - 5))
        ty = max(th + 5, min(py - 12, height - baseline - 5))
        cv2.rectangle(overlay, (tx - 4, ty - th - 4),
                      (tx + tw + 4, ty + baseline + 4), (20, 20, 20), -1)
        cv2.putText(overlay, label, (tx, ty), font, scale,
                    text_color, thickness, cv2.LINE_AA)

    return {
        "value": None,
        "confidence": None,
        "method": ("local_white_axis_lines_grouped_points_v1" if lane else
                   "local_yellow_axis_lines_grouped_points_v2_two_pass"),
        "reason": (f"{marking} 수평/수직 선 그룹의 중간점을 표시했습니다. "
                   "실제 차선/중앙선 여부와 개수는 사람 검수가 필요합니다."
                   if groups else
                   f"분석 ROI에서 {marking} 수평/수직 선 후보를 찾지 못했습니다. "
                   "선 없음으로 확정하지 않습니다."),
        "roi": [x0, y0, x1, y1],
        "total_segments": total_segments,
        "shown_segments": len(segments),
        "omitted_segments": total_segments - len(segments),
        "line_candidates": segments,
        "line_groups": shown,
        "group_count": len(groups),
        "shown_points": len(shown),
        "omitted_points": len(groups) - len(shown),
        "grouping_complete": total_segments == len(segments),
        "first_pass_group_count": len(first_pass_groups),
        "first_pass_line_groups": first_pass_groups if not lane else [],
        "second_pass_group_count": len(groups),
        "grouping_rules": {
            "angle_tolerance_deg": grouping["angle_tolerance_deg"],
            "perpendicular_tolerance_px": grouping["perpendicular_tolerance_px"],
            "max_axial_gap_px": grouping["max_gap_px"],
            "axis_tolerance_deg": 18.0,
            "strategy": (
                "fixed_first_pass_then_configured_second_pass"
                if not lane else "single_pass"
            ),
            "first_pass": first_pass_rules if not lane else None,
            "second_pass": grouping if not lane else None,
        },
    }
