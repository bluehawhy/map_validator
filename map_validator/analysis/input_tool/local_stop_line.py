"""Collect cyan transverse-line candidates around a detected red reference point.

An uncalibrated marker does not identify a road's travel direction. Local
candidate detection must NOT claim a verified stop line or absence.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from ..line_grouping import group_line_segments
from .blue_palette import blue_color_mask, blue_palette


def detect_stop_line_reference(
    image: np.ndarray, point: list[float] | None,
    canvas_bounds: list[int] | None,
) -> dict:
    """Provisional nearest cyan segment ahead of car (NOT verified stop line)."""
    unavailable = {"status": "not_available", "y": None,
                   "point": None, "endpoints": None,
                   "reason": "현재 위치나 도면 경계가 없습니다."}
    if point is None or canvas_bounds is None or len(canvas_bounds) != 4:
        return unavailable
    h, w = image.shape[:2]
    left, top, right, bottom = map(int, canvas_bounds)
    left, top, right, bottom = max(0,left), max(0,top), min(w,right), min(h,bottom)
    cx, cy = map(float, point)
    if not (left <= cx < right and top <= cy < bottom):
        return {**unavailable, "reason": "현재 위치가 도면 밖입니다."}
    settings = blue_palette()
    guide = settings["guidance_roi"]
    stop = settings["stop_roi"]
    half = max(int(stop["min_half_width_px"]),
               round((right-left)*float(stop["half_width_fraction"])))
    above = max(int(guide["min_above_px"]),
                round((bottom-top)*float(guide["above_position_fraction"])))
    x0, x1 = max(left,round(cx)-half), min(right,round(cx)+half)
    y0 = max(top,round(cy)-above)
    y1 = min(bottom,round(cy)+int(guide["stop_line_margin_px"])+2)
    if x0>=x1 or y0>=y1:
        return {**unavailable, "reason": "시안색 후보 탐색 범위가 없습니다."}
    mask = blue_color_mask(image[y0:y1,x0:x1], "stop_line")
    mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((2,2),np.uint8))
    minimum = max(14,round(min(h,w)*.042))
    lines = cv2.HoughLinesP(mask,1,np.pi/180,
                            threshold=max(9,minimum//2),
                            minLineLength=minimum,maxLineGap=5)
    nearest = None
    if lines is not None:
        car = np.array([cx,cy],dtype=float)
        for xa,ya,xb,yb in lines[:,0]:
            a = np.array([float(xa+x0),float(ya+y0)])
            b = np.array([float(xb+x0),float(yb+y0)])
            v = b-a
            sq = float(v @ v)
            if sq < minimum*minimum:
                continue
            t = max(0.0,min(1.0,float((car-a) @ v/sq)))
            q = a+t*v
            if q[1] > cy+2:
                continue
            distance = float(np.hypot(*(car-q)))
            if nearest is None or distance < nearest["distance_px"]:
                nearest = {
                    "status": "cyan_segment_candidate",
                    "y": int(round(float(q[1]))),
                    "point": [round(float(q[0]),1),round(float(q[1]),1)],
                    "endpoints": [a.astype(int).tolist(),b.astype(int).tolist()],
                    "distance_px": round(distance,1),
                    "reason": "최근접 상단 시안색 선분(실제 정지선 여부 미확정)",
                }
    if nearest is not None:
        return nearest
    return {"status":"vehicle_position_fallback","y":round(cy),
            "point":[round(cx,1),round(cy,1)],"endpoints":None,
            "reason":"시안색 후보가 없어서 차량 Y를 임시 하단으로 사용"}


def local_stop_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, canvas_bounds: list[int] | None = None,
    guide_roi: list[int] | None = None,
    stop_reference: dict | None = None,
) -> dict:
    if point is None or canvas_bounds is None or guide_roi is None:
        return {**unknown("차량 위치·GUIDE ROI 미확인"),"roi":None}
    h,w = image.shape[:2]
    left,top,right,bottom = map(int,canvas_bounds)
    left,top,right,bottom = max(0,left),max(0,top),min(w,right),min(h,bottom)
    cx,cy = map(float,point)
    if not (left <= cx < right and top <= cy < bottom):
        return {**unknown("차량 현재 위치가 도면 밖입니다."),"roi":None}
    rule = blue_palette()["stop_roi"]
    half = max(int(rule["min_half_width_px"]),
               round((right-left)*float(rule["half_width_fraction"])))
    below = max(int(rule["min_below_px"]),
                round((bottom-top)*float(rule["below_position_fraction"])))
    guide_top,guide_bottom = int(guide_roi[1]),int(guide_roi[3])
    fraction = float(rule["guide_height_fraction"])
    if not (0 <= fraction <= 1 and guide_bottom > guide_top):
        return {**unknown("GUIDE ROI/STOP 70% 설정이 유효하지 않습니다."),"roi":None}
    x0,x1 = max(left,round(cx)-half),min(right,round(cx)+half)
    y0 = max(top,round(guide_top+(guide_bottom-guide_top)*fraction))
    y1 = min(bottom,round(cy)+below)
    if x1<=x0 or y1<=y0:
        return {**unknown("STOP ROI가 유효하지 않습니다."),"roi":None}
    roi = image[y0:y1,x0:x1]

    # RGB(0,255,255) is the dedicated stop-line colour; reject the other
    # three blue classes, including pure blue intersection outlines.
    cyan = blue_color_mask(roi, "stop_line")
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
        first, last = line["endpoints"]
        line["point"] = [round((first[0] + last[0]) / 2, 1),
                         round((first[1] + last[1]) / 2, 1)]
    groups = group_line_segments(lines)
    for group in groups:
        first, last = group["endpoints"]
        group["point"] = [round((first[0] + last[0]) / 2, 1),
                          round((first[1] + last[1]) / 2, 1)]
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
        "method": "red_marker_local_cyan_lines_v5_guide_70pct",
        "reason": ("빨간 기준점 주변의 시안색 선 후보입니다. 정지선/도로 경계의 구별은 수동 검증이 필요합니다."
                   if lines else "빨간 기준점 주변에서 시안색 선 후보를 찾지 못했습니다. 정지선 없음으로 확정하지 않습니다."),
        "roi": [x0,y0,x1,y1],
        "palette_source":"color_ranges.json.blue_markings.colors.stop_line",
        "color_rgb":[0,255,255],
        "roi_rules":{
            **dict(rule),
            "positioning":"guide_roi_top_plus_70_percent",
            "guide_roi":guide_roi,
            "guide_fraction":fraction,
            "stop_line_reference":stop_reference,
            "position_point_px":[round(cx,1),round(cy,1)],
            "canvas_bounds":[left,top,right,bottom],
            "red_line_detection":False,
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



def paint_stop_line_roi_border(overlay: np.ndarray, result: dict) -> None:
    """Draw the precise current-position stop-line search rectangle last.

    Rendering after S/G and A candidate annotations preserves the boundary.
    No separate LINE ROI is drawn.
    This is a visual guide only; it never changes which pixels are analyzed.
    """
    bounds = result.get("roi")
    if not bounds or len(bounds) != 4:
        return  # No vehicle ROI: never invent a search boundary

    height, width = overlay.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in bounds)
    x0, y0, x1, y1 = (
        max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    )
    if x1 <= x0 or y1 <= y0:
        return

    # Dark halo keeps the orange border distinguishable from the colored
    # map geometry; do not fill or dim the area being inspected.
    cv2.rectangle(
        overlay, (x0, y0), (x1 - 1, y1 - 1),
        (16, 16, 16), 5, cv2.LINE_AA,
    )
    cv2.rectangle(
        overlay, (x0, y0), (x1 - 1, y1 - 1),
        (0, 165, 255), 2, cv2.LINE_AA,
    )

    label = "STOP ROI"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = .58, 2
    (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
    # Place the label just within the exact search boundary so the evidence
    # crop includes it, even near the right/bottom image edge.
    tx = min(x0 + 8, max(x0 + 2, x1 - tw - 6))
    ty = min(y0 + th + 10, y1 - baseline - 3)
    if ty - th - 4 > y0 and tx + tw + 3 < x1:
        cv2.rectangle(
            overlay,
            (tx - 4, ty - th - 4),
            (tx + tw + 4, ty + baseline + 4),
            (17, 17, 17), -1,
        )
        cv2.putText(
            overlay, label, (tx, ty),
            font, scale, (0, 165, 255), thickness, cv2.LINE_AA,
        )
