"""Input-tool lane-count evidence, separated from road geometry."""
from ..findings import unknown


def detect_lane_count(stage: str) -> dict:
    if stage == "before":
        return unknown("진입 차로 수는 도로 경계선·차로 구분 데이터를 확보하기 전까지 임의 산출하지 않습니다.")
    return unknown("선형 경로 한 개로 실제 해당 방향 진출 차로 수를 계산할 수 없습니다.")
