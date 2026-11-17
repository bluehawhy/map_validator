"""Second-pass yellow centerline grouping via connected CG endpoints.

Input CG groups come from the unchanged first-pass detector (8deg/5px/12px).
The second pass joins geometrically compatible endpoint pairs transitively,
while keeping complete per-pair PASS/FAIL evidence for human review.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import atan2, cos, degrees, hypot, pi, sin
from typing import Sequence

from .line_grouping import normalize_center_line_grouping


def _angle(group: dict) -> float:
    (x1, y1), (x2, y2) = group["endpoints"]
    return atan2(y2 - y1, x2 - x1) % pi


def _angle_difference(a: float, b: float) -> float:
    diff = abs(degrees(a - b)) % 180.0
    return min(diff, 180.0 - diff)


def _dot(p, axis) -> float:
    return p[0] * axis[0] + p[1] * axis[1]


def _cross(p, axis) -> float:
    return p[0] * axis[1] - p[1] * axis[0]


def _ends(group: dict, axis):
    points = [(tuple(map(float, p)), index)
              for index, p in enumerate(group["endpoints"])]
    return sorted(points, key=lambda item: _dot(item[0], axis))


def _inspect_pair(a: dict, b: dict, rules: dict) -> dict:
    """Record concrete CG endpoint coordinates, geometry, and failure reasons.

    Only end-to-start links are considered, with up to 5px axial overlap.
    Side-by-side parallel lines with large axial overlap are rejected.
    """
    aa, ba = _angle(a), _angle(b)
    difference = _angle_difference(aa, ba)
    direction = (atan2(sin(2 * aa) + sin(2 * ba),
                       cos(2 * aa) + cos(2 * ba)) / 2) % pi
    axis = (cos(direction), sin(direction))
    start_a, end_a = _ends(a, axis)
    start_b, end_b = _ends(b, axis)

    candidates = []
    # (A endpoint, B endpoint, directed end->start vector)
    for ap, bp, start, end in (
        (end_a, start_b, end_a[0], start_b[0]),
        (start_a, end_b, end_b[0], start_a[0]),
    ):
        delta = (end[0] - start[0], end[1] - start[1])
        distance = hypot(*delta)
        lateral = max(
            abs(_cross(delta, (cos(aa), sin(aa)))),
            abs(_cross(delta, (cos(ba), sin(ba)))),
        )
        axial_gap = _dot(delta, axis)
        failed = []
        if difference > rules["angle_tolerance_deg"]:
            failed.append("angle")
        if axial_gap < -5.0:
            failed.append("axial_overlap")
        if distance > rules["max_gap_px"]:
            failed.append("endpoint_distance")
        if lateral > rules["perpendicular_tolerance_px"]:
            failed.append("perpendicular")
        candidates.append({
            "from_endpoint": list(ap[0]),
            "to_endpoint": list(bp[0]),
            "a_endpoint_index": ap[1],
            "b_endpoint_index": bp[1],
            "distance_px": round(distance, 2),
            "perpendicular_px": round(lateral, 2),
            "angle_difference_deg": round(difference, 2),
            "axial_gap_px": round(axial_gap, 2),
            "failed_conditions": failed,
        })

    # Prefer any valid connection, otherwise explain the closest
    # most plausible endpoint pair rather than hiding its measurements.
    best = min(candidates, key=lambda c: (
        bool(c["failed_conditions"]),
        len(c["failed_conditions"]),
        c["distance_px"],
        c["perpendicular_px"],
    ))
    failed = best["failed_conditions"]
    return {
        "from_group": a["group_id"],
        "to_group": b["group_id"],
        "from_group_endpoints": a["endpoints"],
        "to_group_endpoints": b["endpoints"],
        **best,
        "thresholds": {
            "angle_tolerance_deg": rules["angle_tolerance_deg"],
            "perpendicular_tolerance_px": rules["perpendicular_tolerance_px"],
            "endpoint_distance_px": rules["max_gap_px"],
            "minimum_axial_gap_px": -5.0,
        },
        "status": "FAIL" if failed else "ELIGIBLE",
        "reason": failed[0] if failed else "eligible",
    }


def _fit_component(members: list[dict]) -> dict:
    if len(members) == 1:
        original = members[0]
        return {
            "endpoints": original["endpoints"],
            "angle_deg": original["angle_deg"],
            "orientation": original["orientation"],
            "length_px": original["length_px"],
        }
    weighted = []
    for member in members:
        (ax, ay), (bx, by) = member["endpoints"]
        length = hypot(bx - ax, by - ay)
        weighted.append((length, _angle(member)))
    angle = (0.5 * atan2(
        sum(length * sin(2 * theta) for length, theta in weighted),
        sum(length * cos(2 * theta) for length, theta in weighted),
    )) % pi
    axis = (cos(angle), sin(angle))
    normal = (-axis[1], axis[0])
    all_points = [p for g in members for p in g["endpoints"]]
    projected = [_dot(p, axis) for p in all_points]
    weight_sum = sum(length for length, _ in weighted)
    transverse = sum(
        length * _dot((
            (g["endpoints"][0][0] + g["endpoints"][1][0]) / 2,
            (g["endpoints"][0][1] + g["endpoints"][1][1]) / 2,
        ), normal)
        for g, (length, _) in zip(members, weighted)
    ) / weight_sum
    lo, hi = min(projected), max(projected)
    line = [
        [round(t * axis[0] + transverse * normal[0], 1),
         round(t * axis[1] + transverse * normal[1], 1)]
        for t in (lo, hi)
    ]
    deg = degrees(angle)
    orientation = (
        "horizontal" if deg <= 22.5 or deg >= 157.5
        else "vertical" if 67.5 <= deg <= 112.5 else "diagonal"
    )
    return {
        "endpoints": line,
        "angle_deg": round(deg, 2),
        "orientation": orientation,
        "length_px": round(hi - lo, 1),
    }


def merge_centerline_endpoints(
    first_pass_groups: Sequence[dict], grouping_rules: dict | None = None,
) -> tuple[list[dict], dict]:
    """Merge compatible end-to-start CG links without recursion depth risk.

    ALL pair comparisons remain in diagnostics, including rejected links.
    Endpoint reuse is prevented to avoid branching across nearby lanes.
    """
    settings = normalize_center_line_grouping(grouping_rules)
    source = list(first_pass_groups)
    count = len(source)
    parent = list(range(count))
    comparisons = []
    candidate_edges = []
    counts: Counter[str] = Counter()

    for i in range(count):
        for j in range(i + 1, count):
            detail = _inspect_pair(source[i], source[j], settings)
            comparisons.append(detail)
            if detail["status"] == "ELIGIBLE":
                candidate_edges.append((detail["distance_px"],
                                        detail["perpendicular_px"], i, j,
                                        len(comparisons) - 1))
            else:
                counts[detail["reason"]] += 1

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    used_ends = set()
    accepted_connections = []
    for _, _, i, j, pos in sorted(candidate_edges):
        detail = comparisons[pos]
        a_end = (i, detail["a_endpoint_index"])
        b_end = (j, detail["b_endpoint_index"])
        if a_end in used_ends or b_end in used_ends:
            detail["status"] = "FAIL"
            detail["reason"] = "endpoint_in_use"
        elif find(i) == find(j):
            detail["status"] = "FAIL"
            detail["reason"] = "already_connected"
        else:
            parent[find(j)] = find(i)
            used_ends.update((a_end, b_end))
            detail["status"] = "PASS"
            detail["reason"] = "connected"
            accepted_connections.append({
                key: value for key, value in detail.items()
                if key not in ("thresholds", "failed_conditions",
                               "from_group_endpoints", "to_group_endpoints")
            })
        if detail["status"] == "FAIL":
            detail["failed_conditions"] = [detail["reason"]]
            counts[detail["reason"]] += 1

    components: dict[int, list[dict]] = defaultdict(list)
    for idx, item in enumerate(source):
        components[find(idx)].append(item)

    merged = []
    for members in components.values():
        original_ids = [id for member in members for id in member["member_ids"]]
        cg_ids = [member["group_id"] for member in members]
        fitted = _fit_component(members)
        p, q = fitted["endpoints"]
        merged.append({
            **fitted,
            "point": [round((p[0] + q[0]) / 2, 1),
                      round((p[1] + q[1]) / 2, 1)],
            "member_ids": original_ids,
            "member_count": len(original_ids),
            "first_pass_group_ids": cg_ids,
            "first_pass_group_count": len(cg_ids),
        })
    merged.sort(key=lambda g: g["length_px"], reverse=True)
    for idx, item in enumerate(merged, 1):
        item["group_id"] = f"C{idx}"

    cg_to_c = {
        cg: item["group_id"]
        for item in merged for cg in item["first_pass_group_ids"]
    }
    for detail in comparisons:
        a_final = cg_to_c[detail["from_group"]]
        b_final = cg_to_c[detail["to_group"]]
        detail["from_final_group"] = a_final
        detail["to_final_group"] = b_final
    for edge in accepted_connections:
        edge["final_group"] = cg_to_c[edge["from_group"]]

    diagnostics = {
        "strategy": "endpoint_graph_transitive_union_v2_detailed",
        "first_pass_group_count": count,
        "second_pass_group_count": len(merged),
        "candidate_pairs": count * (count - 1) // 2,
        "eligible_pairs": len(candidate_edges),
        "accepted_connection_count": len(accepted_connections),
        "accepted_connections": accepted_connections,
        "rejected_pairs_by_reason": dict(counts),
        "pair_comparisons": comparisons,
        "second_pass_settings": settings,
        "note": "PASS/FAIL은 그룹 연결 적합성일 뿐 중앙선 여부 확정 판정이 아닙니다.",
    }
    return merged, diagnostics
