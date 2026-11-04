"""Analyze already-saved roadview screenshots without controlling Windows.

The UI's '도로후보 분석' action reads only images in the selected case
folder. It never captures a window, moves a roadview, activates a program,
or rewrites the original screenshots or capture report.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .capture_naming import capture_file_name
from .road_analysis import RoadSegmenter, analyze_road_mask, draw_review_overlay


def _roadview_screenshots(folder: Path, case_id: str, roadview_title: str) -> list[Path]:
    """Find only original roadview PNGs, not work images or overlays."""
    # capture_file_name normalizes the ID, sanitizes the program name, and
    # provides the same filename convention as '캡쳐만'.
    single_name = capture_file_name(case_id, roadview_title, 0, 1)
    stem = single_name[:-4]
    numbered = re.compile(rf"^{re.escape(stem)}_(\d+)\.png$", re.IGNORECASE)
    legacy = re.compile(r"^frame_(\d+)\.png$", re.IGNORECASE)

    candidates: list[tuple[int, Path]] = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".png":
            continue
        if path.name.casefold() == single_name.casefold():
            candidates.append((0, path))
            continue
        match = numbered.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
            continue
        match = legacy.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    return [path for _, path in sorted(candidates, key=lambda entry: (entry[0], entry[1].name))]


def analyze_saved_images(
    output: Path,
    case_id: str,
    roadview_title: str,
    analysis_settings: dict,
    progress: Callable[[str], None],
    check_stop: Callable[[], None],
) -> dict:
    """Run candidate-only segmentation on existing PNGs in an existing folder."""
    check_stop()
    if not output.is_dir():
        raise FileNotFoundError(
            f"검수 ID의 스크린샷 폴더가 없습니다: {output}. 먼저 '캡쳐만'을 실행하세요."
        )

    source_files = _roadview_screenshots(output, case_id, roadview_title)
    if not source_files:
        raise FileNotFoundError(
            f"로드뷰 스크린샷을 찾지 못했습니다: {output}. "
            "먼저 '캡쳐만'으로 로드뷰 PNG를 저장해 주세요."
        )

    progress(f"기존 로드뷰 사진 {len(source_files)}장 확인 · AI 모델 준비 중")
    check_stop()
    segmenter = RoadSegmenter(
        analysis_settings.get(
            "model_name", "nvidia/segformer-b0-finetuned-ade-512-512"
        )
    )
    vertical_range = tuple(analysis_settings.get("vertical_range", [0.28, 0.60]))
    threshold = float(analysis_settings.get("side_road_score_threshold", 0.19))

    frames: list[dict] = []
    for index, source in enumerate(source_files):
        check_stop()
        progress(f"저장된 사진 분석 {index + 1}/{len(source_files)}: {source.name}")
        # np.fromfile + imdecode also supports non-ASCII Windows paths.
        raw = np.fromfile(str(source), dtype=np.uint8)
        frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"로드뷰 이미지 파일을 읽지 못했습니다: {source}")
        mask = segmenter.mask(frame)
        check_stop()
        direction = analyze_road_mask(mask, threshold, vertical_range)
        overlay = draw_review_overlay(frame, mask, direction, vertical_range)
        overlay_path = source.with_name(source.stem + "_overlay.png")
        encoded, png = cv2.imencode(".png", overlay)
        if not encoded:
            raise RuntimeError(f"분석 오버레이 PNG 인코딩 실패: {overlay_path}")
        png.tofile(str(overlay_path))
        frames.append({
            "frame": index,
            "image": source.name,
            "overlay": overlay_path.name,
            **direction.as_dict(),
        })

    check_stop()

    def summary(key: str) -> str:
        return (
            "possible" if any(bool(frame[key]) for frame in frames)
            else "not_detected_review_required"
        )

    report = {
        "case_id": case_id,
        "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "saved_roadview_screenshots",
        "frames": frames,
        "left_road": summary("left_candidate"),
        "right_road": summary("right_candidate"),
        "final_decision": "requires_human_review",
        "warning": (
            "Road segmentation gives candidates only; original HD_3D Tool "
            "line geometry and true turn-lane presence need human review."
        ),
    }
    (output / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    progress(f"저장된 사진 {len(frames)}장 후보 분석 완료")
    return {
        "kind": "analysis",
        "left": report["left_road"],
        "right": report["right_road"],
        "folder": str(output),
        "frames": len(frames),
    }
