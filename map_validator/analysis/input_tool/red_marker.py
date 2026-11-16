"""Detect the user's current-position red marker in an input_tool map.

The marker in real HD_3D Tool captures is a small red square at (or near) the
centre of the black map viewport. Red road outlines, text, and guide lines are
NOT markers. Coordinates describe image pixels, not geographic coordinates.
"""
from __future__ import annotations

import cv2
import numpy as np

from ...line_geometry import _canvas

METHOD = "map_center_red_square_v2"


def find_red_marker(image: np.ndarray) -> dict:
    """Return a conservative current-position candidate or an unknown status.

    Search around the map canvas centre, not the entire window centre: the
    toolbar and status bar shift the overall screenshot's midpoint. A 3x3
    morphological opening removes narrow red polylines while preserving the
    small filled square used for the current-position indicator.
    """
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("현재 위치 인식에는 BGR 3채널 이미지가 필요합니다.")

    height, width = image.shape[:2]
    top, bottom = _canvas(image)
    canvas_center = [round(width / 2, 1), round((top + bottom) / 2, 1)]
    radius_x = max(20, round(width * .065))
    radius_y = max(20, round((bottom - top) * .11))
    x0 = max(0, round(canvas_center[0]) - radius_x)
    y0 = max(top, round(canvas_center[1]) - radius_y)
    x1 = min(width, round(canvas_center[0]) + radius_x + 1)
    y1 = min(bottom, round(canvas_center[1]) + radius_y + 1)
    roi = image[y0:y1, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 145, 130), (12, 255, 255)),
        cv2.inRange(hsv, (170, 145, 130), (179, 255, 255)),
    )
    # A thin red roadway line is typically 1–2 px, whereas the user's
    # position indicator is a filled 4x4 square in the supplied screenshot.
    squares = cv2.morphologyEx(
        red, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )
    count, _, stats, centres = cv2.connectedComponentsWithStats(squares, 8)

    candidates = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not (7 <= area <= 196 and 3 <= min(w, h) and max(w, h) <= 22):
            continue
        if max(w, h) / min(w, h) > 1.8:
            continue
        if area / (w * h) < .46:
            continue
        cx, cy = float(centres[index][0] + x0), float(centres[index][1] + y0)
        centre_distance = float(np.hypot(
            (cx - canvas_center[0]) / radius_x,
            (cy - canvas_center[1]) / radius_y,
        ))
        candidates.append({
            "x": round(cx, 1),
            "y": round(cy, 1),
            "bbox": [x + x0, y + y0, w, h],
            "area": area,
            "shape": "compact_red_square",
            "normalized_center_distance": round(centre_distance, 3),
        })

    candidates.sort(key=lambda item: item["normalized_center_distance"])
    result = {
        "role": "current_position",
        "method": METHOD,
        "canvas_bounds": [0, top, width, bottom],
        "canvas_center": canvas_center,
        "search_roi": [x0, y0, x1, y1],
        "candidates": candidates,
        "point": None,
        "center_offset_px": None,
    }

    if not candidates:
        return {
            **result,
            "status": "not_found",
            "reason": "도면 중앙 부근에서 현재 위치의 빨간 사각 표시를 찾지 못했습니다.",
        }

    # Prefer a uniquely centred mark. If multiple equally plausible squares
    # are close to the centre, do not guess which one indicates the location.
    best = candidates[0]
    if len(candidates) > 1:
        second = candidates[1]
        if not (
            best["normalized_center_distance"] <= .28
            and second["normalized_center_distance"] >= .60
        ):
            return {
                **result,
                "status": "ambiguous",
                "reason": "도면 중심 근처에 빨간 사각 표시 후보가 여러 개 있습니다.",
            }

    point = [best["x"], best["y"]]
    return {
        **result,
        "status": "candidate",
        "point": point,
        "marker_bbox": best["bbox"],
        "center_offset_px": [
            round(point[0] - canvas_center[0], 1),
            round(point[1] - canvas_center[1], 1),
        ],
        "reason": (
            "도면 중앙 근처의 빨간 사각 표시를 현재 위치 후보로 검출했습니다. "
            "지도상 실제 좌표와 진행 방향은 이 이미지로 확정할 수 없습니다."
        ),
    }
