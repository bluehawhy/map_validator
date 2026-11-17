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


def detect_hdl_view_text_bottom(
    image: np.ndarray,
    canvas_bounds: list[int] | None,
) -> dict:
    """Locate the second of the two left-aligned white status-text rows.

    This is deliberately NOT OCR: connected character-sized white components
    must form two separated, left-aligned, horizontally broad text rows near
    the top-left of the black map canvas. No coordinate is invented on failure.
    All coordinates returned refer to the original WGC image.
    """
    options = load_color_config().get("hdl_view_roi", {})
    margin = int(options.get("bottom_margin_px", 10))
    report = {
        "status": "not_found",
        "method": "left_canvas_two_status_rows_cc_v1",
        "anchor": "HDL View / Input second status-text row",
        "bottom_margin_px": margin,
        "text_bottom_y": None,
        "roi_top_y": None,
        "candidate_rows": [],
        "search_rect": None,
    }
    if canvas_bounds is None or len(canvas_bounds) != 4:
        return {**report, "reason": "검은 도면 경계가 없어 상태 글자 위치를 확인하지 못했습니다."}

    height, width = image.shape[:2]
    left, top, right, bottom = (int(v) for v in canvas_bounds)
    left, top, right, bottom = (
        max(0, left), max(0, top), min(width, right), min(height, bottom)
    )
    canvas_height, canvas_width = bottom - top, right - left
    if canvas_height < 140 or canvas_width < 240:
        return {**report, "reason": "상태 글자를 탐색할 도면 영역이 너무 작습니다."}

    # Search only the left-aligned status-text band near the top of the
    # detected canvas. This moves with the WGC canvas when the app resizes.
    x0 = left + max(0, int(options.get("left_inset_px", 8)))
    x1 = min(
        right, x0 + min(int(options.get("search_width_max_px", 570)),
                        round(canvas_width * .62))
    )
    y0 = top + max(0, int(options.get("top_inset_px", 8)))
    search_height = min(
        int(options.get("search_height_max_px", 230)),
        round(canvas_height * float(options.get("search_height_fraction", .40))),
    )
    y1 = min(bottom, y0 + search_height)
    if x1 <= x0 or y1 <= y0:
        return {**report, "reason": "상태 글자 탐색 범위가 유효하지 않습니다."}
    report["search_rect"] = [x0, y0, x1, y1]

    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    white = hsv_mask(hsv, "white")
    count, _, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    components = []
    max_height = int(options.get("max_character_height_px", 44))
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        # Exclude very tall road lines and wide horizontal rules, without
        # suppressing the small letters/dots of the two fixed status labels.
        if not (4 <= area <= 600 and 2 <= h <= max_height
                and 1 <= w <= 42):
            continue
        components.append({
            "x0": x + x0, "x1": x + x0 + w,
            "y0": y + y0, "y1": y + y0 + h,
            "center_y": y + y0 + h / 2,
        })

    # Character parts have close vertical centres. A bounded distance to
    # the group's centre prevents unrelated map glyphs from chaining rows.
    rows = []
    merge_distance = int(options.get("character_row_distance_px", 13))
    for item in sorted(components, key=lambda item: item["center_y"]):
        best = min(rows, key=lambda row: abs(row["center_y"] - item["center_y"]),
                   default=None)
        if best is None or abs(best["center_y"] - item["center_y"]) > merge_distance:
            rows.append({"parts": [item], "center_y": item["center_y"]})
        else:
            best["parts"].append(item)
            best["center_y"] = (
                sum(piece["center_y"] for piece in best["parts"])
                / len(best["parts"])
            )

    eligible = []
    minimum_parts = int(options.get("minimum_character_components", 8))
    minimum_span = int(options.get("minimum_row_span_px", 125))
    max_left_offset = int(options.get("max_row_left_offset_px", 105))
    for row in rows:
        parts = row["parts"]
        leftmost = min(part["x0"] for part in parts)
        rightmost = max(part["x1"] for part in parts)
        upper = min(part["y0"] for part in parts)
        lower = max(part["y1"] for part in parts)
        if (len(parts) < minimum_parts
                or rightmost - leftmost < minimum_span
                or leftmost > left + max_left_offset
                or not 9 <= lower - upper <= max_height + 9):
            continue
        eligible.append({
            "bbox": [leftmost, upper, rightmost, lower],
            "component_count": len(parts),
            "span_px": rightmost - leftmost,
            "center_y": round(row["center_y"], 1),
        })

    eligible.sort(key=lambda row: row["center_y"])
    report["candidate_rows"] = eligible
    if len(eligible) < 2:
        return {
            **report,
            "reason": "도면 왼쪽의 상태 글자 두 행을 구분하지 못했습니다.",
        }

    first, second = eligible[0], eligible[1]
    separation = second["center_y"] - first["center_y"]
    first_x, _, _, _ = first["bbox"]
    second_x, _, _, text_bottom = second["bbox"]
    min_separation = int(options.get("min_row_separation_px", 25))
    max_separation = int(options.get("max_row_separation_px", 135))
    if (not min_separation <= separation <= max_separation
            or abs(first_x - second_x) > 42
            or first["span_px"] < second["span_px"] * .75):
        return {
            **report,
            "reason": "상단 두 글자 행의 간격·시작 위치·너비가 예상 패턴과 다릅니다.",
        }

    roi_top = text_bottom + margin
    if roi_top >= bottom:
        return {**report, "reason": "검출된 글자 아래에 도면 분석 영역이 없습니다."}

    return {
        **report,
        "status": "found",
        "reason": "도면 상단 두 상태 글자 행 중 두 번째 행의 하단을 검출했습니다.",
        "text_bottom_y": int(text_bottom),
        "roi_top_y": int(roi_top),
        "chosen_rows": [first, second],
    }
