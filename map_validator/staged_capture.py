"""Persist manual stage photo pairs, including photos of directions with no road.

Never touches target windows; it only stores already captured frames.
All new revisions are immutable and original PNGs are preserved.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .capture_naming import capture_file_name
from .stage_types import STAGES, validate_case_id, validate_stage

MANIFEST_NAME = "staged_capture.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_stage() -> dict:
    return {
        "state": "not_captured", "revision": 0, "history": [],
    }


def read_manifest(folder: Path, case_id: str) -> dict:
    """Read staged capture state; do not modify the filesystem."""
    validate_case_id(case_id)
    path = folder / MANIFEST_NAME
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("case_id") != case_id:
            raise ValueError("단계별 촬영 기록의 검수 ID가 현재 검수 ID와 다릅니다.")
        if not isinstance(manifest.get("stages"), dict):
            raise ValueError("단계별 촬영 기록의 stages 값이 올바르지 않습니다.")
        if manifest.get("schema_version") != 1:
            raise ValueError("지원하지 않는 단계별 촬영 기록 버전입니다.")
    else:
        manifest = {"schema_version": 1, "case_id": case_id, "stages": {}}

    for stage in STAGES:
        if stage not in manifest["stages"]:
            manifest["stages"][stage] = _default_stage()
    return manifest


def stored_image(folder: Path, relative: str | None) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    resolved_folder = folder.resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(resolved_folder):
        raise ValueError("촬영 기록의 이미지 경로가 검수 폴더를 벗어납니다.")
    return path if path.is_file() else None


def stage_status(folder: Path, record: dict) -> str:
    """Do not classify missing data as a road that does not exist."""
    has_work = stored_image(folder, record.get("work_image")) is not None
    has_road = stored_image(folder, record.get("roadview_image")) is not None
    if has_work and has_road:
        return "captured"
    if has_work or has_road:
        return "partial_capture"
    return "not_captured"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def capture_stage(
    folder: Path, case_id: str, stage: str,
    work_title: str, roadview_title: str,
    work_image: np.ndarray, roadview_image: np.ndarray,
) -> dict:
    """Save two pre-captured WGC frames as an all-or-nothing stage revision."""
    case_id = validate_case_id(case_id)
    stage = validate_stage(stage)
    manifest = read_manifest(folder, case_id)
    previous = dict(manifest["stages"][stage])
    target_dir = folder / "captures" / stage
    target_dir.mkdir(parents=True, exist_ok=True)

    revision = max(0, int(previous.get("revision") or 0)) + 1
    while True:
        rev_suffix = f"_r{revision:02d}" if revision > 1 else ""
        work_base = capture_file_name(case_id, f"{stage}_{work_title}", 0, 1)
        view_base = capture_file_name(case_id, f"{stage}_{roadview_title}", 0, 1)
        work_name = work_base[:-4] + rev_suffix + ".png"
        view_name = view_base[:-4] + rev_suffix + ".png"
        work_path, view_path = target_dir / work_name, target_dir / view_name
        if not work_path.exists() and not view_path.exists():
            break
        revision += 1

    # Encode both images before writing any new file.
    encoded: list[bytes] = []
    for image, name in ((work_image, work_name), (roadview_image, view_name)):
        if image is None or image.size == 0:
            raise ValueError(f"촬영 이미지가 비어 있습니다: {name}")
        success, buffer = cv2.imencode(".png", image)
        if not success:
            raise RuntimeError(f"PNG 인코딩 실패: {name}")
        encoded.append(buffer.tobytes())

    created: list[Path] = []
    temps: list[Path] = []
    try:
        for path, data in zip((work_path, view_path), encoded):
            temporary = path.with_suffix(".png.tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
            temps.append(temporary)
        for temporary, final in zip(temps, (work_path, view_path)):
            os.replace(temporary, final)
            created.append(final)

        history = list(previous.get("history") or [])
        if previous.get("work_image") or previous.get("roadview_image"):
            history.append({
                key: previous.get(key) for key in (
                    "revision", "work_image", "roadview_image", "captured_at"
                )
            })
        manifest["stages"][stage] = {
            "state": "captured",
            "revision": revision,
            "work_image": work_path.relative_to(folder).as_posix(),
            "roadview_image": view_path.relative_to(folder).as_posix(),
            "captured_at": _now(),
            "history": history,
        }
        _write_json(folder / MANIFEST_NAME, manifest)
    except Exception:
        # Preserve all previous revisions and manifest on partial failure.
        for temp in temps:
            temp.unlink(missing_ok=True)
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return {
        "stage": stage, "folder": str(folder),
        "revision": revision, "state": "captured",
        "work_image": str(work_path), "roadview_image": str(view_path),
    }
