"""Independent input_tool location capture with immutable versions.

No camera/window control; caller supplies a WGC frame. This first review mode
locates the red marker and saves local stop-line candidates for human feedback.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .analysis.input_tool.local_stop_line import local_stop_line_candidates
from .analysis.input_tool.local_center_line import local_center_line_candidates
from .analysis.input_tool.local_lane_line import local_lane_line_candidates
from .analysis.input_tool.red_marker import find_red_marker
from .stage_types import validate_case_id

MANIFEST = "individual_capture.json"
APP_LOG = logging.getLogger("map_validator.individual_capture")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def capture_and_analyze(
    folder: Path, case_id: str, input_tool_image: np.ndarray | None,
    *, unassigned: bool = False, capture_only: bool = False,
    existing_revision: int | None = None,
) -> dict:
    validate_case_id(case_id)
    if existing_revision is None and (input_tool_image is None or input_tool_image.size == 0):
        raise ValueError("input_tool 촬영 이미지가 비었습니다.")
    target_dir = folder / "captures" / "individual"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "schema_version": 1, "case_id": case_id, "history": [],
    }
    if manifest.get("schema_version") != 1 or manifest.get("case_id") != case_id:
        raise ValueError("개별 촬영 기록의 검수 ID 또는 버전이 일치하지 않습니다.")
    if existing_revision is None:
        revision = len(manifest.get("history", [])) + 1
        while (target_dir / f"input_tool_r{revision:03d}.png").exists():
            revision += 1
    else:
        revision = int(existing_revision)
        if revision < 1 or not any(int(entry.get("revision", -1)) == revision
                                   for entry in manifest.get("history", [])):
            raise ValueError("선택한 개별 촬영 버전이 저장 목록에 없습니다.")

    raw_path = target_dir / f"input_tool_r{revision:03d}.png"
    overlay_path = target_dir / f"input_tool_r{revision:03d}_overlay.png"
    focus_path = target_dir / f"input_tool_r{revision:03d}_focus.png"
    if existing_revision is None:
        ok, encoded_frame = cv2.imencode(".png", input_tool_image)
        if not ok:
            raise RuntimeError("촬영 이미지 PNG 인코딩에 실패했습니다.")
        temp_path = raw_path.with_suffix(".png.tmp")
        try:
            with temp_path.open("xb") as stream:
                stream.write(encoded_frame.tobytes())
            os.replace(temp_path, raw_path)
        finally:
            temp_path.unlink(missing_ok=True)
        captured_at = datetime.now(timezone.utc).isoformat()
        manifest.setdefault("history", []).append({
            "revision": revision,
            "captured_at_utc": captured_at,
            "input_tool_image": raw_path.relative_to(folder).as_posix(),
        })
        _write_json(manifest_path, manifest)
        if capture_only:
            return {
                "kind": "individual_capture", "folder": str(folder),
                "case_id": case_id, "revision": revision,
                "unassigned": unassigned,
                "input_tool_image": raw_path.relative_to(folder).as_posix(),
                "captured_at_utc": captured_at,
            }
    else:
        if not raw_path.is_file() or raw_path.is_symlink():
            raise FileNotFoundError("선택한 원본 촬영 PNG가 존재하지 않습니다.")
        encoded = np.fromfile(str(raw_path), dtype=np.uint8)
        input_tool_image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if input_tool_image is None:
            raise ValueError("선택한 촬영 PNG를 읽을 수 없습니다.")
        captured_at = next(
            entry.get("captured_at_utc")
            for entry in manifest["history"]
            if int(entry.get("revision", -1)) == revision
        )

    APP_LOG.info(
        "[개별촬영][위치진단] 촬영버전=%d input_tool이미지=%dx%d "
        "검출시작 (실제지도좌표/진행방향은 추정하지 않음)",
        revision, input_tool_image.shape[1], input_tool_image.shape[0],
    )
    marker = find_red_marker(input_tool_image)
    APP_LOG.info(
        "[개별촬영][위치진단] 결과=%s 후보좌표=%s 후보개수=%d "
        "원본빨강픽셀=%d OPENING후픽셀=%d 사유=%s",
        marker["status"], marker.get("point"), len(marker.get("candidates", [])),
        marker.get("diagnostics", {}).get("hsv_red_pixels", -1),
        marker.get("diagnostics", {}).get("opening_pixels", -1),
        marker.get("reason", ""),
    )
    overlay = input_tool_image.copy()
    point = marker.get("point")
    # Mark the viewport centre separately from the detected current position:
    # the first is a search hint, the second is measured pixel evidence.
    canvas_center = marker["canvas_center"]
    cv2.drawMarker(
        overlay, (round(canvas_center[0]), round(canvas_center[1])),
        (255, 180, 0), cv2.MARKER_CROSS, 12, 1,
    )
    if point is not None:
        px, py = round(point[0]), round(point[1])
        cv2.circle(overlay, (px, py), 13, (0, 255, 255), 2)
        cv2.putText(
            overlay, "CURRENT POSITION?", (min(px + 18, input_tool_image.shape[1] - 180), max(py - 14, 20)),
            cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1, cv2.LINE_AA,
        )
    stop_line = local_stop_line_candidates(input_tool_image, point, overlay)
    APP_LOG.info(
        "[개별촬영][위치진단] 주변정지선분석=%s 분석ROI=%s "
        "시안색선조각=%d 선그룹후보=%d 총검출=%s 그룹화완료=%s",
        "진행" if point is not None else "건너뜀(위치미확인)",
        stop_line.get("roi"), len(stop_line.get("line_candidates", [])),
        len(stop_line.get("line_groups", [])),
        stop_line.get("total_segments", 0),
        stop_line.get("grouping_complete", False),
    )
    for group in stop_line.get("line_groups", []):
        APP_LOG.info(
            "[개별촬영][선그룹] %s 구성=%s 방향=%s 길이=%spx 좌표=%s",
            group["group_id"], ",".join(group["member_ids"]),
            group["angle_deg"], group["length_px"], group["endpoints"],
        )
    center_line = local_center_line_candidates(
        input_tool_image, point, overlay, roi=stop_line.get("roi"),
    )
    APP_LOG.info(
        "[개별촬영][중앙선] 노란조각=%s 포인트후보=%s 누락포인트=%s ROI=%s",
        center_line.get("total_segments", 0),
        center_line.get("shown_points", 0),
        center_line.get("omitted_points", 0), center_line.get("roi"),
    )
    for group in center_line.get("line_groups", []):
        APP_LOG.info(
            "[개별촬영][중앙선] %s 좌표=%s 방향=%s 구성=%s",
            group["group_id"], group["point"], group["orientation"],
            ",".join(group["member_ids"]),
        )
    lane_line = local_lane_line_candidates(
        input_tool_image, point, overlay, roi=stop_line.get("roi"),
    )
    dashed_lane_line = lane_line.pop("dashed_line", {})
    APP_LOG.info(
        "[개별촬영][차선] 흰색조각=%s L포인트=%s 생략=%s ROI=%s",
        lane_line.get("total_segments", 0),
        lane_line.get("shown_points", 0),
        lane_line.get("omitted_points", 0), lane_line.get("roi"),
    )
    for group in lane_line.get("line_groups", []):
        APP_LOG.info(
            "[개별촬영][차선] %s 좌표=%s 방향=%s 구성=%s",
            group["group_id"], group["point"], group["orientation"],
            ",".join(group["member_ids"]),
        )
    APP_LOG.info(
        "[개별촬영][점선] 남은 흰색조각=%s D포인트=%s 생략=%s",
        dashed_lane_line.get("total_segments", 0),
        dashed_lane_line.get("shown_points", 0),
        dashed_lane_line.get("omitted_points", 0),
    )
    for group in dashed_lane_line.get("line_groups", []):
        APP_LOG.info(
            "[개별촬영][점선] %s 좌표=%s 방향=%s 점선조각=%s 간격=%s",
            group["group_id"], group["point"], group["orientation"],
            group.get("dash_count"), group.get("gaps_px"),
        )
    ok, encoded_overlay = cv2.imencode(".png", overlay)
    if not ok:
        raise RuntimeError("분석 근거 이미지 PNG 인코딩에 실패했습니다.")
    overlay_temp = overlay_path.with_suffix(".png.tmp")
    try:
        with overlay_temp.open("xb") as stream:
            stream.write(encoded_overlay.tobytes())
        os.replace(overlay_temp, overlay_path)
    finally:
        overlay_temp.unlink(missing_ok=True)

    # A magnified ROI preview lets the inspector identify S1..SN in the UI,
    # while the original and full-size overlay remain immutable.
    roi = stop_line.get("roi")
    if roi and len(roi) == 4:
        left, top, right, bottom = [int(value) for value in roi]
        padding = 20
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(overlay.shape[1], right + padding)
        bottom = min(overlay.shape[0], bottom + padding)
        focus = overlay[top:bottom, left:right]
    else:
        focus = overlay
    ok, encoded_focus = cv2.imencode(".png", focus)
    if not ok:
        raise RuntimeError("정지선 후보 미리보기 PNG 인코딩에 실패했습니다.")
    focus_temp = focus_path.with_suffix(".png.tmp")
    try:
        with focus_temp.open("xb") as stream:
            stream.write(encoded_focus.tobytes())
        os.replace(focus_temp, focus_path)
    finally:
        focus_temp.unlink(missing_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": 1, "case_id": case_id, "revision": revision,
        "unassigned": unassigned,
        "case_id_status": "unassigned" if unassigned else "assigned",
        "captured_at_utc": captured_at, "analyzed_at_utc": now,
        "source": "input_tool_manual_wgc",
        "input_tool_image": raw_path.relative_to(folder).as_posix(),
        "input_tool_overlay": overlay_path.relative_to(folder).as_posix(),
        "input_tool_focus": focus_path.relative_to(folder).as_posix(),
        "red_marker": marker,
        "location": {
            "reference": "input_tool_current_position_red_marker",
            "meaning": "current_user_position",
            "status": marker["status"],
            "coordinate_system": "captured_input_tool_image_pixels",
            "image_size": [int(input_tool_image.shape[1]), int(input_tool_image.shape[0])],
            "canvas_bounds": marker["canvas_bounds"],
            "canvas_center": marker["canvas_center"],
            "image_point": point,
            "center_offset_px": marker["center_offset_px"],
            "normalized_point": (
                [round(point[0] / input_tool_image.shape[1], 6),
                 round(point[1] / input_tool_image.shape[0], 6)]
                if point is not None else None
            ),
            "canvas_normalized_point": (
                [
                    round((point[0] - marker["canvas_bounds"][0]) /
                          (marker["canvas_bounds"][2] - marker["canvas_bounds"][0]), 6),
                    round((point[1] - marker["canvas_bounds"][1]) /
                          (marker["canvas_bounds"][3] - marker["canvas_bounds"][1]), 6),
                ]
                if point is not None else None
            ),
            "geographic_coordinates": None,
            "is_intersection_center": False,
            "road_id": None, "angle_deg": None, "heading_deg": None,
        },
        "checks": {"stop_line": stop_line, "center_line": center_line,
                   "lane_line": lane_line, "dashed_lane_line": dashed_lane_line},
        "human_review": "requires_human_review",
        "warning": (
            "빨간 표시는 현재 사용자 위치의 화면 좌표 후보입니다. 실제 지도 좌표·진행 방향은 "
            "추정하지 않습니다. 정지선·노란 중앙선·흰색 실선 및 점선 후보도 사람 검수가 필요합니다."
        ),
    }
    history_path = folder / f"individual_analysis_r{revision:03d}.json"
    _write_json(history_path, record)
    _write_json(folder / "individual_analysis.json", record)
    for entry in manifest["history"]:
        if int(entry.get("revision", -1)) == revision:
            entry["analysis"] = history_path.name
            entry["analyzed_at_utc"] = now
            break
    _write_json(manifest_path, manifest)
    APP_LOG.info(
        "[개별촬영][위치진단] 완료 촬영버전=%d 원본=%s 근거오버레이=%s "
        "보고서=%s 상태=%s 후보이미지=%s",
        revision, raw_path.name, overlay_path.name, history_path.name,
        marker["status"], focus_path.name,
    )
    return {
        "kind": "individual_analysis", "folder": str(folder), "case_id": case_id,
        **record,
    }

def capture_individual(
    folder: Path, case_id: str, image: np.ndarray, *, unassigned: bool = False,
) -> dict:
    """Save an immutable WGC frame and manifest entry, without analysis."""
    return capture_and_analyze(folder, case_id, image,
                               unassigned=unassigned, capture_only=True)


def analyze_individual(folder: Path, case_id: str, revision: int) -> dict:
    """Recompute a selected saved photo, replacing only this version's derived files."""
    return capture_and_analyze(
        folder, case_id, None,
        unassigned=folder.parent.name == "_unassigned_individual",
        existing_revision=revision,
    )
