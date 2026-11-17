"""Geometry-only grouping of short detected line segments.

Designed for reuse by stop-line, lane-boundary, centre-line and guidance-line
detectors. Grouping means that fragments plausibly belong to one *drawn line*;
it does not classify the line's purpose or approve an inspection result.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, isfinite, pi, sin
from typing import Sequence

# Editable SECOND-pass endpoint rules; fixed first-pass and other markings unchanged.
# Existing max_gap_px YAML key means endpoint XY distance in the second pass.
CENTER_LINE_GROUPING_LIMITS = {
    "angle_tolerance_deg": (0.0, 30.0, 8.0),
    "perpendicular_tolerance_px": (0.0, 30.0, 5.0),
    "max_gap_px": (0.0, 300.0, 20.0),
}


def normalize_center_line_grouping(config: dict | None = None) -> dict[str, float]:
    """Validate saved/UI values before using them for candidate grouping."""
    source = config if isinstance(config, dict) else {}
    normalized = {}
    for key, (lower, upper, default) in CENTER_LINE_GROUPING_LIMITS.items():
        try:
            value = float(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        if not isfinite(value):
            value = default
        normalized[key] = round(max(lower, min(upper, value)), 2)
    return normalized


def _geometry(segment: dict) -> dict:
    first, last = segment["endpoints"]
    x1, y1 = float(first[0]), float(first[1])
    x2, y2 = float(last[0]), float(last[1])
    length = hypot(x2 - x1, y2 - y1)
    if length <= 0:
        raise ValueError("선 그룹화는 길이가 0보다 큰 선분만 처리할 수 있습니다.")
    angle = atan2(y2 - y1, x2 - x1) % pi
    return {
        "id": segment.get("candidate_id"),
        "endpoints": [[x1, y1], [x2, y2]],
        "length": length,
        "angle": angle,
        "midpoint": ((x1 + x2) / 2, (y1 + y2) / 2),
    }


def _angle_difference_deg(a: float, b: float) -> float:
    difference = abs(degrees(a - b)) % 180
    return min(difference, 180 - difference)


def _perpendicular_distance(a: dict, b: dict) -> float:
    """Maximum of both midpoint-to-line perpendicular offsets."""
    offsets = []
    for base, other in ((a, b), (b, a)):
        nx, ny = -sin(base["angle"]), cos(base["angle"])
        ox = other["midpoint"][0] - base["midpoint"][0]
        oy = other["midpoint"][1] - base["midpoint"][1]
        offsets.append(abs(ox * nx + oy * ny))
    return max(offsets)


def _axial_gap(a: dict, b: dict) -> float:
    """Signed projected interval gap: negative values mean overlap."""
    # A shared orientation makes the comparison work for horizontal,
    # vertical, and diagonally sloping lines alike.
    vx, vy = cos(a["angle"]), sin(a["angle"])
    def interval(line: dict) -> tuple[float, float]:
        projected = [p[0] * vx + p[1] * vy for p in line["endpoints"]]
        return min(projected), max(projected)
    amin, amax = interval(a)
    bmin, bmax = interval(b)
    return max(amin - bmax, bmin - amax)


def _aligned(a: dict, b: dict, angle_degrees: float, offset_pixels: float) -> bool:
    return (
        _angle_difference_deg(a["angle"], b["angle"]) <= angle_degrees
        and _perpendicular_distance(a, b) <= offset_pixels
    )


def _group_geometry(members: list[dict]) -> dict:
    """Calculate a representative line using undirected weighted angles."""
    weighted_cos = sum(m["length"] * cos(2 * m["angle"]) for m in members)
    weighted_sin = sum(m["length"] * sin(2 * m["angle"]) for m in members)
    angle = 0.5 * atan2(weighted_sin, weighted_cos) % pi
    vx, vy = cos(angle), sin(angle)
    nx, ny = -vy, vx
    endpoints = [point for member in members for point in member["endpoints"]]
    axial = [x * vx + y * vy for x, y in endpoints]
    transverse = (
        sum(m["length"] * (m["midpoint"][0] * nx + m["midpoint"][1] * ny)
            for m in members)
        / sum(m["length"] for m in members)
    )
    start, end = min(axial), max(axial)
    fitted = [
        [round(start * vx + transverse * nx, 1),
         round(start * vy + transverse * ny, 1)],
        [round(end * vx + transverse * nx, 1),
         round(end * vy + transverse * ny, 1)],
    ]
    angle_deg = degrees(angle)
    axis = ("horizontal" if angle_deg <= 22.5 or angle_deg >= 157.5
            else "vertical" if 67.5 <= angle_deg <= 112.5
            else "diagonal")
    return {
        "endpoints": fitted,
        "angle_deg": round(angle_deg, 2),
        "orientation": axis,
        "length_px": round(end - start, 1),
    }


def group_line_segments(
    segments: Sequence[dict],
    *,
    angle_tolerance_deg: float = 8.0,
    perpendicular_tolerance_px: float = 6.0,
    max_gap_px: float = 12.0,
) -> list[dict]:
    """Group fragments by angle + collinearity + overlap or short axial gap.

    All three rules must hold. A segment must align with *every* existing
    member, preventing chained merges between neighbouring parallel lines;
    it must overlap/touch at least one member to join that group. Unconnected
    parallel lane lines remain separate even with the same slope.

    The thresholds are initial pixel-space heuristics, not ground-truth
    classification. The input segments and their original IDs are unchanged.
    """
    if angle_tolerance_deg < 0 or perpendicular_tolerance_px < 0 or max_gap_px < 0:
        raise ValueError("선 그룹화 임계값은 음수가 될 수 없습니다.")

    geometries = [_geometry(segment) for segment in segments]
    geometries.sort(key=lambda item: item["length"], reverse=True)
    groups: list[list[dict]] = []
    for segment in geometries:
        matches = [
            (index, members) for index, members in enumerate(groups)
            if all(
                _aligned(segment, member, angle_tolerance_deg,
                         perpendicular_tolerance_px)
                for member in members
            )
            and any(_axial_gap(segment, member) <= max_gap_px
                    for member in members)
        ]
        if matches:
            # Prefer the group with the closest aligned member and the
            # largest projected overlap, instead of merging whole groups.
            _, selected = min(
                matches,
                key=lambda item: min(
                    (max(0.0, _axial_gap(segment, member)),
                     _perpendicular_distance(segment, member))
                    for member in item[1]
                ),
            )
            selected.append(segment)
        else:
            groups.append([segment])

    result = []
    for members in groups:
        geometry = _group_geometry(members)
        result.append({
            "member_ids": [member["id"] for member in members],
            "member_count": len(members),
            **geometry,
        })
    result.sort(key=lambda group: group["length_px"], reverse=True)
    for index, group in enumerate(result, 1):
        group["group_id"] = f"G{index}"
    return result
