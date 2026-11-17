"""Collect cyan transverse-line candidates around a detected red reference point.

An uncalibrated marker does not identify a road's travel direction. Local
candidate detection must NOT claim a verified stop line or absence.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from ..line_grouping import group_line_segments
from .local_ui_text import detect_hdl_view_text_bottom


def local_stop_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, canvas_bounds: list[int] | None = None,
) -> dict:
    if point is None:
        return unknown("빨간 기준점이 확정되지 않아 주변 정지선을 분석하지 않았습니다.")

    height, width = image.shape[:2]
    cx, cy = point
    text_anchor = detect_hdl_view_text_bottom(image, canvas_bounds)
    if text_anchor["status"] != "found":
        return {
            **unknown(
                "HDL View 글자 하단을 확인하지 못해 선형 분석을 보류했습니다: "
                + text_anchor["reason"]
            ),
            "roi": None,
            "roi_rules": {
                "positioning": "hdl_view_text_bottom",
                "anchor_status": "not_found",
                "text_anchor": text_anchor,
            },
        }

    # All four line/object detectors share this ROI. Its top tracks the
    # actual status-text row; no fixed percentage or guessed fallback is used.
    radius_x = max(55, round(width * .31))
    radius_below = max(55, round(height * .44))
    _, canvas_top, _, canvas_bottom = map(int, canvas_bounds)
    x0 = max(0, round(cx) - radius_x)
    x1 = min(width, round(cx) + radius_x)
    y0 = max(canvas_top, int(text_anchor["roi_top_y"]))
    y1 = min(canvas_bottom, round(cy) + radius_below)
    if x1 <= x0 or y1 <= y0:
        return {
            **unknown("HDL View 글자 아래의 유효한 도면 분석 영역이 없습니다."),
            "roi": None,
            "roi_rules": {
                "positioning": "hdl_view_text_bottom",
                "anchor_status": "invalid_roi",
                "text_anchor": text_anchor,
            },
        }
    roi = image[y0:y1, x0:x1]
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (0, 145, 255), 2)

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, (78, 105, 120), (102, 255, 255))
    cyan = cv2.morphologyEx(cyan, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    # Keep the old per-image line sensitivity. Scaling the minimum line
    # length with the wider ROI would silently discard shorter stop lines.
    minimum = max(14, round(min(height, width) * .042))
    hough = cv2.HoughLinesP(
        cyan, 1, np.pi / 180, threshold=max(9, minimum // 2),
        minLineLength=minimum, maxLineGap=5,
    )
    lines = []
    if hough is not None:
        for x_a, y_a, x_b, y_b in hough[:, 0]:
            distance = float(np.hypot(int(x_b) - int(x_a), int(y_b) - int(y_a)))
            if distance < minimum:
                continue
            endpoints = [[int(x_a + x0), int(y_a + y0)],
                         [int(x_b + x0), int(y_b + y0)]]
            lines.append({"endpoints": endpoints, "length_px": round(distance, 1)})
    lines.sort(key=lambda line: line["length_px"], reverse=True)
    total_segments = len(lines)
    lines = lines[:24]
    # The geometry grouping is shared with future lane/centre-line detectors.
    # S# denotes raw Hough fragments; G# denotes geometrically aligned groups.
    for index, line in enumerate(lines, 1):
        line["candidate_id"] = f"S{index}"
    groups = group_line_segments(lines)
    member_groups = {
        member_id: group["group_id"]
        for group in groups for member_id in group["member_ids"]
    }
    for line in lines:
        line["group_id"] = member_groups[line["candidate_id"]]

    # Show the evidence for every detected Hough segment, not just a count.
    # S1..SN match the serialized list and the UI's details panel.
    occupied_labels: list[tuple[int, int, int, int]] = []
    for index, line in enumerate(lines, start=1):
        a, b = line["endpoints"]
        cv2.line(overlay, tuple(a), tuple(b), (0, 255, 255), 3, cv2.LINE_AA)
        for endpoint in (a, b):
            cv2.circle(overlay, tuple(endpoint), 4, (0, 110, 255), -1, cv2.LINE_AA)

        label = line["candidate_id"]
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = .65, 2
        (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
        mid_x = round((a[0] + b[0]) / 2)
        mid_y = round((a[1] + b[1]) / 2)
        for dx, dy in ((8, -10), (-tw - 8, -10), (8, 24), (-tw - 8, 24), (8, -32)):
            tx = max(2, min(mid_x + dx, width - tw - 7))
            ty = max(th + 5, min(mid_y + dy, height - baseline - 5))
            box = (tx - 3, ty - th - 3, tx + tw + 3, ty + baseline + 3)
            if not any(not (
                box[2] < prev[0] or box[0] > prev[2]
                or box[3] < prev[1] or box[1] > prev[3]
            ) for prev in occupied_labels):
                break
        occupied_labels.append(box)
        cv2.rectangle(overlay, (box[0], box[1]), (box[2], box[3]), (20, 20, 20), -1)
        cv2.rectangle(overlay, (box[0], box[1]), (box[2], box[3]), (0, 255, 255), 1)
        cv2.putText(overlay, label, (tx, ty), font, scale, (255, 255, 255),
                    thickness, cv2.LINE_AA)

    # Draw each fitted group line in magenta, with a separate green G# tag.
    # The S# labels remain visible for inspecting merges / false positives.
    for group in groups:
        first, last = group["endpoints"]
        a = tuple(round(value) for value in first)
        b = tuple(round(value) for value in last)
        cv2.line(overlay, a, b, (230, 80, 230), 2, cv2.LINE_AA)
        center_x = round((a[0] + b[0]) / 2)
        center_y = round((a[1] + b[1]) / 2)
        label = group["group_id"]
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = .7, 2
        (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
        # Keep G# labels clear of the S# labels already placed on the image.
        for dx, dy in ((12, -28), (-tw - 12, -28), (12, 40),
                       (-tw - 12, 40), (20, -55), (-tw - 20, 65)):
            x = max(4, min(center_x + dx, width - tw - 6))
            y = max(th + 6, min(center_y + dy, height - baseline - 5))
            box = (x - 4, y - th - 4, x + tw + 4, y + baseline + 4)
            if not any(not (
                box[2] < prev[0] or box[0] > prev[2]
                or box[3] < prev[1] or box[1] > prev[3]
            ) for prev in occupied_labels):
                break
        occupied_labels.append(box)
        cv2.rectangle(overlay, (box[0], box[1]),
                      (box[2], box[3]), (20, 20, 20), -1)
        cv2.rectangle(overlay, (box[0], box[1]),
                      (box[2], box[3]), (30, 255, 120), 1)
        cv2.putText(overlay, label, (x, y), font, scale,
                    (30, 255, 120), thickness, cv2.LINE_AA)

    return {
        "value": None,
        "confidence": None,
        "method": "red_marker_local_cyan_lines_v3_grouped_wide_roi",
        "reason": ("빨간 기준점 주변의 시안색 선 후보입니다. 정지선/도로 경계의 구별은 수동 검증이 필요합니다."
                   if lines else "빨간 기준점 주변에서 시안색 선 후보를 찾지 못했습니다. 정지선 없음으로 확정하지 않습니다."),
        "roi": [x0, y0, x1, y1],
        "roi_rules": {
            "radius_x_fraction": .31,
            "radius_below_fraction": .44,
            "minimum_radius_px": 55,
            "red_line_detection": False,
            "positioning": "hdl_view_text_bottom",
            "anchor_status": "found",
            "text_anchor": text_anchor,
        },
        "total_segments": total_segments,
        "shown_segments": len(lines),
        "omitted_segments": max(0, total_segments - len(lines)),
        "line_candidates": lines,
        "line_groups": groups,
        "group_count": len(groups),
        "grouping_complete": total_segments == len(lines),
        "grouping_rules": {
            "angle_tolerance_deg": 8.0,
            "perpendicular_tolerance_px": 6.0,
            "max_axial_gap_px": 12.0,
            "requires_overlap_or_short_gap": True,
        },
    }
