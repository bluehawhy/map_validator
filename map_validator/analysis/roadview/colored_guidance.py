"""Painted-color candidates, not confirmed colored guidance line counts."""
import cv2
import numpy as np

from ..findings import candidate, unknown


def detect_colored_guidance(image: np.ndarray) -> tuple[dict, list]:
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    x0, x1 = int(w * .25), int(w * .75)
    y0, y1 = int(h * .46), int(h * .86)
    crop = hsv[y0:y1, x0:x1]
    mask = cv2.inRange(crop, (0, 135, 95), (179, 255, 255))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    strokes = []
    for i in range(1, n):
        x, y, ww, hh, area = (int(value) for value in stats[i])
        longer, shorter = max(ww, hh), max(1, min(ww, hh))
        if longer >= w * .12 and longer / shorter >= 4.0 and area >= 24:
            strokes.append((x + x0, y + y0, ww, hh))
    if not strokes:
        return unknown("길게 이어진 컬러 노면선 후보가 명확하지 않습니다."), []
    return candidate(
        True, "high_saturation_elongated_marking_candidate",
        "유색의 긴 노면표시 후보입니다. 실제 유도선인지 차량·광고 색상인지 확인하세요.", .42,
    ), strokes
