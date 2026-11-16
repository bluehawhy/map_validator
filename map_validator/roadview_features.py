"""Compatibility API: observed values now live under analysis.roadview."""
from __future__ import annotations

import numpy as np

from .analysis.roadview.colored_guidance import detect_colored_guidance as _painted_color_candidate
from .analysis.roadview.road_presence import detect_road_presence as _forward_presence
from .analysis.roadview.features import extract_roadview_features as _extract


def extract_roadview_features(
    image: np.ndarray, stage: str, masks: dict[str, np.ndarray],
    stop_line_threshold: float = .68,
) -> tuple[dict, np.ndarray, dict]:
    return _extract(image, stage, masks, stop_line_threshold=stop_line_threshold)
