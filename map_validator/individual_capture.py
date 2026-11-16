"""Independent input_tool location capture with immutable versions.

No camera/window control; caller supplies a WGC frame. This first review mode
locates the red marker and saves local stop-line candidates for human feedback.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .analysis.input_tool.local_stop_line import local_stop_line_candidates
from .analysis.input_tool.red_marker import find_red_marker
from .stage_types import validate_case_id

MANIFEST = "individual_capture.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def capture_and_analyze(
    folder: Path, case_id: str, input_tool_image: np.ndarray,
) -> dict:
    validate_case_id(case_id)
    if input_tool_image is None or input_tool_image.size == 0:
        raise ValueError("input_tool 촬영 이미지가 비었습니다.")
    target_dir = folder / "captures" / "individual"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "schema_version": 1, "case_id": case_id, "history": [],
    }
    if manifest.get("schema_version") != 1 or manifest.get("case_id") != case_id:
        raise ValueError("개별 촬영 기록의 검수 ID 또는 버전이 일치하지 않습니다.")
    revision = len(manifest.get("history", [])) + 1
    while (target_dir / f"input_tool_r{revision:03d}.png").exists():
        revision += 1

    raw_path = target_dir / f"input_tool_r{revision:03d}.png"
    overlay_path = target_dir / f"input_tool_r{revision:03d}_overlay.png"
    if not cv2.imencode(".png", input_tool_image)[0]:
        raise RuntimeError("촬영 이미지 PNG 인코딩에 실패했습니다.")
    encoded = cv2.imencode(".png", input_tool_image)[1].tobytes()
    temp_path = raw_path.with_suffix(".png.tmp")
    try:
        with temp_path.open("xb") as stream:
            stream.write(encoded)
        os.replace(temp_path, raw_path)
    finally:
        temp_path.unlink(missing_ok=True)

    marker = find_red_marker(input_tool_image)
    overlay = input_tool_image.copy()
    point = marker.get("point")
    if point is not None:
        cv2.circle(overlay, (round(point[0]), round(point[1])), 13, (0, 255, 255), 2)
    stop_line = local_stop_line_candidates(input_tool_image, point, overlay)
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

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": 1, "case_id": case_id, "revision": revision,
        "captured_at_utc": now, "source": "input_tool_manual_wgc",
        "input_tool_image": raw_path.relative_to(folder).as_posix(),
        "input_tool_overlay": overlay_path.relative_to(folder).as_posix(),
        "red_marker": marker, "checks": {"stop_line": stop_line},
        "human_review": "requires_human_review",
        "warning": "정지선 후보는 확정 판정이 아닙니다. 위치 기준점과 선형은 현장 사진으로 검증해야 합니다.",
    }
    history_path = folder / f"individual_analysis_r{revision:03d}.json"
    _write_json(history_path, record)
    _write_json(folder / "individual_analysis.json", record)
    manifest.setdefault("history", []).append({
        "revision": revision, "captured_at_utc": now,
        "input_tool_image": record["input_tool_image"],
        "analysis": history_path.name,
    })
    _write_json(manifest_path, manifest)
    return {
        "kind": "individual_analysis", "folder": str(folder), "case_id": case_id,
        **record,
    }
