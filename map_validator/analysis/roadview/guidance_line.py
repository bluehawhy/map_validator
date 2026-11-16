"""Ordinary guidance lines are distinct from lane boundary paint."""
from ..findings import unknown


def detect_guidance_line() -> dict:
    return unknown("일반 유도선과 차로 경계선 구분 기준이 아직 검증되지 않았습니다.")
