"""Detect the user's current-position red marker in an input_tool map.

The marker in real HD_3D Tool captures is a small red square at (or near) the
centre of the black map viewport. Red road outlines, text, and guide lines are
NOT markers. Coordinates describe image pixels, not geographic coordinates.
"""
from __future__ import annotations

import cv2
import numpy as np
import logging
from collections import Counter

from ...line_geometry import _canvas

METHOD = "map_center_red_square_v2"
APP_LOG = logging.getLogger("map_validator.analysis.input_tool.red_marker")


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
    APP_LOG.info(
        "[현재위치][1/5] 입력크기=%dx%d 도면Y=%d~%d 도면중심=%s "
        "탐색ROI=[%d,%d,%d,%d] ROI크기=%dx%d 방식=%s",
        width, height, top, bottom, canvas_center,
        x0, y0, x1, y1, roi.shape[1], roi.shape[0], METHOD,
    )

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 145, 130), (12, 255, 255)),
        cv2.inRange(hsv, (170, 145, 130), (179, 255, 255)),
    )
    # Inspect the raw mask as well: a 1–2px current-position square may be
    # erased by opening before the regular shape filters ever see it.
    red_pixels = int(np.count_nonzero(red))
    raw_count, _, raw_stats, raw_centres = cv2.connectedComponentsWithStats(red, 8)
    raw_nearest = []
    for index in range(1, raw_count):
        x, y, w, h, area = (int(v) for v in raw_stats[index])
        cx, cy = float(raw_centres[index][0] + x0), float(raw_centres[index][1] + y0)
        distance = float(np.hypot(cx - canvas_center[0], cy - canvas_center[1]))
        raw_nearest.append((round(distance, 1), [x+x0, y+y0, w, h], area))
    raw_nearest.sort(key=lambda item: item[0])
    APP_LOG.info(
        "[현재위치][2/5] HSV빨강픽셀=%d 원본연결객체=%d 중심근접원본상위8=%s "
        "HSV조건=(H 0~12|170~179, S>=145, V>=130)",
        red_pixels, raw_count - 1, raw_nearest[:8],
    )
    # A thin red roadway line is typically 1–2 px, whereas the user's
    # position indicator is expected to survive a 3x3 opening.
    squares = cv2.morphologyEx(
        red, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )
    opened_pixels = int(np.count_nonzero(squares))
    count, _, stats, centres = cv2.connectedComponentsWithStats(squares, 8)
    APP_LOG.info(
        "[현재위치][3/5] 3x3_OPENING 전픽셀=%d 후픽셀=%d 제거픽셀=%d "
        "후연결객체=%d",
        red_pixels, opened_pixels, red_pixels - opened_pixels, count - 1,
    )

    candidates = []
    rejected = Counter()
    rejected_samples = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not (7 <= area <= 196 and 3 <= min(w, h) and max(w, h) <= 22):
            reason = "크기(면적7~196/짧은변3~/긴변~22)"
        elif max(w, h) / min(w, h) > 1.8:
            reason = "가로세로비(최대1.8)"
        elif area / (w * h) < .46:
            reason = "채움비율(최소0.46)"
        else:
            reason = None
        if reason is not None:
            rejected[reason] += 1
            if len(rejected_samples) < 12:
                rejected_samples.append({
                    "bbox": [x+x0, y+y0, w, h], "area": area,
                    "fill": round(area / (w*h), 2), "reject": reason,
                })
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
    APP_LOG.info(
        "[현재위치][4/5] 형태필터 통과=%d 탈락내역=%s 탈락샘플(최대12)=%s 후보=%s",
        len(candidates), dict(rejected), rejected_samples, candidates[:12],
    )
    diagnostics = {
        "hsv_red_pixels": red_pixels,
        "raw_component_count": raw_count - 1,
        "raw_nearest_components": raw_nearest[:8],
        "opening_pixels": opened_pixels,
        "opened_component_count": count - 1,
        "rejected_by_rule": dict(rejected),
        "rejected_samples": rejected_samples,
        "accepted_count": len(candidates),
    }
    result = {
        "role": "current_position",
        "method": METHOD,
        "canvas_bounds": [0, top, width, bottom],
        "canvas_center": canvas_center,
        "search_roi": [x0, y0, x1, y1],
        "candidates": candidates,
        "point": None,
        "center_offset_px": None,
        "diagnostics": diagnostics,
    }

    if not candidates:
        failure = (
            "빨강픽셀없음" if red_pixels == 0
            else "OPENING에서모두소실" if opened_pixels == 0
            else "형태필터에서모두탈락"
        )
        APP_LOG.warning(
            "[현재위치][5/5] 검출실패 status=not_found 원인=%s "
            "원본중심근접=%s 후객체수=%d 탈락=%s",
            failure, raw_nearest[:5], count - 1, dict(rejected),
        )
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
            APP_LOG.warning(
                "[현재위치][5/5] 검출보류 status=ambiguous "
                "1순위=%s 2순위=%s 중심선택기준=(1순위<=0.28,2순위>=0.60)",
                best, second,
            )
            return {
                **result,
                "status": "ambiguous",
                "reason": "도면 중심 근처에 빨간 사각 표시 후보가 여러 개 있습니다.",
            }

    point = [best["x"], best["y"]]
    APP_LOG.info(
        "[현재위치][5/5] 검출후보 status=candidate 좌표=%s bbox=%s "
        "중심차이픽셀=(%.1f,%.1f) 거리비율=%.3f",
        point, best["bbox"],
        point[0] - canvas_center[0], point[1] - canvas_center[1],
        best["normalized_center_distance"],
    )
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
