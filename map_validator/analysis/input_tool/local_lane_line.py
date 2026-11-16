"""White lane-line candidates using the centre-line geometry and grouping.

Candidates are visual inspection aids, not verified lane boundaries or counts.
"""
from __future__ import annotations

import numpy as np

from .local_center_line import _detect_axis_line_candidates


def local_lane_line_candidates(
    image: np.ndarray, point: list[float] | None, overlay: np.ndarray,
    *, roi: list[int] | None,
) -> dict:
    return _detect_axis_line_candidates(image, point, overlay, roi=roi, lane=True)
