"""Mask fixed HD_3D Tool status labels in the upper-left black map canvas.

Only white pixels are masked; nonwhite map geometry and original WGC files
remain untouched. The rectangles are image-coordinate offsets from the
detected dark canvas top-left, not OCR or relative screen percentages.
"""
from __future__ import annotations

import cv2
import numpy as np

from .color_config import hsv_mask, load_color_config


def fixed_ui_text_exclusion(
    image: np.ndarray, canvas_bounds: list[int] | None,
    *, roi: list[int] | None,
) -> tuple[dict, np.ndarray]:
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    config = load_color_config().get("ui_text_exclusion", {})
    regions = []
    enabled = bool(config.get("enabled", False))
    if not enabled or canvas_bounds is None or roi is None:
        return ({
            "method": "fixed_canvas_ui_text_white_mask_v1",
            "status": "not_analyzed",
            "reason": "문자 제외 비활성화 또는 도면/검색 ROI 미확인",
            "enabled": enabled, "regions": [], "excluded_white_pixels": 0,
            "scope": "white_pixels_only",
        }, mask)

    if config.get("anchor") != "canvas_top_left":
        raise ValueError("UI 문자 제외 기준점은 canvas_top_left여야 합니다.")

    canvas_left, canvas_top, canvas_right, canvas_bottom = map(int, canvas_bounds)
    rx0, ry0, rx1, ry1 = map(int, roi)
    rx0, ry0 = max(0, rx0), max(0, ry0)
    rx1, ry1 = min(width, rx1), min(height, ry1)
    if rx1 <= rx0 or ry1 <= ry0:
        return ({
            "method": "fixed_canvas_ui_text_white_mask_v1",
            "status": "not_analyzed", "enabled": enabled, "regions": [],
            "reason": "검색 ROI가 유효하지 않아 문자 제외를 하지 않았습니다.",
            "excluded_white_pixels": 0, "scope": "white_pixels_only",
        }, mask)

    for region in config["regions"]:
        left, top, right, bottom = (int(v) for v in region["rect"])
        if right <= left or bottom <= top or left < 0 or top < 0:
            raise ValueError("UI 문자 제외 영역 좌표가 올바르지 않습니다.")
        # Clip to the map canvas AND actual search ROI, so title bars,
        # normal window chrome and lines elsewhere are not excluded.
        x0 = max(rx0, canvas_left, canvas_left + left, 0)
        y0 = max(ry0, canvas_top, canvas_top + top, 0)
        x1 = min(rx1, canvas_right, canvas_left + right, width)
        y1 = min(ry1, canvas_bottom, canvas_top + bottom, height)
        if x1 <= x0 or y1 <= y0:
            regions.append({
                "id": region["id"], "bbox": None,
                "excluded_white_pixels": 0, "intersects_roi": False,
            })
            continue
        hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        white = hsv_mask(hsv, "white")
        target = mask[y0:y1, x0:x1]
        new_pixels = cv2.bitwise_and(white, cv2.bitwise_not(target))
        pixels = cv2.countNonZero(new_pixels)
        cv2.bitwise_or(target, white, dst=target)
        regions.append({
            "id": region["id"],
            "bbox": [x0, y0, x1, y1],
            "excluded_white_pixels": int(pixels),
            "intersects_roi": True,
        })

    count = int(cv2.countNonZero(mask))
    return ({
        "method": "fixed_canvas_ui_text_white_mask_v1",
        "status": "applied",
        "reason": ("고정 상태 문구 사각형 내부의 흰색 픽셀만 다음 후보에서 제외했습니다. "
                   "겹치는 실제 차선은 함께 빠질 수 있어 수동 검수가 필요합니다."),
        "enabled": True,
        "anchor": config["anchor"],
        "config_source": "color_ranges.json",
        "regions": regions,
        "excluded_white_pixels": count,
        "scope": "white_pixels_only",
    }, mask)


def paint_ui_text_exclusion(overlay: np.ndarray, report: dict) -> None:
    """Mark the excluded rectangles faintly on evidence without hiding W labels."""
    height, width = overlay.shape[:2]
    for region in report.get("regions", []):
        bbox = region.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        patch = overlay[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        tint = np.full_like(patch, (75, 75, 75))
        cv2.addWeighted(patch, .88, tint, .12, 0, dst=patch)
        cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1),
                      (155, 155, 155), 1, cv2.LINE_AA)
