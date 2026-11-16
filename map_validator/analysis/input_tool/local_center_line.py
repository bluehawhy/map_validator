"""Yellow input-tool centre-line candidates for visual human review.

Detect horizontal and vertical yellow road markings within the same ROI as
individual stop-line review. An image-space candidate is not a verified
centre line, and a group count is not a surveyed centre-line count.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from ..line_grouping import group_line_segments


def local_center_line_candidates(
    image: np.ndarray,
    point: list[float] | None,
    overlay: np.ndarray,
    *,
    roi: list[int] | None,
) -> dict:
    if point is None or roi is None:
        return unknown("현재 위치 또는 검색 ROI가 확인되지 않아 노란 중앙선 후보를 분석하지 않았습니다.")

    height, width = image.shape[:2]
    x0, y0, x1, y1 = (int(value) for value in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return unknown("중앙선 검색 ROI가 유효하지 않습니다.")

    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    # Initial field-tunable yellow range; text and other yellow UI elements
    # may still become candidates and must be checked in the overlay.
    yellow = cv2.inRange(hsv, (18, 125, 135), (38, 255, 255))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    minimum = max(14, round(min(width, height) * .042))
    hough = cv2.HoughLinesP(
        yellow, 1, np.pi / 180,
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
        segment["candidate_id"] = f"Y{idx}"

    # Tighter lateral grouping than the stop-line default: a second or fourth
    # parallel centre line must remain a separate candidate when resolvable.
    groups = group_line_segments(
        segments,
        angle_tolerance_deg=8.0,
        perpendicular_tolerance_px=2.5,
        max_gap_px=12.0,
    )
    for idx, group in enumerate(groups, 1):
        group["group_id"] = f"C{idx}"
        a, b = group["endpoints"]
        group["point"] = [round((a[0] + b[0]) / 2, 1),
                          round((a[1] + b[1]) / 2, 1)]
    lookup = {name: group["group_id"]
              for group in groups for name in group["member_ids"]}
    for segment in segments:
        segment["group_id"] = lookup[segment["candidate_id"]]

    # Paint group-level representative points, not one marker per Hough
    # fragment; show a limited number to keep the stop-line overlay legible.
    shown = groups[:24]
    for group in shown:
        a, b = group["endpoints"]
        pa = tuple(round(value) for value in a)
        pb = tuple(round(value) for value in b)
        px, py = (round(value) for value in group["point"])
        cv2.line(overlay, pa, pb, (255, 165, 0), 2, cv2.LINE_AA)
        cv2.circle(overlay, (px, py), 8, (255, 190, 0), -1, cv2.LINE_AA)
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
                    (255, 205, 40), thickness, cv2.LINE_AA)

    return {
        "value": None,
        "confidence": None,
        "method": "local_yellow_axis_lines_grouped_points_v1",
        "reason": ("노란색 수평/수직 선 그룹의 중간점을 표시했습니다. "
                   "실제 중앙선 여부와 개수는 사람 검수가 필요합니다."
                   if groups else
                   "분석 ROI에서 노란색 수평/수직 선 후보를 찾지 못했습니다. "
                   "중앙선 없음으로 확정하지 않습니다."),
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
        "grouping_rules": {
            "angle_tolerance_deg": 8.0,
            "perpendicular_tolerance_px": 2.5,
            "max_axial_gap_px": 12.0,
            "axis_tolerance_deg": 18.0,
        },
    }
