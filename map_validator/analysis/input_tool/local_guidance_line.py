"""Connected-colour U# guidance and P# approach-path review candidates.

Both detectors share a configured exact RGB palette but use independent,
vehicle-relative ROIs. Curved and branched line components are retained.
No route direction or real-road semantics are automatically approved.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from .blue_palette import blue_palette, blue_color_mask


def _unknown(reason: str, kind: str) -> dict:
    return {
        **unknown(reason), "method": "exact_rgb_connected_blue_v2",
        "object_type": kind, "roi": None, "roi_rules": {},
        "groups": [], "group_count": 0, "color_counts": {},
        "classification_status": "not_analyzed",
    }


def _vehicle_roi(image: np.ndarray, point: list[float],
                 canvas_bounds: list[int], settings: dict) -> list[int] | None:
    """PATH ROI: from above the current marker, with marker at lower edge."""
    h,w = image.shape[:2]
    left,top,right,bottom = map(int,canvas_bounds)
    left,top,right,bottom = max(0,left),max(0,top),min(w,right),min(h,bottom)
    px,py = map(float,point)
    if not (left <= px < right and top <= py < bottom):
        return None
    half = max(int(settings["min_half_width_px"]),
               round((right-left)*float(settings["half_width_fraction"])))
    above = max(int(settings["min_above_px"]),
                round((bottom-top)*float(settings["above_position_fraction"])))
    below = max(int(settings["min_below_px"]),
                round((bottom-top)*float(settings["below_position_fraction"])))
    x0,x1 = max(left,round(px)-half),min(right,round(px)+half)
    y0,y1 = max(top,round(py)-above),min(bottom,round(py)+below)
    return [x0,y0,x1,y1] if x1>x0 and y1>y0 else None


def _guidance_roi(
    image: np.ndarray, point: list[float], canvas_bounds: list[int],
    settings: dict,
) -> list[int] | None:
    """GUIDE ROI is defined only by the current red position and canvas size."""
    height, width = image.shape[:2]
    canvas_left, canvas_top, canvas_right, canvas_bottom = map(int, canvas_bounds)
    canvas_left = max(0, canvas_left)
    canvas_top = max(0, canvas_top)
    canvas_right = min(width, canvas_right)
    canvas_bottom = min(height, canvas_bottom)
    if canvas_right <= canvas_left or canvas_bottom <= canvas_top:
        return None

    px, py = float(point[0]), float(point[1])
    if not (canvas_left <= px < canvas_right and canvas_top <= py < canvas_bottom):
        return None

    viewport_width = canvas_right - canvas_left
    viewport_height = canvas_bottom - canvas_top
    half = max(
        int(settings["min_half_width_px"]),
        round(viewport_width * float(settings["half_width_fraction"])),
    )
    above = max(
        int(settings["min_above_px"]),
        round(viewport_height * float(settings["above_position_fraction"])),
    )
    below = max(
        int(settings["min_below_px"]),
        round(viewport_height * float(settings["below_position_fraction"])),
    )
    x0 = max(canvas_left, round(px) - half)
    x1 = min(canvas_right, round(px) + half)
    y0 = max(canvas_top, round(py) - above)
    y1 = min(canvas_bottom, round(py) + below)
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def _paint_candidate(
    overlay: np.ndarray, candidate: dict, contours: list[np.ndarray],
    origin: tuple[int, int], stroke: tuple[int, int, int],
) -> None:
    height, width = overlay.shape[:2]
    offset = np.array(origin, dtype=np.int32)
    for contour in contours:
        cv2.drawContours(
            overlay, [contour + offset], -1, stroke, 1, cv2.LINE_AA
        )
    x, y = candidate["point"]
    cv2.circle(overlay, (x, y), 5, stroke, -1, cv2.LINE_AA)
    label = candidate["candidate_id"]
    (tw, th), baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, .55, 2
    )
    tx = max(3, min(width - tw - 5, x + 7))
    ty = max(th + 5, min(height - baseline - 5, y - 8))
    cv2.rectangle(overlay, (tx - 3, ty - th - 4),
                  (tx + tw + 3, ty + baseline + 3), (20, 20, 20), -1)
    cv2.putText(overlay, label, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, .55, stroke, 2, cv2.LINE_AA)


def _connected_groups(
    image: np.ndarray, point: list[float] | None,
    overlay: np.ndarray, *,
    canvas_bounds: list[int] | None = None,
    name: str, identifier: str, border_name: str,
) -> dict:
    if point is None:
        return _unknown("현재 위치가 확인되지 않았습니다.", name)
    settings = blue_palette()
    roi_keys = {"guidance":"guidance_roi","approach_path":"approach_roi"}
    scope = settings[roi_keys[name]]
    if canvas_bounds is None or len(canvas_bounds) != 4:
        return _unknown(f"{border_name} 도면 경계를 찾지 못했습니다.",name)
    roi = (_guidance_roi(image,point,canvas_bounds,scope)
           if name=="guidance" else
           _vehicle_roi(image,point,canvas_bounds,scope))
    if roi is None:
        return _unknown(f"{border_name} 범위가 유효하지 않습니다.",name)

    x0, y0, x1, y1 = roi
    source = image[y0:y1, x0:x1]
    mask = blue_color_mask(source, name)
    pure_blue_excluded = int(cv2.countNonZero(
        blue_color_mask(source, "intersection_outline")
    ))
    k = int(settings["closing_kernel_px"])
    if not (1 <= k <= 15 and k % 2 == 1):
        raise ValueError("파랑 연결 커널은 1~15 사이 홀수여야 합니다.")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        joined, connectivity=int(settings["connectivity"])
    )
    candidates = []
    for index in range(1, count):
        x, y, w, h, size = (int(t) for t in stats[index])
        if (size < int(settings["min_connected_pixels"])
                or max(w, h) < int(settings["min_group_span_px"])):
            continue
        component = np.uint8(labels[y:y+h, x:x+w] == index) * 255
        ys, xs = np.nonzero(component)
        mid_x, mid_y = xs.mean(), ys.mean()
        closest = int(np.argmin(
            (xs - mid_x) ** 2 + (ys - mid_y) ** 2
        ))
        hit = [int(x0 + x + xs[closest]), int(y0 + y + ys[closest])]
        contours, _ = cv2.findContours(
            component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        candidates.append({
            "color": name,
            "label": settings["colors"][name]["label"],
            "color_rgb": list(settings["colors"][name]["rgb"]),
            "point": hit,
            "bbox": [x0+x, y0+y, x0+x+w, y0+y+h],
            "connected_pixels": size,
            "original_color_pixels": int(cv2.countNonZero(
                cv2.bitwise_and(mask[y:y+h, x:x+w], component)
            )),
            "_contours": contours, "_origin": (x0+x, y0+y),
        })
    candidates.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    stroke = (235, 85, 210) if name == "guidance" else (220, 190, 135)
    for i, item in enumerate(candidates, 1):
        item["candidate_id"] = f"{identifier}{i}"
        item["group_id"] = item["candidate_id"]  # old UI/JSON key compatibility
        _paint_candidate(
            overlay, item, item.pop("_contours"),
            item.pop("_origin"), stroke,
        )
    return {
        "value": None, "confidence": None,
        "method": "exact_rgb_connected_blue_v2",
        "object_type": name,
        "status": "candidate",
        "reason": (
            f"{border_name} 내부에서 색상별 연결 후보를 표시했습니다. "
            "실제 도로 구조의 확정은 사람 검수가 필요합니다."
            if candidates else
            f"{border_name} 내부에서 해당 RGB 후보를 찾지 못했습니다. "
            "오브젝트 없음으로 확정하지 않습니다."
        ),
        "roi": roi,
        "roi_rules": {
            **dict(scope),
            "positioning": (
                "vehicle_position_independent_offsets"
            ),
            "position_point_px": [round(float(point[0]), 1), round(float(point[1]), 1)],
            "canvas_bounds": list(map(int, canvas_bounds)),
            "anchor": "red_marker.point",
        },
        "palette_source": "color_ranges.json.blue_markings",
        "color_rgb": list(settings["colors"][name]["rgb"]),
        "palette": {name: list(settings["colors"][name]["rgb"])},
        "color_tolerance_per_channel": int(settings["tolerance_per_channel"]),
        "excluded_outline_blue_pixels": pure_blue_excluded,
        "grouping": "8-connected RGB pixels with 3x3 morphological close",
        "groups": candidates, "group_count": len(candidates),
        "color_counts": {name: len(candidates)},
        "classification_status": "candidate_needs_review",
    }


def local_guidance_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, canvas_bounds: list[int] | None = None,
) -> dict:
    return _connected_groups(
        image,point,overlay,canvas_bounds=canvas_bounds,
        name="guidance",identifier="U",border_name="GUIDE ROI",
    )


def local_approach_path_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, canvas_bounds: list[int] | None = None,
) -> dict:
    return _connected_groups(
        image,point,overlay,canvas_bounds=canvas_bounds,
        name="approach_path",identifier="P",border_name="PATH ROI",
    )


def _paint_roi(
    overlay: np.ndarray, result: dict, label: str,
    stroke: tuple[int, int, int], *, offset: int,
) -> None:
    roi = result.get("roi")
    if not roi or len(roi) != 4:
        return
    h, w = overlay.shape[:2]
    x0, y0, x1, y1 = map(int, roi)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1),
                  (15, 15, 15), 5, cv2.LINE_AA)
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1),
                  stroke, 2, cv2.LINE_AA)
    (tw, th), baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, .54, 2
    )
    tx = min(max(x0 + 4, x1 - tw - 12), w - tw - 4)
    ty = min(y1 - baseline - 5, y0 + th + 9 + offset)
    if tx - 3 >= x0 and ty - th - 4 > y0:
        cv2.rectangle(overlay, (tx - 3, ty - th - 4),
                      (tx + tw + 3, ty + baseline + 3), (18, 18, 18), -1)
        cv2.putText(overlay, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    .54, stroke, 2, cv2.LINE_AA)


def paint_guidance_roi_border(overlay: np.ndarray, result: dict) -> None:
    _paint_roi(overlay, result, "GUIDE ROI", (235, 75, 195), offset=0)


def paint_approach_roi_border(overlay: np.ndarray, result: dict) -> None:
    _paint_roi(overlay, result, "PATH ROI", (230, 205, 95), offset=28)
