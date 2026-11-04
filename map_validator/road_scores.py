"""Comparable road-mask scores for the four manually captured viewpoints.

Scores are the fraction of semantic ROAD pixels in equal-sized, fixed
camera-frame regions of interest (ROI); they are NOT turn permissions,
lane counts or calibrated 3D geometry. All six values use the same model,
vertical crop and ROI area, so they can be studied later.

before: L / straight / R regions of one approach screenshot.
after: the straight-ahead region of each left / straight / right screenshot.
"""
from __future__ import annotations

import csv
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SCORE_VERSION = "road_mask_roi_v1"
REGIONS_X = {
    "left": (0.04, 0.34),
    "straight": (0.35, 0.65),
    "right": (0.66, 0.96),
}
VERTICAL_RANGE = (0.28, 0.60)
CSV_FIELDS = [
    "case_id", "polygon_id", "link_id", "analyzed_at_utc",
    "score_version", "model_name",
    "before_left_score", "before_straight_score", "before_right_score",
    "after_left_straight_score", "after_straight_straight_score",
    "after_right_straight_score",
    "left_delta", "straight_delta", "right_delta",
    "before_revision", "after_left_revision", "after_straight_revision",
    "after_right_revision", "available_scores", "missing_scores",
]


def score_road_mask(
    mask: np.ndarray, vertical_range: tuple[float, float] = VERTICAL_RANGE,
) -> dict[str, Any]:
    """Normalized ROAD pixel ratios for left / straight / right visual ROIs."""
    if mask.ndim != 2:
        raise ValueError("도로 점수 계산에는 2D 세그멘테이션 마스크가 필요합니다.")
    h, w = mask.shape
    if h < 64 or w < 64:
        raise ValueError("도로 점수 계산에는 64x64 이상의 로드뷰 이미지가 필요합니다.")
    y0, y1 = (int(h * y) for y in vertical_range)
    if not (0 <= y0 < y1 <= h):
        raise ValueError("도로 점수 계산 ROI 높이 범위가 잘못됐습니다.")

    scores: dict[str, float] = {}
    pixel_counts: dict[str, dict[str, int]] = {}
    for direction, (left, right) in REGIONS_X.items():
        x0, x1 = int(w * left), int(w * right)
        roi = mask[y0:y1, x0:x1]
        if roi.size == 0:
            raise ValueError(f"{direction} ROI 픽셀 영역이 비었습니다.")
        road_pixels = int(np.count_nonzero(roi))
        scores[direction] = round(road_pixels / int(roi.size), 6)
        pixel_counts[direction] = {
            "road_pixels": road_pixels,
            "total_pixels": int(roi.size),
        }
    return {
        "scores": scores,
        "pixels": pixel_counts,
        "vertical_range": [float(vertical_range[0]), float(vertical_range[1])],
        "horizontal_regions": {
            name: [float(v[0]), float(v[1])] for name, v in REGIONS_X.items()
        },
        "method": SCORE_VERSION,
    }


def _parse_ids(case_id: str) -> tuple[str | None, str | None]:
    match = re.fullmatch(
        r"Polygon\s+(\d+)(?:\s*-\s*Link\s+(\d+))?",
        case_id.strip(), re.IGNORECASE,
    )
    if not match:
        return None, None
    return match.group(1), match.group(2)


