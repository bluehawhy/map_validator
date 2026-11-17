"""Two-pass white lane candidate detector for saved HD_3D Tool images.

Pass 1 keeps long, nearly continuous solid lines. Pass 2 masks only those
accepted groups and joins short, separated collinear white dashes. Neither
pass confirms a lane, road count or the legal meaning of a marking.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..findings import unknown
from ..line_grouping import group_line_segments
from .local_center_line import _detect_axis_line_candidates


def _visible_runs(
    mask: np.ndarray,
    endpoints: list[list[float]],
    origin: tuple[int, int],
    *,
    minimum_run: int = 1,
) -> tuple[list[tuple[int, int]], list[int], float]:
    """Sample a fitted image-space line; return visible runs and true gaps.

    Small one/two-pixel sampling holes are bridged for antialiased CAD lines.
    The local +/-1 pixel search does not connect adjacent parallel lanes.
    """
    (ax, ay), (bx, by) = endpoints
    size = max(2, int(round(np.hypot(bx - ax, by - ay))) + 1)
    ox, oy = origin
    height, width = mask.shape
    presence = []
    for index in range(size):
        t = index / (size - 1)
        x = round(ax + (bx - ax) * t) - ox
        y = round(ay + (by - ay) * t) - oy
        if 0 <= x < width and 0 <= y < height:
            region = mask[max(0, y - 1):min(height, y + 2),
                          max(0, x - 1):min(width, x + 2)]
            presence.append(bool(cv2.countNonZero(region)))
        else:
            presence.append(False)

    cursor = 0
    while cursor < size:
        if presence[cursor]:
            cursor += 1
            continue
        start = cursor
        while cursor < size and not presence[cursor]:
            cursor += 1
        if start > 0 and cursor < size and cursor - start <= 2:
            presence[start:cursor] = [True] * (cursor - start)

    runs = []
    start = None
    for index, present in enumerate(presence):
        if present and start is None:
            start = index
        if start is not None and (not present or index == size - 1):
            end = index if not present else index + 1
            if end - start >= minimum_run:
                runs.append((start, end))
            start = None
    gaps = [nxt[0] - prior[1] for prior, nxt in zip(runs, runs[1:])]
    coverage = sum(end - start for start, end in runs) / size
    return runs, gaps, round(coverage, 3)


def _paint_group(
    overlay: np.ndarray, group: dict, *,
    dashed: bool, members: dict[str, dict] | None = None,
) -> None:
    line_color = (90, 230, 120) if dashed else (205, 75, 245)
    point_color = (90, 230, 120) if dashed else (205, 75, 245)
    text_color = (130, 255, 160) if dashed else (240, 210, 255)
    first, last = group["endpoints"]
    if dashed:
        # Draw only detected dash pieces, not a misleading continuous line.
        for member_id in group["member_ids"]:
            item = (members or {}).get(member_id)
            if item is None:
                continue
            a, b = item["endpoints"]
            cv2.line(overlay, tuple(int(round(v)) for v in a),
                     tuple(int(round(v)) for v in b),
                     line_color, 2, cv2.LINE_AA)
    else:
        cv2.line(overlay, tuple(int(round(v)) for v in first),
                 tuple(int(round(v)) for v in last),
                 line_color, 2, cv2.LINE_AA)

    px, py = (int(round(v)) for v in group["point"])
    cv2.circle(overlay, (px, py), 7, point_color, -1, cv2.LINE_AA)
    cv2.circle(overlay, (px, py), 3, (255, 255, 255), -1, cv2.LINE_AA)
    label = group["group_id"]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = .65, 2
    (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
    height, width = overlay.shape[:2]
    tx = max(4, min(px + 11, width - tw - 5))
    ty = max(th + 5, min(py - 11, height - baseline - 5))
    cv2.rectangle(overlay, (tx - 4, ty - th - 4),
                  (tx + tw + 4, ty + baseline + 4), (20, 20, 20), -1)
    cv2.putText(overlay, label, (tx, ty), font, scale,
                text_color, thickness, cv2.LINE_AA)


def local_lane_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, roi: list[int] | None,
) -> dict:
    """Return solid L groups with dashed D groups in the dashed_line field."""
    missing = unknown("빨간 기준점 또는 ROI가 확인되지 않아 흰색 차선을 분석하지 않았습니다.")
    if point is None or roi is None:
        return {**missing, "dashed_line": dict(missing)}

    # Reuse the previous long-white-line detector on a scratch overlay so
    # that provisional/short groups do not get painted as solid L markers.
    preliminary = _detect_axis_line_candidates(
        image, point, np.zeros_like(overlay), roi=roi, lane=True,
    )
    region = preliminary.get("roi")
    if not region:
        return {**preliminary, "dashed_line": dict(missing)}
    x0, y0, x1, y1 = (int(v) for v in region)
    height, width = image.shape[:2]
    scale = min(height, width)
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 185), (179, 65, 255))
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

    long_segments = preliminary.get("line_candidates", [])
    long_groups = group_line_segments(
        long_segments,
        angle_tolerance_deg=8.0,
        perpendicular_tolerance_px=2.5,
        max_gap_px=12.0,
    )
    min_solid_span = max(48, round(scale * .075))
    solid_gap_limit = max(7, round(scale * .012))
    solid_groups = []
    for group in long_groups:
        runs, gaps, coverage = _visible_runs(white, group["endpoints"], (x0, y0))
        if (
            group["length_px"] >= min_solid_span
            and coverage >= .74
            and max(gaps, default=0) <= solid_gap_limit
        ):
            group["coverage_ratio"] = coverage
            group["largest_gap_px"] = max(gaps, default=0)
            group["style"] = "solid"
            solid_groups.append(group)

    retained_ids = set()
    for index, group in enumerate(solid_groups, 1):
        group["group_id"] = f"L{index}"
        a, b = group["endpoints"]
        group["point"] = [round((a[0] + b[0]) / 2, 1),
                          round((a[1] + b[1]) / 2, 1)]
        retained_ids.update(group["member_ids"])

    groups_by_fragment = {
        name: group["group_id"]
        for group in solid_groups for name in group["member_ids"]
    }
    kept_long_segments = []
    for segment in long_segments:
        if segment["candidate_id"] in retained_ids:
            segment["group_id"] = groups_by_fragment[segment["candidate_id"]]
            kept_long_segments.append(segment)

    # Mask only accepted solid fitted lines; avoid removing a broad road ROI
    # or the next nearby parallel dashed line.
    remainder = white.copy()
    for group in solid_groups:
        a, b = group["endpoints"]
        cv2.line(
            remainder,
            (round(a[0] - x0), round(a[1] - y0)),
            (round(b[0] - x0), round(b[1] - y0)),
            0, 3, cv2.LINE_8,
        )

    # Find shorter fragments in the remaining white image; the ordinary
    # centre/solid minimum length would drop many valid CAD dash pieces.
    min_dash = max(6, round(scale * .012))
    max_dash_gap = max(24, round(scale * .075))
    min_visible_gap = max(4, round(scale * .008))
    hough = cv2.HoughLinesP(
        remainder, 1, np.pi / 180,
        threshold=max(5, min_dash // 2),
        minLineLength=min_dash,
        maxLineGap=2,
    )
    short_segments = []
    if hough is not None:
        for xa, ya, xb, yb in hough[:, 0]:
            dx, dy = int(xb) - int(xa), int(yb) - int(ya)
            length = float(np.hypot(dx, dy))
            if length < min_dash:
                continue
            angle = float(np.degrees(np.arctan2(dy, dx)) % 180)
            if min(angle, 180 - angle) > 18 and abs(angle - 90) > 18:
                continue
            short_segments.append({
                "endpoints": [[int(xa + x0), int(ya + y0)],
                              [int(xb + x0), int(yb + y0)]],
                "length_px": round(length, 1),
            })
    short_segments.sort(key=lambda part: part["length_px"], reverse=True)
    total_short = len(short_segments)
    short_segments = short_segments[:180]
    for index, segment in enumerate(short_segments, 1):
        segment["candidate_id"] = f"P{index}"

    candidate_groups = group_line_segments(
        short_segments,
        angle_tolerance_deg=8.0,
        perpendicular_tolerance_px=2.5,
        max_gap_px=max_dash_gap,
    )
    dashed_groups = []
    for group in candidate_groups:
        runs, gaps, coverage = _visible_runs(
            remainder, group["endpoints"], (x0, y0),
            minimum_run=max(4, min_dash // 2),
        )
        meaningful = [gap for gap in gaps if gap >= min_visible_gap]
        if (
            len(runs) < 2
            or not meaningful
            or max(meaningful) > max_dash_gap
            or group["length_px"] < max(24, 2 * min_dash + min_visible_gap)
            or coverage > .84
        ):
            continue
        group["dash_count"] = len(runs)
        group["gaps_px"] = meaningful
        group["coverage_ratio"] = coverage
        group["style"] = "dashed"
        dashed_groups.append(group)

    for index, group in enumerate(dashed_groups, 1):
        group["group_id"] = f"D{index}"
        a, b = group["endpoints"]
        group["point"] = [round((a[0] + b[0]) / 2, 1),
                          round((a[1] + b[1]) / 2, 1)]

    group_for_short = {
        member: group["group_id"]
        for group in dashed_groups for member in group["member_ids"]
    }
    accepted_short = []
    for segment in short_segments:
        group_id = group_for_short.get(segment["candidate_id"])
        if group_id:
            segment["group_id"] = group_id
            accepted_short.append(segment)

    shown_solid = solid_groups[:24]
    shown_dashed = dashed_groups[:24]
    short_by_id = {part["candidate_id"]: part for part in short_segments}
    for group in shown_solid:
        _paint_group(overlay, group, dashed=False)
    for group in shown_dashed:
        _paint_group(overlay, group, dashed=True, members=short_by_id)

    dashed = {
        "value": None,
        "confidence": None,
        "method": "remaining_white_short_dashes_grouped_v1",
        "reason": (
            "실선 그룹을 제외한 뒤 같은 선상에서 공백을 두고 반복되는 "
            "흰색 선 조각을 점선 후보로 연결했습니다. 사람 확인이 필요합니다."
            if dashed_groups else
            "실선 영역 제외 후 점선 후보를 확인하지 못했습니다. 점선 없음으로 확정하지 않습니다."
        ),
        "roi": region,
        "line_candidates": accepted_short,
        "line_groups": shown_dashed,
        "total_segments": total_short,
        "shown_segments": len(accepted_short),
        "omitted_segments": total_short - len(short_segments),
        "group_count": len(dashed_groups),
        "shown_points": len(shown_dashed),
        "omitted_points": len(dashed_groups) - len(shown_dashed),
        "grouping_complete": total_short == len(short_segments),
        "grouping_rules": {
            "minimum_dash_px": min_dash,
            "min_visible_gap_px": min_visible_gap,
            "max_axial_gap_px": max_dash_gap,
            "angle_tolerance_deg": 8.0,
            "perpendicular_tolerance_px": 2.5,
            "minimum_disconnected_runs": 2,
            "max_visible_coverage_ratio": .84,
        },
    }
    return {
        "value": None,
        "confidence": None,
        "method": "white_solid_first_then_dashes_v2",
        "reason": (
            "긴 연속 흰 선을 실선 후보로 분류했습니다. "
            "남은 영역의 점선 후보는 별도 D그룹으로 표시합니다."
            if solid_groups else
            "연속 흰색 실선 그룹을 찾지 못했습니다. 없음으로 확정하지 않습니다."
        ),
        "roi": region,
        "line_candidates": kept_long_segments,
        "line_groups": shown_solid,
        "total_segments": preliminary.get("total_segments", 0),
        "shown_segments": len(kept_long_segments),
        "omitted_segments": preliminary.get("omitted_segments", 0),
        "group_count": len(solid_groups),
        "shown_points": len(shown_solid),
        "omitted_points": len(solid_groups) - len(shown_solid),
        "grouping_complete": preliminary.get("grouping_complete", True),
        "solid_groups_removed": len(solid_groups),
        "grouping_rules": {
            "minimum_solid_span_px": min_solid_span,
            "minimum_coverage_ratio": .74,
            "maximum_visible_gap_px": solid_gap_limit,
            "angle_tolerance_deg": 8.0,
            "perpendicular_tolerance_px": 2.5,
            "max_axial_gap_px": 12.0,
            "mask_line_thickness_px": 3,
        },
        "dashed_line": dashed,
    }
