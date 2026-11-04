"""Analyze manually captured four-stage photo pairs without controlling windows.

Comparison logic keeps expected map data, observed roadview evidence and
per-field uncertainty separate; no status constitutes an automatic approval.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .input_features import extract_input_features
from .road_analysis import RoadSegmenter
from .roadview_features import extract_roadview_features
from .road_scores import (
    assemble_score_record,
    save_score_record,
    score_road_mask,
)
from .stage_types import FIELD_LABELS, STAGES, STAGE_LABELS, fields_for_stage
from .staged_capture import read_manifest, stage_status, stored_image


def _read_image(path: Path) -> np.ndarray:
    raw = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"근거 이미지 생성 실패: {path}")
    encoded.tofile(str(path))


def compare_values(expected: dict, observed: dict, field: str) -> dict:
    lhs, rhs = expected.get("value"), observed.get("value")
    if lhs is None or rhs is None:
        status = "insufficient_evidence"
        reason = "입력툴 기대값 또는 실제 로드뷰 관측값의 근거가 부족합니다."
    elif lhs == rhs:
        status = "match_candidate"
        reason = "입력툴·로드뷰 후보 값이 같습니다. 실제 현장 검수가 필요합니다."
    else:
        status = "mismatch_review"
        if field == "road_exists" and lhs is True and rhs is False:
            reason = (
                "입력툴에는 해당 방향의 도로가 있지만 로드뷰 전방 중앙에는 "
                "건물 등 비도로 영역이 우세한 것으로 검출됐습니다. "
                "실제 촬영 위치와 해당 방향을 확인하세요."
            )
        else:
            reason = "입력툴 기대값과 로드뷰 관측값이 다릅니다. 사람 검수가 필요합니다."
    if field == "stop_line":
        verdict = (
            "REVIEW" if lhs is None or rhs is None
            else "PASS" if lhs == rhs else "FAIL"
        )
        if verdict == "PASS":
            reason = "입력툴의 시안색 가로 정지선과 로드뷰의 실제 정지선 존재 여부가 같습니다."
        elif verdict == "FAIL":
            reason = "입력툴의 시안색 가로 정지선과 로드뷰의 실제 정지선 존재 여부가 다릅니다."
        else:
            reason = (
                "정지선 유무를 확정할 수 없습니다. 횡단보도는 정지선으로 취급하지 "
                "않으며, 검수자가 실제 로드뷰를 추가 확인해야 합니다."
            )
    else:
        verdict = None
    return {
        "status": status,
        "verdict": verdict,
        "expected_value": lhs,
        "observed_value": rhs,
        "field": field, "label": FIELD_LABELS[field],
        "reason": reason,
        "expected_confidence": expected.get("confidence"),
        "observed_confidence": observed.get("confidence"),
    }


def _atomic_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def analyze_stages(
    folder: Path, case_id: str, model_name: str,
    progress: Callable[[str], None], check_stop: Callable[[], None],
    stop_line_threshold: float = .68,
) -> dict:
    """Run one SegFormer inference per captured roadview stage; no recapture."""
    check_stop()
    if not .35 <= stop_line_threshold <= .95:
        raise ValueError("로드뷰 정지선 threshold는 0.35~0.95 범위여야 합니다.")
    manifest = read_manifest(folder, case_id)
    available = [
        stage for stage in STAGES
        if stage_status(folder, manifest["stages"][stage]) == "captured"
    ]
    if not available:
        raise FileNotFoundError(
            "현재 검수 ID의 4단계 촬영본이 없습니다. 먼저 진입 전·좌·직·우 촬영을 진행하세요."
        )

    progress(f"촬영 완료 {len(available)}/4단계 · 도로/건물 분석 모델 준비")
    segmenter = RoadSegmenter(model_name)
    report = {
        "schema_version": 1, "case_id": case_id,
        "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "four_stage_saved_wgc_images",
        "human_review": "requires_human_review",
        "stages": {},
    }
    mismatch_count = 0
    assessed = 0
    for stage in STAGES:
        check_stop()
        record = manifest["stages"][stage]
        state = stage_status(folder, record)
        if state != "captured":
            report["stages"][stage] = {
                "stage": stage, "label": STAGE_LABELS[stage],
                "capture_state": state, "analysis_state": "not_analyzed",
                "reason": "입력툴·로드뷰 사진 쌍이 아직 완성되지 않았습니다.",
                "comparison": {},
            }
            continue

        progress(f"{STAGE_LABELS[stage]}: 입력툴 기대값 및 로드뷰 도로·건물 분석")
        input_path = stored_image(folder, record.get("work_image"))
        road_path = stored_image(folder, record.get("roadview_image"))
        if input_path is None or road_path is None:
            raise RuntimeError("촬영 상태 변경으로 원본 파일을 찾지 못했습니다.")
        input_image = _read_image(input_path)
        road_image = _read_image(road_path)
        input_expected, input_overlay, route = extract_input_features(input_image, stage)
        check_stop()
        masks = segmenter.class_masks(road_image)
        # One segmentation pass supplies BOTH the qualitative detector and
        # the six-number, future-comparable road-pixel score dataset.
        score_observation = score_road_mask(masks["road"])
        roadview_observed, road_overlay, evidence = extract_roadview_features(
            road_image, stage, masks, stop_line_threshold=stop_line_threshold
        )
        compare = {
            key: compare_values(input_expected[key], roadview_observed[key], key)
            for key in fields_for_stage(stage)
        }
        statuses = {item["status"] for item in compare.values()}
        if "mismatch_review" in statuses:
            stage_result = "mismatch_review"
            mismatch_count += 1
        elif "match_candidate" in statuses:
            stage_result = "partial_evidence_review"
        else:
            stage_result = "insufficient_evidence"
        assessed += 1

        revision = int(record.get("revision", 0))
        overlay_dir = folder / "overlays"
        input_annotated = overlay_dir / f"{stage}_r{revision:02d}_input.png"
        road_annotated = overlay_dir / f"{stage}_r{revision:02d}_roadview.png"
        _write_image(input_annotated, input_overlay)
        _write_image(road_annotated, road_overlay)

        report["stages"][stage] = {
            "stage": stage, "label": STAGE_LABELS[stage],
            "capture_state": "captured", "analysis_state": stage_result,
            "revision": revision,
            "input_expected": input_expected,
            "roadview_observed": roadview_observed,
            "comparison": compare,
            "stop_line_verdict": (
                compare["stop_line"].get("verdict") if stage == "before" else None
            ),
            "route_candidate": route,
            "roadview_semantic_evidence": evidence,
            "roadview_scores": score_observation["scores"],
            "roadview_score_details": {
                "method": score_observation["method"],
                "pixels": score_observation["pixels"],
                "vertical_range": score_observation["vertical_range"],
                "horizontal_regions": score_observation["horizontal_regions"],
            },
            "evidence": {
                "input_image": input_path.relative_to(folder).as_posix(),
                "roadview_image": road_path.relative_to(folder).as_posix(),
                "input_overlay": input_annotated.relative_to(folder).as_posix(),
                "roadview_overlay": road_annotated.relative_to(folder).as_posix(),
            },
            "human_review": "requires_human_review",
        }

    check_stop()
    overall = (
        "mismatch_review" if mismatch_count else
        "partial_evidence_review" if assessed else "insufficient_evidence"
    )
    report["summary"] = {
        "captured_stages": assessed,
        "required_stages": len(STAGES),
        "missing_stages": [s for s in STAGES if s not in available],
        "mismatch_stage_count": mismatch_count,
        "status": overall,
        "complete_capture": assessed == len(STAGES),
        "stop_line_roadview_threshold": stop_line_threshold,
        "stop_line_verdict": report["stages"].get("before", {}).get(
            "stop_line_verdict", "REVIEW"
        ) or "REVIEW",
        "warning": (
            "건물/도로 후보와 색상 선형은 픽셀 기반 추정입니다. "
            "차로 수·화살표·유도선 등 검증되지 않은 특징은 null로 보존합니다. "
            "사진의 방향, 실제 연결 관계 및 최종 판정은 사용자가 확인해야 합니다."
        ),
    }
    check_stop()
    scores = assemble_score_record(
        case_id=case_id,
        model_name=model_name,
        stages=report["stages"],
        analyzed_at_utc=report["analyzed_at_utc"],
    )
    report["road_scores"] = scores
    _atomic_report(folder / "staged_analysis.json", report)
    check_stop()
    score_files = save_score_record(folder, scores)
    progress(
        f"교차로 스코어 {scores['available_scores']}/6개 저장 · "
        f"전체 CSV: {score_files['all_cases_csv']}"
    )
    progress(f"4단계 검수 결과 저장 완료: {assessed}/4단계 · {overall}")
    return {
        "kind": "staged_analysis", "folder": str(folder), "case_id": case_id,
        "stages": report["stages"], "summary": report["summary"],
        "road_scores": scores, "score_files": score_files,
    }