def assemble_score_record(
    case_id: str, model_name: str, stages: dict[str, dict],
    analyzed_at_utc: str,
) -> dict[str, Any]:
    """Map exactly six stage/ROI readings to future comparable named fields."""
    polygon_id, link_id = _parse_ids(case_id)
    before = stages.get("before", {}).get("roadview_scores", {})
    after = {
        direction: stages.get(f"after_{direction}", {}).get(
            "roadview_scores", {}
        ).get("straight")
        for direction in ("left", "straight", "right")
    }
    approach = {
        direction: before.get(direction)
        for direction in ("left", "straight", "right")
    }
    comparison = {
        direction: (
            round(after[direction] - approach[direction], 6)
            if after[direction] is not None and approach[direction] is not None
            else None
        )
        for direction in ("left", "straight", "right")
    }
    expected_keys = (
        "before_left", "before_straight", "before_right",
        "after_left_straight", "after_straight_straight", "after_right_straight"
    )
    flat = {
        "before_left": approach["left"],
        "before_straight": approach["straight"],
        "before_right": approach["right"],
        "after_left_straight": after["left"],
        "after_straight_straight": after["straight"],
        "after_right_straight": after["right"],
    }
    return {
        "schema_version": 1,
        "case_id": case_id,
        "polygon_id": polygon_id,
        "link_id": link_id,
        "analyzed_at_utc": analyzed_at_utc,
        "score_method": SCORE_VERSION,
        "model_name": model_name,
        "score_units": "road_pixel_fraction_0_to_1",
        "vertical_range": list(VERTICAL_RANGE),
        "horizontal_regions": {
            key: list(value) for key, value in REGIONS_X.items()
        },
        "before": approach,
        "after": {
            "left": {"straight_score": after["left"]},
            "straight": {"straight_score": after["straight"]},
            "right": {"straight_score": after["right"]},
        },
        "delta_after_minus_before": comparison,
        "stage_revisions": {
            key: stages.get(key, {}).get("revision")
            for key in ("before", "after_left", "after_straight", "after_right")
        },
        "available_scores": sum(flat[key] is not None for key in expected_keys),
        "missing_scores": [key for key in expected_keys if flat[key] is None],
        "evidence_images": {
            key: stages.get(key, {}).get("evidence", {}).get("roadview_image")
            for key in ("before", "after_left", "after_straight", "after_right")
        },
        "warning": (
            "도로 SegFormer 마스크의 ROI 내 픽셀 비율이며 진짜 도로 존재 확률이나 "
            "차로 수가 아닙니다. before/after 사진은 시점이 다르므로 점수 차이만으로 "
            "불일치를 확정하지 않고 원본과 함께 비교해야 합니다."
        ),
    }


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _csv_row(record: dict) -> dict[str, str | int | float | None]:
    a, b = record["before"], record["after"]
    d = record["delta_after_minus_before"]
    revisions = record["stage_revisions"]
    return {
        "case_id": record["case_id"],
        "polygon_id": record["polygon_id"],
        "link_id": record["link_id"],
        "analyzed_at_utc": record["analyzed_at_utc"],
        "score_version": record["score_method"],
        "model_name": record["model_name"],
        "before_left_score": a["left"],
        "before_straight_score": a["straight"],
        "before_right_score": a["right"],
        "after_left_straight_score": b["left"]["straight_score"],
        "after_straight_straight_score": b["straight"]["straight_score"],
        "after_right_straight_score": b["right"]["straight_score"],
        "left_delta": d["left"],
        "straight_delta": d["straight"],
        "right_delta": d["right"],
        "before_revision": revisions["before"],
        "after_left_revision": revisions["after_left"],
        "after_straight_revision": revisions["after_straight"],
        "after_right_revision": revisions["after_right"],
        "available_scores": record["available_scores"],
        "missing_scores": ";".join(record["missing_scores"]),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_score_record(folder: Path, record: dict) -> dict[str, str]:
    """Save per-case JSON, per-run history, and root-level latest CSV.

    The CSV is only a convenient materialized view; per-run JSON archives are
    the durable measurement history. Re-running analysis on identical photos
    creates a new timestamped record with image revisions for traceability.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"검수 폴더가 없습니다: {folder}")

    output_root = folder.parent
    history_folder = folder / "score_history"
    history_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    history_path = history_folder / f"road_scores_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    current_path = folder / "road_scores.json"
    csv_path = output_root / "road_scores.csv"
    row = _csv_row(record)

    # Preserve the previous and current raw measurements in immutable history.
    _atomic_json(history_path, record)
    _atomic_json(current_path, record)

    # Update one current row per case, while preserving rows for other IDs.
    rows: dict[str, dict] = {}
    if csv_path.is_file():
        with csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != CSV_FIELDS:
                raise ValueError(
                    "기존 road_scores.csv 열 구조가 다릅니다. 기존 파일은 변경하지 "
                    "않았으므로 백업 후 새 파일로 분리하거나 구조를 확인하세요."
                )
            for existing in reader:
                key = (existing.get("case_id") or "").strip()
                if key:
                    rows[key] = existing
    rows[record["case_id"]] = row
    _write_csv(csv_path, [rows[key] for key in sorted(rows)])
    return {
        "case_json": str(current_path),
        "history_json": str(history_path),
        "all_cases_csv": str(csv_path),
    }
