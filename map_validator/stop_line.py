"""Stop-line presence checks for the manually captured BEFORE stage.

The HD_3D Tool expectation is defined by a cyan transverse bar. The roadview
observation is an isolated WHITE stop line across the roadway, NOT a zebra
crossing (including yellow/white crosswalk paint). Uncertain evidence is None,
never an assumed absence. Output is a review aid, not a final traffic verdict.
"""
from __future__ import annotations

import cv2
import numpy as np

from .line_geometry import _canvas


def _finding(value: bool | None, score: float | None, method: str, reason: str,
             **evidence) -> dict:
    return {
        "value": value,
        "confidence": round(float(score), 3) if score is not None else None,
        "method": method,
        "reason": reason,
        "evidence": evidence,
    }


def _horizontal_lines(mask: np.ndarray, image_width: int,
                      min_fraction: float) -> list[tuple[int, int, int, int]]:
    min_length = max(14, int(image_width * min_fraction))
    segments = cv2.HoughLinesP(
        mask, 1, np.pi / 180, threshold=max(9, min_length // 2),
        minLineLength=min_length, maxLineGap=max(4, image_width // 200),
    )
    found = []
    if segments is None:
        return found
    for x1, y1, x2, y2 in segments[:, 0]:
        x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx >= min_length and dy <= max(3, dx * .17):
            found.append((x1, y1, x2, y2))
    return sorted(found, key=lambda v: abs(v[2] - v[0]), reverse=True)


def detect_input_stop_line(image: np.ndarray, overlay: np.ndarray) -> dict:
    """Detect the work-tool cyan transverse bar; reject the vertical cyan path."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("입력툴 스크린샷은 BGR 3채널이어야 합니다.")
    height, width = image.shape[:2]
    top, bottom = _canvas(image)
    if bottom - top < max(90, height // 5):
        return _finding(None, None, "cyan_transverse_v2", "입력툴 도면 영역을 확인할 수 없습니다.")

    hsv = cv2.cvtColor(image[top:bottom], cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, (78, 105, 120), (102, 255, 255))
    cyan = cv2.morphologyEx(cyan, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    lines = _horizontal_lines(cyan, width, .023)
    lines = [
        seg for seg in lines
        if (bottom - top) * .10 <= (seg[1] + seg[3]) / 2 <= (bottom - top) * .92
    ]
    if lines:
        x1, y1, x2, y2 = lines[0]
        p1, p2 = (x1, y1 + top), (x2, y2 + top)
        cv2.line(overlay, p1, p2, (0, 0, 255), 3)
        cv2.putText(overlay, "CYAN STOP LINE", (min(x1, width - 180), max(top + 20, p1[1] - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, .52, (0, 0, 255), 2, cv2.LINE_AA)
        length = abs(x2 - x1)
        return _finding(
            True, min(.94, .65 + (length / max(1, width)) * 1.3),
            "cyan_transverse_v2", "입력툴의 시안색 가로 정지선이 검출됐습니다.",
            endpoints=[list(p1), list(p2)], length_px=length,
        )

    # A black/blank capture is not proof of an absent stop line. Only return
    # false when a recognizable colored road drawing is present in the map.
    saturated = cv2.inRange(hsv, (0, 105, 80), (179, 255, 255))
    colored_pixels = int(np.count_nonzero(saturated))
    map_area = (bottom - top) * width
    if colored_pixels < max(90, int(map_area * .001)):
        return _finding(None, None, "cyan_transverse_v2",
                        "도면이 비어 있거나 선형을 인식하기 어려워 정지선 부재를 판단할 수 없습니다.")
    return _finding(
        False, .64, "cyan_transverse_v2",
        "도면의 도로 선형은 확인되나 시안색 가로 정지선이 검출되지 않았습니다.",
        colored_map_pixels=colored_pixels,
    )


def detect_roadview_stop_line(
    image: np.ndarray, road_mask: np.ndarray, overlay: np.ndarray,
    threshold: float = .68,
) -> dict:
    """Exclude crosswalk patterns and search for a distinct solid white bar.

    threshold is the required confidence for a roadview presence/absence
    decision; a weak line or obscured road produces None for manual review.
    """
    if not 0.35 <= threshold <= 0.95:
        raise ValueError("로드뷰 정지선 threshold는 0.35~0.95 범위여야 합니다.")
    h, w = image.shape[:2]
    if image.ndim != 3 or road_mask.shape != (h, w):
        raise ValueError("로드뷰/도로 마스크 이미지 형식이 잘못됐습니다.")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 173), (179, 85, 255))
    # Yellow stripes can also be crosswalks. Consider both for *exclusion*,
    # but never accept yellow paint as a white stop line.
    yellow = cv2.inRange(hsv, (9, 65, 110), (43, 255, 255))
    paint = cv2.bitwise_or(white, yellow)

    x0, x1 = int(w * .13), int(w * .87)
    y0, y1 = int(h * .40), int(h * .89)
    if y1 <= y0 or x1 <= x0:
        return _finding(None, None, "isolated_white_stopline_v1",
                        "로드뷰가 너무 작아 정지선 영역을 확인할 수 없습니다.")
    # Road semantic mask can omit the painted line itself; a modest dilation
    # allows markings surrounded by actual road without including buildings.
    road_context = cv2.dilate(
        (road_mask > 0).astype(np.uint8), np.ones((13, 13), np.uint8)
    )
    candidate_mask = cv2.bitwise_and(white, white, mask=road_context)
    crop = candidate_mask[y0:y1, x0:x1]
    segments = _horizontal_lines(crop, w, .19)
    road_zone = road_mask[int(h * .55):int(h * .83), int(w * .28):int(w * .72)]
    visible_road = float(np.mean(road_zone > 0)) if road_zone.size else 0.0

    # Find repeated transverse paint marks, the signature of a crosswalk.
    paint_crop = paint[y0:y1, x0:x1]
    lines_of_paint = _horizontal_lines(paint_crop, w, .13)
    candidates = []
    rejected_crosswalk = 0
    for x1c, y1c, x2c, y2c in segments:
        middle_y = (y1c + y2c) / 2
        length = abs(x2c - x1c)
        # Compare groups of *separate* horizontal marks, not duplicate Hough
        # fragments from one thick line (separation >= 7 px).
        neighbor_positions = sorted(
            (q1 + q3) / 2 for q0, q1, q2, q3 in lines_of_paint
            if abs((q1 + q3) / 2 - middle_y) < max(32, h * .105)
            and abs((q1 + q3) / 2 - middle_y) >= 7
        )
        separate_bands = []
        for position in neighbor_positions:
            if not separate_bands or position - separate_bands[-1] >= max(7, h * .012):
                separate_bands.append(position)
        if len(separate_bands) >= 2:
            rejected_crosswalk += 1
            continue
        # A stop line should run across meaningful road context in the
        # central approach, not a white edge elsewhere in the screenshot.
        global_y = int(middle_y + y0)
        left_x, right_x = sorted((x1c + x0, x2c + x0))
        mid_x = (left_x + right_x) // 2
        if mid_x < int(w * .23) or mid_x > int(w * .77):
            continue
        band_top = max(0, global_y - 14)
        band_bot = min(h, global_y + 15)
        context = road_context[band_top:band_bot, left_x:right_x + 1]
        context_score = float(np.mean(context)) if context.size else 0
        if context_score < .52:
            continue
        confidence = min(
            .94, .48 + .75 * min(length / max(w, 1), .48)
            + .13 * context_score
        )
        candidates.append((confidence, (left_x, y1c + y0), (right_x, y2c + y0)))

    if candidates:
        confidence, p1, p2 = max(candidates, key=lambda item: item[0])
        if confidence >= threshold:
            cv2.line(overlay, p1, p2, (0, 255, 255), 3)
            cv2.putText(overlay, "WHITE STOP LINE?", (p1[0], max(20, p1[1]-10)),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, (0, 255, 255), 2, cv2.LINE_AA)
            return _finding(
                True, confidence, "isolated_white_stopline_v1",
                "횡단보도 반복 무늬와 분리된 흰색 가로 정지선 후보가 검출됐습니다.",
                endpoints=[list(p1), list(p2)],
                threshold=threshold, rejected_crosswalk=rejected_crosswalk,
                visible_road_ratio=round(visible_road, 4),
            )
        return _finding(
            None, confidence, "isolated_white_stopline_v1",
            "단독 흰색 가로선 후보는 있지만 threshold에 미달해 추가 확인이 필요합니다.",
            threshold=threshold, rejected_crosswalk=rejected_crosswalk,
            visible_road_ratio=round(visible_road, 4),
        )

    # Clearly visible unobstructed road with no crossing markings is weak
    # negative evidence. With crosswalk candidates or poor visibility, retain
    # 'unknown' rather than confusing a zebra stripe with a stop line.
    absence_confidence = min(.82, .47 + visible_road * .38)
    if rejected_crosswalk == 0 and not lines_of_paint and absence_confidence >= threshold:
        return _finding(
            False, absence_confidence, "isolated_white_stopline_v1",
            "전방 도로는 보이지만 정지선 및 횡단보도 가로 표식이 검출되지 않았습니다.",
            threshold=threshold, visible_road_ratio=round(visible_road, 4),
        )
    return _finding(
        None, None, "isolated_white_stopline_v1",
        "횡단보도 표시 또는 가림/원근 때문에 독립된 정지선의 유무가 불분명합니다. 수동 확인이 필요합니다.",
        threshold=threshold, rejected_crosswalk=rejected_crosswalk,
        visible_road_ratio=round(visible_road, 4),
    )
