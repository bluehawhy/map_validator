"""Colored guidance markings; map route colors are not painted guidance."""
from ..findings import unknown


def detect_colored_guidance() -> dict:
    return unknown("입력툴 경로색(시안/주황/파랑)과 실제 컬러유도선 표시는 다른 개념입니다.")
