"""Roadview stop-line detection, only validated for approach-stage imagery."""
import numpy as np

from ..findings import unknown
from ...stop_line import detect_roadview_stop_line


def detect_stop_line(
    image: np.ndarray, road_mask: np.ndarray, overlay: np.ndarray,
    stage: str, threshold: float,
) -> dict:
    if stage != "before":
        return unknown("진출 도로 정지선의 진행 방향·ROI·횡단보도 분리 기준은 현장 사진 검증이 필요합니다.")
    return detect_roadview_stop_line(image, road_mask, overlay, threshold=threshold)
