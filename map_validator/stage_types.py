"""Four manually captured intersection stages and their review fields."""
from __future__ import annotations

import re

STAGES = ("before", "after_left", "after_straight", "after_right")
STAGE_LABELS = {
    "before": "교차로 진입 전",
    "after_left": "진입 후 · 좌",
    "after_straight": "진입 후 · 직",
    "after_right": "진입 후 · 우",
}
STAGE_BUTTONS = {
    "before": "진입 전 촬영",
    "after_left": "진입 후 · 좌 촬영",
    "after_straight": "진입 후 · 직 촬영",
    "after_right": "진입 후 · 우 촬영",
}
BEFORE_FIELDS = ("stop_line", "entry_lane_count", "lane_arrows", "colored_guidance")
AFTER_FIELDS = ("road_exists", "exit_lane_count", "guidance_line", "colored_guidance")
FIELD_LABELS = {
    "stop_line": "정지선",
    "entry_lane_count": "진입 차로 수",
    "lane_arrows": "차로별 화살표",
    "colored_guidance": "컬러유도선",
    "road_exists": "도로 존재",
    "exit_lane_count": "진출 차로 수",
    "guidance_line": "일반 유도선",
}


def validate_stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(f"지원하지 않는 촬영 단계: {stage}")
    return stage


def validate_case_id(case_id: str) -> str:
    case_id = case_id.strip()
    if not case_id or not re.fullmatch(r"[A-Za-z0-9 _-]+", case_id):
        raise ValueError("검수 ID는 영문/숫자/공백/-/_만 사용할 수 있습니다.")
    if case_id in {".", ".."}:
        raise ValueError("올바르지 않은 검수 ID입니다.")
    return case_id


def fields_for_stage(stage: str) -> tuple[str, ...]:
    return BEFORE_FIELDS if validate_stage(stage) == "before" else AFTER_FIELDS
