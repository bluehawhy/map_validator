"""Input-tool lane-by-lane painted arrow evidence."""
from ..findings import unknown


def detect_lane_arrows() -> dict:
    return unknown("방향 화살표/복합 화살표 모델 및 차로별 대응 정보가 아직 검증되지 않았습니다.")
