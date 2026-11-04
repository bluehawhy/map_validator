"""Conservative extraction of a colored route from an HD_3D Tool screenshot.

A cyan entry line, orange intersection connector and blue exit line encode
the planned map path. Their ordering and signed turn angle can be estimated
in the 2D map image, without touching the running application.

This does not reconstruct 3D world coordinates or prove lane connectivity.
When the colors are missing, fragmented or ambiguous, return 'unknown'.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import atan2, degrees
from typing import Any

import cv2
import numpy as np


@dataclass
class _Line:
    name: str
    a: np.ndarray
    b: np.ndarray
    center: np.ndarray
    span: float
    area: int

    @property
    def ends(self) -> tuple[np.ndarray, np.ndarray]:
        return self.a, self.b


def _canvas(image: np.ndarray) -> tuple[int, int]:
    """Identify the large dark map viewport rather than toolbars or status."""
    h, w = image.shape[:2]
    dark = np.mean(np.max(image, axis=2) < 82, axis=1)
    good = dark >= 0.52
    # The drawing area is the longest sequence of mainly dark rows.
    best = (0, 0)
    start = None
    for i in range(h + 1):
        active = i < h and bool(good[i])
        if active and start is None:
            start = i
        if not active and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best[1] - best[0] < max(60, h // 5):
        return max(0, int(h * .15)), max(1, int(h * .97))
    return best


def _components(mask: np.ndarray, name: str, offset: int, limit: int = 22) -> list[_Line]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    lines: list[_Line] = []
    for index in range(1, count):
        x, y, w, h, area = (int(x) for x in stats[index])
        if area < 9 or max(w, h) < 9:
            continue
        ys, xs = np.where(labels[y:y + h, x:x + w] == index)
        points = np.column_stack((xs + x, ys + y + offset)).astype(np.float64)
        if len(points) < 3:
            continue
        center = np.mean(points, axis=0)
        _, _, vt = np.linalg.svd(points - center, full_matrices=False)
        axis = vt[0]
        projections = (points - center) @ axis
        lo = np.quantile(projections, .04)
        hi = np.quantile(projections, .96)
        a = center + lo * axis
        b = center + hi * axis
        span = float(np.linalg.norm(b - a))
        if span < 7:
            continue
        lines.append(_Line(name, a, b, center, span, area))
    return sorted(lines, key=lambda item: (item.span, item.area), reverse=True)[:limit]


def _int_pt(point: np.ndarray) -> list[int]:
    return [int(round(float(point[0]))), int(round(float(point[1])))]


def extract_line_geometry(image: np.ndarray) -> tuple[dict[str, Any], np.ndarray]:
    """Trace colored entry -> connector -> exit and draw its evidence overlay."""
    h, w = image.shape[:2]
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("입력도구 이미지가 BGR 컬러 화면이 아닙니다.")
    top, bottom = _canvas(image)
    hsv = cv2.cvtColor(image[top:bottom], cv2.COLOR_BGR2HSV)
    # Cyan entry, orange connector, blue exit. Ignore low saturation text/UI.
    specs = {
        "entry_cyan": ((78, 105, 125), (101, 255, 255)),
        "connector_orange": ((5, 125, 130), (25, 255, 255)),
        "exit_blue": ((103, 110, 90), (134, 255, 255)),
    }
    masks: dict[str, np.ndarray] = {}
    candidates: dict[str, list[_Line]] = {}
    for name, (lower, upper) in specs.items():
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        # Remove single-pixel compression noise while retaining thin paths.
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
        )
        masks[name] = mask
        candidates[name] = _components(mask, name, top)
    counts = {key: len(value) for key, value in candidates.items()}
    overlay = image.copy()
    report: dict[str, Any] = {
        "status": "unknown",
        "expected_turn": "unknown",
        "turn_angle_deg": None,
        "canvas_rows": [int(top), int(bottom)],
        "component_counts": counts,
        "method": "hsv_route_entry_connector_exit_v1",
        "warning": (
            "색상 기반 2D 선형 추정이며 HD_3D Tool의 실제 3D 좌표, "
            "차선 연결이나 회전 가능성을 확정하지 않습니다."
        ),
    }
    if any(not components for components in candidates.values()):
        report["reason"] = "하늘색 진입선, 주황색 연결선, 파란색 진출선 중 일부를 찾지 못했습니다."
        cv2.putText(overlay, "ROUTE: UNKNOWN (missing color)", (16, max(top + 32, 40)),
                    cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 255), 2)
        return report, overlay

    diagonal = float(np.hypot(w, bottom - top))
    screen_center = np.array([w / 2., (top + bottom) / 2.])
    options = []
    for entry, connector, exit_line in product(
        candidates["entry_cyan"], candidates["connector_orange"],
        candidates["exit_blue"]
    ):
        if entry.span < max(10., diagonal * .012) or exit_line.span < max(10., diagonal * .012):
            continue
        if connector.span < max(7., diagonal * .008):
            continue
        for connector_start, connector_end in (
            (connector.a, connector.b), (connector.b, connector.a)
        ):
            entry_near, entry_far = min(
                ((entry.a, entry.b), (entry.b, entry.a)),
                key=lambda pair: np.linalg.norm(pair[0] - connector_start),
            )
            exit_near, exit_far = min(
                ((exit_line.a, exit_line.b), (exit_line.b, exit_line.a)),
                key=lambda pair: np.linalg.norm(pair[0] - connector_end),
            )
            gap_in = float(np.linalg.norm(entry_near - connector_start))
            gap_out = float(np.linalg.norm(exit_near - connector_end))
            center_offset = float(np.linalg.norm(connector.center - screen_center))
            # Prefer spatial continuity and intersection near the map center.
            cost = gap_in + gap_out + center_offset * .15
            options.append((cost, gap_in, gap_out, entry, connector, exit_line,
                            entry_far, connector_start, connector_end, exit_far))

    if not options:
        report["reason"] = "연결할 수 있는 길이의 색상 선형이 부족합니다."
        return report, overlay
    options.sort(key=lambda item: item[0])
    (_, gap_in, gap_out, entry, connector, exit_line,
     entry_far, connector_start, connector_end, exit_far) = options[0]

    max_gap = max(18., diagonal * .055)
    report["join_gaps_px"] = {
        "entry_to_connector": round(gap_in, 1),
        "connector_to_exit": round(gap_out, 1),
        "max_accepted": round(max_gap, 1),
    }
    report["path_points"] = {
        "entry": _int_pt(entry_far),
        "connector_start": _int_pt(connector_start),
        "connector_end": _int_pt(connector_end),
        "exit": _int_pt(exit_far),
    }
    # OpenCV screen coordinates have y pointing down. Cross > 0 => right turn.
    inbound = connector_start - entry_far
    outbound = exit_far - connector_end
    in_norm = float(np.linalg.norm(inbound))
    out_norm = float(np.linalg.norm(outbound))
    if in_norm < 8 or out_norm < 8:
        report["reason"] = "진입 또는 진출 선형 방향을 판단할 수 없습니다."
    else:
        cross = float(np.cross(inbound, outbound))
        dot = float(np.dot(inbound, outbound))
        angle = degrees(atan2(cross, dot))
        report["turn_angle_deg"] = round(angle, 1)
        if gap_in > max_gap or gap_out > max_gap:
            report["reason"] = "색상 선형 사이 간격이 커서 하나의 경로로 확인할 수 없습니다."
        else:
            report["status"] = "candidate"
            if abs(angle) < 28:
                report["expected_turn"] = "straight"
            elif 28 <= angle <= 150:
                report["expected_turn"] = "right"
            elif -150 <= angle <= -28:
                report["expected_turn"] = "left"
            else:
                report["status"] = "unknown"
                report["reason"] = "진행 방향이 역방향으로 보입니다. 선택된 경로를 확인하세요."

    palette = ((0, 240, 240), (0, 170, 255), (255, 120, 50))
    for line, color in zip((entry, connector, exit_line), palette):
        cv2.line(overlay, tuple(_int_pt(line.a)), tuple(_int_pt(line.b)), color, 3)
        cv2.circle(overlay, tuple(_int_pt(line.center)), 5, color, -1)
    points = [entry_far, connector_start, connector_end, exit_far]
    for p1, p2 in zip(points, points[1:]):
        cv2.arrowedLine(overlay, tuple(_int_pt(p1)), tuple(_int_pt(p2)),
                        (255, 255, 255), 2, tipLength=.16)
    text = f"ROUTE: {report['expected_turn'].upper()} / {report['status'].upper()}"
    cv2.putText(overlay, text, (16, max(top + 32, 40)),
                cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2)
    return report, overlay


def compare_with_roadview(geometry: dict[str, Any], road_candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare candidate turn topology, never claim 3D geometric equivalence."""
    expected = geometry.get("expected_turn", "unknown")
    if geometry.get("status") != "candidate":
        return {
            "status": "insufficient_evidence",
            "expected_turn": "unknown",
            "reason": geometry.get("reason", "입력툴에서 경로를 확실하게 추출하지 못했습니다."),
        }
    if expected not in {"left", "right", "straight"}:
        return {"status": "insufficient_evidence", "expected_turn": expected,
                "reason": "선형 방향이 불명확합니다."}
    if expected == "straight":
        return {
            "status": "insufficient_evidence",
            "expected_turn": expected,
            "reason": "한 장의 로드뷰 도로 분할만으로 직진 경로의 기하학적 일치를 검증할 수 없습니다.",
        }
    side = f"{expected}_candidate"
    score_key = f"{expected}_score"
    found = bool(road_candidate.get(side, False))
    return {
        "status": "direction_consistent_candidate" if found else "possible_mismatch_review",
        "expected_turn": expected,
        "roadview_side_candidate": found,
        "roadview_side_score": road_candidate.get(score_key),
        "reason": (
            "입력툴의 예상 회전 방향과 같은 쪽에서 로드뷰 도로 영역 후보가 검출됐습니다."
            if found else
            "입력툴의 예상 회전 방향에 대응하는 로드뷰 도로 영역이 확인되지 않았습니다."
        ),
        "warning": "화면 원근·촬영 위치·가림 때문에 실제 도로 선형 일치 여부는 사람이 확인해야 합니다.",
    }
