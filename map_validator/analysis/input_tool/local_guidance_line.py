"""Guide-line candidate groups based on connected same-colour curved pixels.

Fixed RGB palette comes from color_ranges.json. Unlike straight-line Hough
grouping, 8-connected components tolerate curved/branching guidance paths.
Results are visual review candidates, not verified roadway guidance geometry.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from .color_config import load_color_config


def _unavailable(reason: str) -> dict:
    return {
        **unknown(reason),
        "method": "fixed_rgb_guidance_connected_groups_v1",
        "roi": None, "status": "not_analyzed",
        "groups": [], "group_count": 0, "color_counts": {},
    }


def local_guidance_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, stop_roi: list[int] | None,
) -> dict:
    """Detect independently coloured, spatially connected U# candidates."""
    if point is None or stop_roi is None or len(stop_roi) != 4:
        return _unavailable("차량 현재 위치 또는 HDL View 기준 도면 ROI 미확인")

    height, width = image.shape[:2]
    px, py = (float(point[0]), float(point[1]))
    rule = load_color_config()["guide_lines"]
    region_rule = rule["roi"]
    half_w = max(
        int(region_rule["min_half_width_px"]),
        round(width * float(region_rule["half_width_fraction"])),
    )
    above = max(
        int(region_rule["min_above_px"]),
        round(height * float(region_rule["above_position_fraction"])),
    )
    below = max(
        int(region_rule["min_below_px"]),
        round(height * float(region_rule["below_position_fraction"])),
    )

    sx0, sy0, sx1, sy1 = map(int, stop_roi)
    x0, x1 = max(0, round(px) - half_w), min(width, round(px) + half_w)
    y0 = max(sy0 + int(region_rule["top_inset_from_stop_roi_px"]), round(py) - above)
    y1 = min(sy1, round(py) + below)
    if x1 <= x0 or y1 <= y0:
        result = _unavailable("유도선 전용 검출 범위가 유효하지 않습니다.")
        result["roi_rules"] = region_rule
        return result

    source = image[y0:y1, x0:x1]
    rgb_tolerance = int(rule["channel_tolerance"])
    kernel_size = int(rule["morph_close_kernel_px"])
    if not (0 <= rgb_tolerance <= 60 and 1 <= kernel_size <= 15
            and kernel_size % 2 == 1):
        raise ValueError("유도선 색상 허용 오차/연결 커널 설정이 잘못되었습니다.")
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )

    pending: list[dict] = []
    color_counts: dict[str, int] = {}
    for color_name, spec in rule["colors"].items():
        rgb = np.asarray(spec["rgb"], dtype=np.int16)
        if rgb.shape != (3,):
            raise ValueError("유도선 RGB 색상은 채널 3개를 지정해야 합니다.")
        low = np.clip(rgb - rgb_tolerance, 0, 255).astype(np.uint8)
        high = np.clip(rgb + rgb_tolerance, 0, 255).astype(np.uint8)
        # WGC is OpenCV BGR, while configuration and reference RGB are RGB.
        mask = cv2.inRange(source, low[::-1], high[::-1])
        connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            connected, connectivity=8
        )
        matched = 0
        for index in range(1, count):
            x, y, w, h, region_area = (int(n) for n in stats[index])
            if (region_area < int(rule["min_connected_pixels"])
                    or max(w, h) < int(rule["min_group_span_px"])):
                continue

            # A connected region can branch or curve; use a real visible
            # pixel nearest its centroid for the annotation, rather than
            # an empty bounding-box center.
            piece = np.uint8(labels[y:y+h, x:x+w] == index) * 255
            ys, xs = np.nonzero(piece)
            mean_x, mean_y = xs.mean(), ys.mean()
            nearest = int(np.argmin(
                (xs - mean_x) ** 2 + (ys - mean_y) ** 2
            ))
            anchor = [int(x0 + x + xs[nearest]), int(y0 + y + ys[nearest])]
            original_pixels = int(cv2.countNonZero(
                cv2.bitwise_and(mask[y:y+h, x:x+w], piece)
            ))
            contours, _ = cv2.findContours(
                piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            pending.append({
                "color": color_name,
                "color_rgb": [int(v) for v in spec["rgb"]],
                "label": spec["label"],
                "bbox": [x0 + x, y0 + y, x0 + x + w, y0 + y + h],
                "point": anchor,
                "connected_pixels": region_area,
                "original_color_pixels": original_pixels,
                "fragment_count": len(contours),
                "_contours": contours,
                "_origin": [x0 + x, y0 + y],
            })
            matched += 1
        color_counts[color_name] = matched

    # Assign deterministic IDs by on-image position, regardless of colour.
    pending.sort(key=lambda g: (g["bbox"][1], g["bbox"][0], g["color"]))
    groups = []
    for index, candidate in enumerate(pending, 1):
        group_id = f"U{index}"
        candidate["group_id"] = group_id
        origin_x, origin_y = candidate.pop("_origin")
        for contour in candidate.pop("_contours"):
            shifted = contour + np.array([origin_x, origin_y], dtype=np.int32)
            cv2.drawContours(
                overlay, [shifted], -1, (215, 130, 235), 1, cv2.LINE_AA
            )
        px_label, py_label = candidate["point"]
        cv2.circle(
            overlay, (px_label, py_label), 5, (225, 100, 230),
            -1, cv2.LINE_AA
        )
        tx = max(2, min(width - 40, px_label + 6))
        ty = max(13, min(height - 5, py_label - 7))
        (tw, th), baseline = cv2.getTextSize(
            group_id, cv2.FONT_HERSHEY_SIMPLEX, .55, 2
        )
        cv2.rectangle(overlay, (tx - 3, ty - th - 3),
                      (tx + tw + 3, ty + baseline + 3), (16, 16, 16), -1)
        cv2.putText(
            overlay, group_id, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
            .55, (235, 145, 245), 2, cv2.LINE_AA
        )
        groups.append(candidate)

    return {
        "value": None, "confidence": None, "status": "candidate",
        "method": "fixed_rgb_guidance_connected_groups_v1",
        "reason": (
            "유도선 색상별 연결 영역을 후보로 표시했습니다. 곡선·분기 형태를 "
            "유지하지만 실제 유도선 여부와 진행 방향은 사람이 검수해야 합니다."
            if groups else
            "유도선 전용 ROI에서 고정 색상의 연결 그룹 후보를 찾지 못했습니다. "
            "유도선 없음으로 확정하지 않습니다."
        ),
        "roi": [x0, y0, x1, y1],
        "roi_rules": region_rule,
        "palette_source": "color_ranges.json.guide_lines",
        "palette": {name: spec["rgb"] for name, spec in rule["colors"].items()},
        "color_tolerance_per_channel": rgb_tolerance,
        "connection_kernel_px": kernel_size,
        "grouping": "eight_connected_same_color_after_small_close",
        "groups": groups, "group_count": len(groups),
        "color_counts": color_counts,
        "classification_status": "candidate_needs_review",
    }


def paint_guidance_roi_border(overlay: np.ndarray, result: dict) -> None:
    """Draw the actual vehicle-relative GUIDE ROI after all annotations."""
    bounds = result.get("roi")
    if not bounds or len(bounds) != 4:
        return
    height, width = overlay.shape[:2]
    x0, y0, x1, y1 = map(int, bounds)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1),
                  (20, 20, 20), 5, cv2.LINE_AA)
    cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1),
                  (235, 75, 195), 2, cv2.LINE_AA)
    label = "GUIDE ROI"
    (tw, th), baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, .54, 2
    )
    tx = max(x0 + 3, x1 - tw - 8)
    ty = y0 + th + 10
    if tx + tw + 3 < x1 and ty + baseline + 4 < y1:
        cv2.rectangle(overlay, (tx - 4, ty - th - 4),
                      (tx + tw + 4, ty + baseline + 4), (16, 16, 16), -1)
        cv2.putText(overlay, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    .54, (235, 90, 205), 2, cv2.LINE_AA)
