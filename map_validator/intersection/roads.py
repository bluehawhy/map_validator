"""Expandable road records without direction-specific code or guessed angles.

The existing UI still captures four legacy stages. Those stage names are an
optional evidence reference, not road identity or an orientation measurement.
"""
from __future__ import annotations

from ..stage_types import STAGES, fields_for_stage


def road_record(
    road_id: str, role: str, *, angle_deg: float | None = None,
    checks: tuple[str, ...] | list[str] = (), source_stage: str | None = None,
) -> dict:
    """Make a transportable per-road record; 0 degrees is image-up, clockwise.

    Angle None explicitly means not measured. All road counts are supported.
    """
    if not road_id or not isinstance(road_id, str):
        raise ValueError("도로 ID가 필요합니다.")
    if role not in ("entry", "exit", "unknown"):
        raise ValueError("도로 역할이 올바르지 않습니다.")
    if angle_deg is not None and not (0 <= angle_deg < 360):
        raise ValueError("각도는 0 이상 360 미만이어야 합니다.")
    return {
        "road_id": road_id,
        "angle_deg": angle_deg,
        "angle_reference": "image_top_clockwise",
        "role": role,
        "checks": list(checks),
        "source_stage": source_stage,
    }


def legacy_stage_road(stage: str) -> dict:
    """Temporary mapping for historical four-photo capture, not road detection."""
    if stage not in STAGES:
        raise ValueError(f"지원하지 않는 촬영 단계: {stage}")
    number = STAGES.index(stage) + 1
    return road_record(
        f"road_{number:03d}", "entry" if stage == "before" else "exit",
        checks=fields_for_stage(stage), source_stage=stage,
    )
