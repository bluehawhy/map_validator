"""Locate a compact red location marker, not red roads or long red strokes.

Red lines/labels are common in HD_3D Tool screenshots. Never assume the image
centre is the selected point; ambiguous or absent markers remain unknown.
"""
from __future__ import annotations

import cv2
import numpy as np


def find_red_marker(image: np.ndarray) -> dict:
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("기준점 인식에는 BGR 이미지가 필요합니다.")
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, (0, 145, 130), (12, 255, 255))
    high = cv2.inRange(hsv, (170, 145, 130), (179, 255, 255))
    mask = cv2.bitwise_or(low, high)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask, 8)

    candidates = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        # Reject narrow red guide lines, large filled areas, and speckle.
        if area < 5 or area > min(280, max(40, int(width * height * .0005))):
            continue
        if min(w, h) < 3 or max(w, h) > 24:
            continue
        if max(w, h) / min(w, h) > 1.7:
            continue
        if not (0.30 <= area / (w * h) <= 1.0):
            continue
        contours, _ = cv2.findContours(
            (labels[y:y+h, x:x+w] == index).astype(np.uint8),
            cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            continue
        perimeter = cv2.arcLength(max(contours, key=cv2.contourArea), True)
        circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter else 0.0
        if circularity < .25:
            continue
        cx, cy = centres[index]
        candidates.append({
            "x": round(float(cx), 1), "y": round(float(cy), 1),
            "bbox": [x, y, w, h], "area": area,
            "circularity": round(float(circularity), 3),
        })

    if len(candidates) != 1:
        return {
            "status": "not_found" if not candidates else "ambiguous",
            "point": None,
            "candidates": candidates,
            "reason": ("독립된 빨간 점을 확인하지 못했습니다." if not candidates
                       else "빨간 점 후보가 여러 개라 기준점을 정할 수 없습니다."),
            "method": "compact_red_hsv_v1",
        }
    marker = candidates[0]
    return {
        "status": "candidate", "point": [marker["x"], marker["y"]],
        "candidates": candidates,
        "reason": "작고 둥근 빨간 표시 1개를 위치 후보로 찾았습니다. 실제 지점을 확인하세요.",
        "method": "compact_red_hsv_v1",
    }
