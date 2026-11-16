"""Input-tool stop-line evidence; only the approach detector is validated."""
import numpy as np

from ..findings import unknown
from ...stop_line import detect_input_stop_line


def detect_stop_line(image: np.ndarray, overlay: np.ndarray, stage: str) -> dict:
    if stage != "before":
        return unknown("해당 진출 도로의 정지선 ROI·진입 주체가 아직 확인되지 않았습니다.")
    return detect_input_stop_line(image, overlay)
