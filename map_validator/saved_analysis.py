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
from .line_geometry import extract_line_geometry, compare_with_roadview
from .road_analysis import RoadSegmenter, analyze_road_mask, draw_review_overlay
from .road_shape import trace_road_corridor, draw_road_corridor


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
    work_title: str,
    analysis_settings: dict,
    progress: Callable[[str], None],
    check_stop: Callable[[], None],
) -> dict:
    """Compare existing HD_3D Tool route lines with saved roadview road regions."""
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
    work_base = capture_file_name(case_id, work_title, 0, 1)
    road_base = capture_file_name(case_id, roadview_title, 0, 1)
    road_stem = road_base[:-4]
    work_stem = work_base[:-4]
    geometry_cache: dict[str, tuple[dict, str | None]] = {}

    def work_geometry(road_source: Path) -> tuple[dict, str | None, str | None]:
        """Match the input-tool image by the same capture suffix."""
        suffix = road_source.stem[len(road_stem):] if (
            road_source.stem.casefold().startswith(road_stem.casefold())
        ) else ""
        matching = output / (work_stem + suffix + ".png")
        if not matching.is_file():
            matching = output / work_base
        if not matching.is_file():
            return (
                {"status": "unknown", "expected_turn": "unknown",
                 "reason": "해당 검수 ID의 HD_3D Tool 스크린샷이 없습니다."},
                None, None,
            )
        cache_key = str(matching)
        if cache_key not in geometry_cache:
            raw = np.fromfile(str(matching), dtype=np.uint8)
            work_image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if work_image is None:
                raise ValueError(f"입력도구 이미지 파일을 읽지 못했습니다: {matching}")
            info, geometry_overlay = extract_line_geometry(work_image)
            overlay_path = matching.with_name(matching.stem + "_geometry.png")
            success, encoded = cv2.imencode(".png", geometry_overlay)
            if not success:
                raise RuntimeError(f"입력툴 선형 표시 PNG 인코딩 실패: {overlay_path}")
            encoded.tofile(str(overlay_path))
            geometry_cache[cache_key] = (info, overlay_path.name)
        geometry, overlay_name = geometry_cache[cache_key]
        return geometry, overlay_name, matching.name

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
        road_corridor = trace_road_corridor(mask)
        check_stop()
        input_geometry, input_overlay, input_image = work_geometry(source)
        comparison = compare_with_roadview(
            input_geometry, direction.as_dict(), road_corridor
        )
        overlay = draw_review_overlay(frame, mask, direction, vertical_range)
        overlay = draw_road_corridor(overlay, road_corridor)
        comparison_label = (
            f"INPUT {comparison['expected_turn'].upper()}: "
            f"{comparison['status'].upper()}"
        )
        cv2.rectangle(overlay, (0, 0), (min(frame.shape[1], 760), 34), (0, 0, 0), -1)
        cv2.putText(
            overlay, comparison_label, (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX, .49, (255, 255, 255), 1,
            cv2.LINE_AA,
        )
        overlay_path = source.with_name(source.stem + "_overlay.png")
        encoded, png = cv2.imencode(".png", overlay)
        if not encoded:
            raise RuntimeError(f"분석 오버레이 PNG 인코딩 실패: {overlay_path}")
        png.tofile(str(overlay_path))
        frames.append({
            "frame": index,
            "image": source.name,
            "overlay": overlay_path.name,
            "work_image": input_image,
            "work_geometry_overlay": input_overlay,
            "input_line_geometry": input_geometry,
            "roadview_corridor": road_corridor,
            "geometry_comparison": comparison,
            **direction.as_dict(),
        })

    check_stop()

    def summary(key: str) -> str:
        return (
            "possible" if any(bool(frame[key]) for frame in frames)
            else "not_detected_review_required"
        )

    comparison_statuses = [
        frame["geometry_comparison"]["status"] for frame in frames
    ]
    evidence = set(comparison_statuses)
    consistent = {
        "geometry_consistent_candidate", "direction_consistent_candidate"
    }
    if "possible_mismatch_review" in evidence and evidence.intersection(consistent):
        overall_comparison = "mixed_evidence_review"
    elif "possible_mismatch_review" in evidence:
        overall_comparison = "possible_mismatch_review"
    elif "geometry_consistent_candidate" in evidence:
        overall_comparison = "geometry_consistent_candidate"
    elif "direction_consistent_candidate" in evidence:
        overall_comparison = "direction_consistent_candidate"
    else:
        overall_comparison = "insufficient_evidence"

    report = {
        "case_id": case_id,
        "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "saved_work_and_roadview_screenshots",
        "geometry_comparison_status": overall_comparison,
        "frames": frames,
        "left_road": summary("left_candidate"),
        "right_road": summary("right_candidate"),
        "final_decision": "requires_human_review",
        "warning": (
            "Cyan entry -> orange connector -> blue exit from the work image "
            "is compared with roadview road-corridor curvature and branch candidates. "
            "No calibrated 3D alignment or lane-connectivity proof is possible "
            "from these screenshots alone. Human verification is required."
        ),
    }
    (output / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    progress(
        f"저장된 사진 {len(frames)}장 · 입력툴 선형 대조 완료 "
        f"({overall_comparison})"
    )
    return {
        "kind": "analysis",
        "geometry_comparison_status": overall_comparison,
        "left": report["left_road"],
        "right": report["right_road"],
        "folder": str(output),
        "frames": len(frames),
    }
