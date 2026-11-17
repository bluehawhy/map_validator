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

from .analysis.input_tool.local_stop_line import (
    local_stop_line_candidates, paint_stop_line_roi_border,
)
from .analysis.input_tool.local_center_line import local_center_line_candidates
from .analysis.input_tool.local_guidance_line import (
    local_guidance_line_candidates, paint_guidance_roi_border,
    local_approach_path_candidates, paint_approach_roi_border,
)
from .analysis.input_tool.local_white_marking import local_white_marking_candidates
from .analysis.input_tool.local_ui_text import (
    fixed_ui_text_exclusion, paint_ui_text_exclusion,
)
from .analysis.input_tool.local_road_arrow import (
    local_road_arrow_candidates, paint_arrow_candidates,
)
from .analysis.input_tool.red_marker import find_red_marker
from .individual_capture_index import list_individual_capture_files
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


def _recover_missing_capture_history(folder: Path, manifest: dict) -> tuple[dict[int, Path], bool]:
    """Restore missing manifest entries from raw PNG files without changing them.

    Existing history entries/analysis links remain untouched. When the original
    capture time is absent, file mtime is only an estimated fallback and is
    explicitly marked as recovered rather than presented as a true shot time.
    """
    originals = list_individual_capture_files(folder)
    history = manifest.setdefault("history", [])
    if not isinstance(history, list):
        raise ValueError("개별 촬영 기록의 history 형식이 올바르지 않습니다.")

    recorded: dict[int, dict] = {}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        try:
            revision = int(entry.get("revision", -1))
        except (TypeError, ValueError):
            continue
        if revision > 0 and revision not in recorded:
            recorded[revision] = entry

    changed = False
    for revision, raw_path in originals.items():
        entry = recorded.get(revision)
        if entry is None:
            entry = {"revision": revision}
            history.append(entry)
            recorded[revision] = entry
            changed = True
            APP_LOG.warning(
                "[개별촬영][이력복구] 원본 PNG로 누락 버전 r%03d 복원: %s",
                revision, raw_path.name,
            )
        relative_path = raw_path.relative_to(folder).as_posix()
        if entry.get("input_tool_image") != relative_path:
            entry["input_tool_image"] = relative_path
            changed = True
        if not entry.get("captured_at_utc"):
            entry["captured_at_utc"] = datetime.fromtimestamp(
                raw_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            entry["captured_at_source"] = "file_mtime_recovered"
            changed = True
        # Do not synthesize a completed analysis for a recovered raw capture.
    return originals, changed


def capture_and_analyze(
    folder: Path, case_id: str, input_tool_image: np.ndarray | None,
    *, unassigned: bool = False, capture_only: bool = False,
    existing_revision: int | None = None,
    center_line_grouping: dict | None = None,
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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("case_id") != case_id:
        raise ValueError("개별 촬영 기록의 검수 ID 또는 버전이 일치하지 않습니다.")

    original_files, recovered = _recover_missing_capture_history(folder, manifest)
    if existing_revision is None:
        recorded_revisions = set()
        for entry in manifest["history"]:
            if isinstance(entry, dict):
                try:
                    recorded_revisions.add(int(entry.get("revision", -1)))
                except (TypeError, ValueError):
                    pass
        revision = max({0, *original_files.keys(), *recorded_revisions}) + 1
        while (target_dir / f"input_tool_r{revision:03d}.png").exists():
            revision += 1
    else:
        revision = int(existing_revision)
        if revision not in original_files:
            raise FileNotFoundError(
                f"선택한 개별 촬영 원본 input_tool_r{revision:03d}.png가 없습니다."
            )
        if recovered or not manifest_path.is_file():
            _write_json(manifest_path, manifest)

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
    bounds = marker.get("canvas_bounds")
    # All three ROIs use the same red marker and black canvas bounds.
    # None of their boundaries depend on a detected line or another ROI.
    guide_lines = local_guidance_line_candidates(
        input_tool_image, point, overlay, canvas_bounds=bounds,
    )
    stop_line = local_stop_line_candidates(
        input_tool_image, point, overlay, canvas_bounds=bounds,
    )
    approach_paths = local_approach_path_candidates(
        input_tool_image, point, overlay, canvas_bounds=bounds,
    )
    available = [x["roi"] for x in (guide_lines,stop_line,approach_paths)
                 if x.get("roi") is not None]
    scan_bounds = ([min(x[0] for x in available),
                    min(x[1] for x in available),
                    max(x[2] for x in available),
                    max(x[3] for x in available)]
                   if available else None)
    APP_LOG.info(
        "[개별촬영][ROI] 기준=red_marker.point 현재위치=%s GUIDE=%s STOP=%s PATH=%s C/W내부=%s",
        point, guide_lines.get("roi"),stop_line.get("roi"),
        approach_paths.get("roi"),scan_bounds,
    )
    for group in stop_line.get("line_groups",[]):
        APP_LOG.info(
            "[개별촬영][선그룹] %s 구성=%s 방향=%s 좌표=%s",
            group["group_id"],",".join(group["member_ids"]),
            group["angle_deg"],group["endpoints"],
        )
    center_line = local_center_line_candidates(
        input_tool_image,point,overlay,roi=scan_bounds,
        grouping_rules=center_line_grouping,
    )
    raw_white = local_white_marking_candidates(
        input_tool_image,point,np.zeros_like(overlay),roi=scan_bounds,
    )
    ui_text,text_white_exclusion = fixed_ui_text_exclusion(
        input_tool_image,bounds,roi=scan_bounds,
    )
    after_ui = local_white_marking_candidates(
        input_tool_image,point,np.zeros_like(overlay),roi=scan_bounds,
        exclude_mask=text_white_exclusion,excluded_objects=["fixed_ui_status_text"],
    )
    road_arrows,arrow_region_exclusion = local_road_arrow_candidates(
        input_tool_image,point,roi=stop_line.get("roi"),
    )
    combined_exclusion = cv2.bitwise_or(
        text_white_exclusion,arrow_region_exclusion,
    )
    paint_ui_text_exclusion(overlay,ui_text)
    white_markings = local_white_marking_candidates(
        input_tool_image,point,overlay,roi=scan_bounds,
        exclude_mask=combined_exclusion,
        excluded_objects=["fixed_ui_status_text","road_arrow_green_framed_region"],
    )
    paint_arrow_candidates(overlay,road_arrows)
    paint_stop_line_roi_border(overlay,stop_line)
    paint_guidance_roi_border(overlay,guide_lines)
    paint_approach_roi_border(overlay,approach_paths)
    APP_LOG.info(
        "[개별촬영][중앙선] 노란조각=%s 1차그룹=%s 2차그룹=%s ROI=%s 2차설정=%s",
        center_line.get("total_segments", 0),
        center_line.get("first_pass_group_count", 0),
        center_line.get("second_pass_group_count", 0),
        center_line.get("roi"),
        center_line.get("grouping_rules", {}).get("second_pass"),
    )
    APP_LOG.info(
        "[개별촬영][유도선/경로] U=%s P=%s",
        guide_lines.get("group_count",0),approach_paths.get("group_count",0),
    )
    APP_LOG.info(
        "[개별촬영][UI문자] 제외영역=%s 흰색제외픽셀=%s 원본W=%s 문자제외후W=%s",
        [r.get("bbox") for r in ui_text.get("regions", [])],
        ui_text.get("excluded_white_pixels", 0),
        raw_white.get("total_segments", 0), after_ui.get("total_segments", 0),
    )
    APP_LOG.info(
        "[개별촬영][화살표] A후보=%s 초록외곽기준영역=%spx 흰색제외=%spx 문자제외후W=%s 최종W=%s 겹친조각제외=%s",
        road_arrows.get("candidate_count", 0),
        road_arrows.get("excluded_region_pixels", 0),
        road_arrows.get("excluded_white_pixels", 0),
        after_ui.get("total_segments", 0),
        white_markings.get("total_segments", 0),
        white_markings.get("rejected_mask_overlap_segments", 0),
    )
    APP_LOG.info(
        "[개별촬영][흰색원시후보] W조각=%s 표시=%s 생략=%s ROI=%s 분류=%s",
        white_markings.get("total_segments", 0),
        white_markings.get("shown_segments", 0),
        white_markings.get("omitted_segments", 0),
        white_markings.get("roi"),
        white_markings.get("classification_status"),
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
    roi = scan_bounds
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
        "candidate_search_bounds": scan_bounds,
        "checks": {"stop_line": stop_line, "center_line": center_line,
                   "guidance_lines": guide_lines,
                   "approach_paths": approach_paths,
                   "ui_text_exclusion": ui_text, "road_arrows": road_arrows,
                   "white_marking_candidates_raw": raw_white,
                   "white_marking_candidates_after_ui": after_ui,
                   "white_marking_candidates": white_markings},
        "review_regions": {
            "stop_line_S_G": {
                "roi": stop_line.get("roi"),
                "candidate_count": len(stop_line.get("line_candidates", [])),
                "group_count": len(stop_line.get("line_groups", [])),
                "border": "STOP ROI (orange)",
            },
            "center_line_C": {
                "roi": center_line.get("roi"),
                "candidate_count": len(center_line.get("line_groups", [])),
                "border": "none (internal combined search)",
            },
            "road_arrow_A": {
                "roi": road_arrows.get("roi"),
                "candidate_count": len(road_arrows.get("candidates", [])),
                "border": "STOP ROI (shared)",
            },
            "white_W": {
                "roi": white_markings.get("roi"),
                "candidate_count": len(white_markings.get("line_candidates", [])),
                "border": "none (internal combined search)",
            },
            "guidance_U": {
                "roi": guide_lines.get("roi"),
                "candidate_count": guide_lines.get("group_count", 0),
                "border": "GUIDE ROI (magenta)",
            },
            "approach_path_P": {
                "roi": approach_paths.get("roi"),
                "candidate_count": approach_paths.get("group_count", 0),
                "border": "PATH ROI (blue-green)",
            },
        },
        "human_review": "requires_human_review",
        "warning": (
            "빨간 표시는 현재 사용자 위치의 화면 좌표 후보입니다. 실제 지도 좌표·진행 방향은 "
            "추정하지 않습니다. 정지선 S/G·중앙선 C·유도선 U·진입 경로 P·노면화살표 A·흰선 W 후보는 사람 검수가 필요합니다."
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


def analyze_individual(
    folder: Path, case_id: str, revision: int,
    *, center_line_grouping: dict | None = None,
) -> dict:
    """Recompute a selected saved photo, replacing only this version's derived files."""
    return capture_and_analyze(
        folder, case_id, None,
        unassigned=folder.parent.name == "_unassigned_individual",
        existing_revision=revision,
        center_line_grouping=center_line_grouping,
    )
