"""Estimate the visible road's forward corridor from a semantic road mask.

This is a camera-frame curvature *hint*, not a map-to-camera registration.
The drivable mask can include adjacent lanes, lay-bys or parking areas, so
the result is deliberately conservative and never proves lane connectivity.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def trace_road_corridor(mask: np.ndarray) -> dict[str, Any]:
    if mask.ndim != 2:
        raise ValueError("도로 마스크는 2D 배열이어야 합니다.")
    height, width = mask.shape
    if height < 100 or width < 100:
        return {"status": "unknown", "reason": "로드뷰 사진이 너무 작습니다."}

    clean = (mask.astype(np.uint8) > 0).astype(np.uint8)
    clean = cv2.morphologyEx(
        clean, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(clean, 8)
    if count < 2:
        return {"status": "unknown", "reason": "검출된 도로 영역이 없습니다."}

    # Prefer road regions reaching the central near-field; reject cars/sky.
    anchor_y = min(height - 1, int(height * .74))
    anchor_x = width // 2
    candidates = []
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area < width * height * .008:
            continue
        row = labels[anchor_y, :]
        xs = np.flatnonzero(row == component)
        if len(xs) < width * .04:
            continue
        nearest = int(np.min(np.abs(xs - anchor_x)))
        candidates.append((nearest, -area, component))
    if candidates:
        component_id = min(candidates)[2]
    else:
        # Do not infer a trajectory from a disconnected area away from camera.
        return {
            "status": "unknown",
            "reason": "화면 하단 중앙에서 이어지는 도로 영역을 찾지 못했습니다.",
        }

    ys = [int(height * factor) for factor in (.74, .67, .60, .53, .46, .39, .32)]
    points: list[list[int]] = []
    previous = anchor_x
    for row_y in ys:
        if not (0 <= row_y < height):
            continue
        line = (labels[row_y] == component_id).astype(np.uint8)
        transitions = np.diff(
            np.pad(line.astype(np.int16), (1, 1), constant_values=0)
        )
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]
        spans = [
            (int(start), int(end))
            for start, end in zip(starts, ends)
            if end - start >= width * .035
        ]
        if not spans:
            continue
        # Track a continuous visible corridor, not the widest unrelated road.
        start, end = min(
            spans,
            key=lambda span: (
                max(span[0] - previous, previous - span[1], 0),
                abs((span[0] + span[1]) / 2 - previous),
            ),
        )
        if max(start - previous, previous - end, 0) > width * .15:
            continue
        center_x = int(round((start + end) / 2))
        points.append([center_x, row_y])
        previous = center_x

    if len(points) < 4:
        return {
            "status": "unknown",
            "centerline": points,
            "reason": "연속된 도로 영역이 충분하지 않아 굽은 방향을 추정할 수 없습니다.",
        }

    # As y decreases, the tracked forward corridor moves toward the distance.
    # Screen x increases to the right: strong lateral shift is a bend hint.
    displacement = (points[-1][0] - points[0][0]) / float(width)
    if abs(displacement) < .10:
        direction = "undetermined"
    else:
        direction = "right" if displacement > 0 else "left"
    return {
        "status": "candidate",
        "centerline": points,
        "lateral_shift_ratio": round(displacement, 4),
        "curve_direction": direction,
        "method": "largest_nearfield_road_component_row_center_trace_v1",
        "warning": (
            "원근법·도로 폭·주차 차량·카메라 방향에 따라 중심 경로가 달라져 "
            "실제 교차로 선형과 일대일 대응하지 않을 수 있습니다."
        ),
    }


def draw_road_corridor(image: np.ndarray, corridor: dict[str, Any]) -> np.ndarray:
    result = image.copy()
    points = corridor.get("centerline", [])
    if len(points) >= 2:
        polyline = np.array(points, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(result, [polyline], False, (255, 245, 40), 3)
        for point in points:
            cv2.circle(result, tuple(point), 4, (255, 245, 40), -1)
    return result
