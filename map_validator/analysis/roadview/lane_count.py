"""Roadview lane counts remain unknown until direction-specific validation."""
from ..findings import unknown


def detect_lane_count(stage: str) -> dict:
    if stage == "before":
        return unknown("SegFormer 도로 영역만으로 차로 경계 개수를 판정하지 않습니다.")
    return unknown("촬영 시점에 따라 양방향 차로가 섞일 수 있어 진출 차로 수를 확정하지 않습니다.")
