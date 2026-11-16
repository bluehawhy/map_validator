"""Collect cyan transverse-line candidates around a detected red reference point.

An uncalibrated marker does not identify a road's travel direction. Local
candidate detection must NOT claim a verified stop line or absence.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown


def local_stop_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
) -> dict:
    if point is None:
        return unknown("빨간 기준점이 확정되지 않아 주변 정지선을 분석하지 않았습니다.")

    height, width = image.shape[:2]
    cx, cy = point
    radius_x = max(55, int(width * .18))
    radius_y = max(55, int(height * .19))
    x0, y0 = max(0, round(cx) - radius_x), max(0, round(cy) - radius_y)
    x1, y1 = min(width, round(cx) + radius_x), min(height, round(cy) + radius_y)
    roi = image[y0:y1, x0:x1]
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (255, 180, 0), 1)

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, (78, 105, 120), (102, 255, 255))
    cyan = cv2.morphologyEx(cyan, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    minimum = max(14, round(min(roi.shape[:2]) * .11))
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
    lines = lines[:12]
    for line in lines:
        a, b = line["endpoints"]
        cv2.line(overlay, tuple(a), tuple(b), (0, 220, 255), 2)

    return {
        "value": None,
        "confidence": None,
        "method": "red_marker_local_cyan_lines_v1",
        "reason": ("빨간 기준점 주변의 시안색 선 후보입니다. 정지선/도로 경계의 구별은 수동 검증이 필요합니다."
                   if lines else "빨간 기준점 주변에서 시안색 선 후보를 찾지 못했습니다. 정지선 없음으로 확정하지 않습니다."),
        "roi": [x0, y0, x1, y1],
        "line_candidates": lines,
    }
