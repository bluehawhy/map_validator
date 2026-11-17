"""Find review-only road-arrow objects: green rim, gray fill, white interior.

Candidates are identified from the original WGC image. A# is a provisional
object label, not a directional or semantic recognition result. The entire
green-framed polygon and a small margin are excluded from later white-line
detection; original pixels and raw white candidates remain unchanged.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from .color_config import gray_background_mask, hsv_mask, load_color_config


def _blank(reason: str, size: tuple[int, int]) -> tuple[dict, np.ndarray]:
    h, w = size
    return ({
        **unknown(reason), "method": "green_gray_white_arrow_candidate_v1",
        "classification_status": "not_analyzed",
        "candidates": [], "candidate_count": 0, "excluded_white_pixels": 0,
        "excluded_region_pixels": 0, "exclusion_scope": "green_framed_object_region",
    }, np.zeros((h, w), dtype=np.uint8))


def local_road_arrow_candidates(
    image: np.ndarray, point: list[float] | None, *,
    roi: list[int] | None,
) -> tuple[dict, np.ndarray]:
    height, width = image.shape[:2]
    if point is None or roi is None:
        return _blank("현재 위치 또는 검색 ROI가 없어 노면화살표 후보를 찾지 않았습니다.",
                      (height, width))

    x0, y0, x1, y1 = (int(v) for v in roi)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return _blank("노면화살표 탐색 ROI가 유효하지 않습니다.", (height, width))

    config = load_color_config()["road_arrow"]
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    gray = gray_background_mask(hsv)
    green = hsv_mask(hsv, "green")
    white = hsv_mask(hsv, "white")
    gray = cv2.morphologyEx(
        gray, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
    )
    contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    roi_height, roi_width = gray.shape
    candidate_area_limit = roi_height * roi_width * float(config["max_roi_area_fraction"])
    arrow_exclusion_roi = np.zeros_like(gray)
    border_margin = max(0, int(config.get("exclusion_margin_px", 3)))
    exclusion_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * border_margin + 1, 2 * border_margin + 1)
    )
    accepted = []
    for contour in contours:
        contour_area = float(cv2.contourArea(contour))
        if contour_area < float(config["min_gray_contour_area_px"]):
            continue

        rect = cv2.minAreaRect(contour)
        (cx, cy), (side_a, side_b), _ = rect
        shorter, longer = min(side_a, side_b), max(side_a, side_b)
        rect_area = float(side_a * side_b)
        if (shorter < config["min_short_side_px"]
                or longer < config["min_long_side_px"]
                or rect_area <= 0
                or rect_area > candidate_area_limit
                or longer / shorter < config["min_aspect_ratio"]
                or longer / shorter > config["max_aspect_ratio"]):
            continue

        box = np.rint(cv2.boxPoints(rect)).astype(np.int32)
        polygon = np.zeros_like(gray)
        cv2.fillConvexPoly(polygon, box, 255)
        area_pixels = max(1, cv2.countNonZero(polygon))
        gray_pixels = cv2.countNonZero(cv2.bitwise_and(gray, polygon))
        white_pixels = cv2.countNonZero(cv2.bitwise_and(white, polygon))

        # Allow a thin, partially interrupted green perimeter. Check the
        # narrow exterior/interior rim, never the surrounding whole rectangle.
        dilated = cv2.dilate(polygon, np.ones((5, 5), np.uint8))
        eroded = cv2.erode(polygon, np.ones((3, 3), np.uint8))
        rim = cv2.subtract(dilated, eroded)
        green_pixels = cv2.countNonZero(cv2.bitwise_and(green, rim))
        perimeter = 2 * (shorter + longer)
        required_green = max(
            int(config["min_green_edge_pixels"]),
            int(round(perimeter * config["min_green_border_fraction"])),
        )
        if (gray_pixels / area_pixels < config["min_gray_fill_ratio"]
                or white_pixels < config["min_white_pixels"]
                or green_pixels < required_green):
            continue

        # Rotated rectangle orientation along its long side.
        edges = [(box[(index + 1) % 4] - box[index]) for index in range(4)]
        longest_edge = max(edges, key=lambda vector: float(np.hypot(*vector)))
        angle = float(np.degrees(np.arctan2(
            float(longest_edge[1]), float(longest_edge[0])
        )) % 180)
        # The green border is the object boundary. Exclude every pixel
        # enclosed by it plus a small margin, not only the white arrow glyph.
        region_mask = (
            cv2.dilate(polygon, exclusion_kernel)
            if border_margin else polygon
        )
        arrow_exclusion_roi = cv2.bitwise_or(arrow_exclusion_roi, region_mask)
        local_excluded_white = cv2.countNonZero(cv2.bitwise_and(white, region_mask))
        mx, my, mw, mh = cv2.boundingRect(cv2.findNonZero(region_mask))
        global_box = [[int(x + x0), int(y + y0)] for x, y in box]
        xs, ys = [p[0] for p in global_box], [p[1] for p in global_box]
        accepted.append({
            "point": [round(cx + x0, 1), round(cy + y0, 1)],
            "polygon": global_box,
            "bbox": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
            "angle_deg": round(angle, 2),
            "long_side_px": round(longer, 1),
            "short_side_px": round(shorter, 1),
            "gray_fill_ratio": round(gray_pixels / area_pixels, 3),
            "gray_pixels": gray_pixels,
            "white_pixels": white_pixels,
            "masked_white_pixels": int(local_excluded_white),
            "masked_region_pixels": int(cv2.countNonZero(region_mask)),
            "mask_bbox": [mx + x0, my + y0, mx + mw + x0, my + mh + y0],
            "mask_margin_px": border_margin,
            "green_edge_pixels": green_pixels,
            "required_green_edge_pixels": required_green,
            "classification_status": "candidate_needs_review",
        })
    accepted.sort(key=lambda candidate: (candidate["point"][1], candidate["point"][0]))
    for index, candidate in enumerate(accepted, 1):
        candidate["candidate_id"] = f"A{index}"

    full_mask = np.zeros((height, width), dtype=np.uint8)
    full_mask[y0:y1, x0:x1] = arrow_exclusion_roi
    removed_area = int(cv2.countNonZero(arrow_exclusion_roi))
    removed_white = int(cv2.countNonZero(
        cv2.bitwise_and(white, arrow_exclusion_roi)
    ))
    return ({
        "value": None, "confidence": None,
        "method": "green_gray_white_arrow_candidate_v1",
        "reason": (
            "회색 회전 사각형·초록 외곽·내부 흰색 조건을 통과한 "
            "노면화살표 검수 후보입니다. 방향 및 최종 판정은 보류합니다."
            if accepted else
            "세 가지 색상 조건을 만족한 노면화살표 후보를 찾지 못했습니다. "
            "노면화살표 없음으로 확정하지 않습니다."
        ),
        "roi": [x0, y0, x1, y1],
        "classification_status": "candidate_needs_review",
        "candidates": accepted, "candidate_count": len(accepted),
        "excluded_white_pixels": removed_white,
        "excluded_region_pixels": removed_area,
        "exclusion_scope": "green_framed_object_region",
        "mask_margin_px": border_margin,
        "palette_source": "color_ranges.json",
        "rules": {
            "min_gray_contour_area_px": config["min_gray_contour_area_px"],
            "min_short_side_px": config["min_short_side_px"],
            "min_long_side_px": config["min_long_side_px"],
            "min_aspect_ratio": config["min_aspect_ratio"],
            "max_aspect_ratio": config["max_aspect_ratio"],
            "min_gray_fill_ratio": config["min_gray_fill_ratio"],
            "min_white_pixels": config["min_white_pixels"],
            "min_green_edge_pixels": config["min_green_edge_pixels"],
            "min_green_border_fraction": config["min_green_border_fraction"],
            "exclusion_margin_px": border_margin,
        },
    }, full_mask)


def paint_arrow_candidates(overlay: np.ndarray, result: dict) -> None:
    """Annotate A candidates after white fragments, keeping A labels readable."""
    height, width = overlay.shape[:2]
    for candidate in result.get("candidates", []):
        polygon = np.array(candidate["polygon"], dtype=np.int32)
        cv2.polylines(overlay, [polygon], True, (55, 255, 95), 2, cv2.LINE_AA)
        px, py = (int(round(v)) for v in candidate["point"])
        cv2.circle(overlay, (px, py), 6, (45, 255, 80), -1, cv2.LINE_AA)
        label = candidate["candidate_id"]
        (tw, th), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, .7, 2
        )
        tx = max(2, min(px + 9, width - tw - 5))
        ty = max(th + 5, min(py - 9, height - baseline - 5))
        cv2.rectangle(overlay, (tx - 4, ty - th - 4),
                      (tx + tw + 4, ty + baseline + 3), (20, 20, 20), -1)
        cv2.putText(overlay, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (65, 255, 120), 2, cv2.LINE_AA)
