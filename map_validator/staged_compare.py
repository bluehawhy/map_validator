"""Analyze manually captured four-stage photo pairs without controlling windows.

Comparison logic keeps expected map data, observed roadview evidence and
per-field uncertainty separate; no status constitutes an automatic approval.
"""
from __future__ import annotations

import json
import logging
import os
import time
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


APP_LOG = logging.getLogger("map_validator.staged_compare")


def _diag(value) -> str:
    """Stable, copyable single-line evidence for the UI and file log."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


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
    analysis_started = time.perf_counter()
    manifest = read_manifest(folder, case_id)
    APP_LOG.info(
        "분석 진단 시작 | 검수ID=%s | 모델=%s | 정지선기준=%.3f | 결과폴더=%s",
        case_id, model_name, stop_line_threshold, folder,
    )
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
        stage_started = time.perf_counter()
        record = manifest["stages"][stage]
        state = stage_status(folder, record)
        APP_LOG.info(
            "분석 진단 단계 | 단계=%s | 촬영상태=%s | 촬영버전=%s | 촬영시각=%s",
            STAGE_LABELS[stage], state, record.get("revision"),
            record.get("captured_at"),
        )
        if state != "captured":
            APP_LOG.warning(
                "분석 진단 촬영누락 | 단계=%s | 입력툴사진=%s | 로드뷰사진=%s",
                STAGE_LABELS[stage], record.get("work_image"), record.get("roadview_image"),
            )
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
        APP_LOG.info(
            "분석 진단 원본 | 단계=%s | 입력툴=%s (%dx%d) | 로드뷰=%s (%dx%d)",
            STAGE_LABELS[stage], input_path.name,
            input_image.shape[1], input_image.shape[0], road_path.name,
            road_image.shape[1], road_image.shape[0],
        )
        input_expected, input_overlay, route = extract_input_features(input_image, stage)
        if stage != "before":
            APP_LOG.info(
                "분석 진단 입력경로 | 단계=%s | 경로상태=%s | 추정방향=%s | 회전각=%s"
                " | 색상선개수=%s | 연결간격=%s | 후보중복=%s | 보류사유=%s",
                STAGE_LABELS[stage], route.get("status"),
                route.get("expected_turn"), route.get("turn_angle_deg"),
                _diag(route.get("component_counts")),
                _diag(route.get("join_gaps_px")),
                route.get("ambiguous_path_choices"), route.get("reason", "없음"),
            )
        check_stop()
        masks = segmenter.class_masks(road_image)
        # One segmentation pass supplies BOTH the qualitative detector and
        # the six-number, future-comparable road-pixel score dataset.
        score_observation = score_road_mask(masks["road"])
        roadview_observed, road_overlay, evidence = extract_roadview_features(
            road_image, stage, masks, stop_line_threshold=stop_line_threshold
        )
        APP_LOG.info(
            "분석 진단 도로마스크 | 단계=%s | 도로비율=%s | 건물비율=%s"
            " | ROI도로점수=%s | ROI픽셀수=%s",
            STAGE_LABELS[stage], evidence.get("road_ratio"),
            evidence.get("building_ratio"), _diag(score_observation["scores"]),
            _diag(score_observation["pixels"]),
        )
        if stage == "before":
            expected_stop = input_expected["stop_line"]
            observed_stop = roadview_observed["stop_line"]
            APP_LOG.info(
                "분석 진단 정지선 | 입력툴값=%s | 입력툴후보점수=%s"
                " | 입력툴방법=%s | 입력툴근거=%s | 입력툴사유=%s"
                " | 로드뷰값=%s | 로드뷰후보점수=%s | 로드뷰방법=%s"
                " | 로드뷰근거=%s | 로드뷰사유=%s",
                expected_stop.get("value"), expected_stop.get("confidence"),
                expected_stop.get("method"), _diag(expected_stop.get("evidence")),
                expected_stop.get("reason"), observed_stop.get("value"),
                observed_stop.get("confidence"), observed_stop.get("method"),
                _diag(observed_stop.get("evidence")), observed_stop.get("reason"),
            )
        else:
            presence = roadview_observed.get("road_exists", {})
            APP_LOG.info(
                "분석 진단 도로존재 | 단계=%s | 판별값=%s | 후보점수=%s"
                " | 검출방법=%s | 전방ROI=%s | 비율=%s | 기준=도로>=0.24"
                " 또는 (건물>=0.46, 도로<0.055) | 보류사유=%s",
                STAGE_LABELS[stage], presence.get("value"),
                presence.get("confidence"), presence.get("method"),
                _diag(presence.get("roi")), _diag(presence.get("evidence_scores")),
                presence.get("reason"),
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
        for field, item in compare.items():
            expected_feature = input_expected[field]
            observed_feature = roadview_observed[field]
            APP_LOG.info(
                "분석 진단 항목 | 단계=%s | 항목=%s | 기대값=%s"
                " | 관측값=%s | 결과=%s | P/F/N근거=%s"
                " | 기대방법=%s | 기대후보점수=%s | 관측방법=%s"
                " | 관측후보점수=%s | 기대보류사유=%s | 관측보류사유=%s",
                STAGE_LABELS[stage], FIELD_LABELS[field],
                _diag(item.get("expected_value")), _diag(item.get("observed_value")),
                item.get("status"), item.get("reason"),
                expected_feature.get("method"), expected_feature.get("confidence"),
                observed_feature.get("method"), observed_feature.get("confidence"),
                expected_feature.get("reason"), observed_feature.get("reason"),
            )
        APP_LOG.info(
            "분석 진단 단계완료 | 단계=%s | 결과=%s | 소요=%.2f초",
            STAGE_LABELS[stage], stage_result, time.perf_counter() - stage_started,
        )

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
    APP_LOG.info(
        "분석 진단 종합 | 검수ID=%s | 판정=%s | 촬영완료=%d/%d"
        " | 불일치의심단계=%d | 정지선판정=%s | 총분석시간=%.2f초"
        " | 주의=후보점수는 확률이 아니며 최종 판정은 사람 검수 필요",
        case_id, overall, assessed, len(STAGES), mismatch_count,
        report["summary"]["stop_line_verdict"], time.perf_counter() - analysis_started,
    )
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
