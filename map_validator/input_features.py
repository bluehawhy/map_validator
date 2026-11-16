"""Compatibility API: expected values now live under analysis.input_tool.

Keep this module for callers that still import extract_input_features.
"""
from __future__ import annotations

import numpy as np

from .analysis.findings import candidate, unknown
from .analysis.input_tool.features import extract_input_tool_features


def extract_input_features(image: np.ndarray, stage: str) -> tuple[dict, np.ndarray, dict]:
    return extract_input_tool_features(image, stage)
