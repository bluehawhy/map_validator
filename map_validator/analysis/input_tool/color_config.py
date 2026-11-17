"""Read the shared OpenCV HSV colour definitions for input-tool detectors."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


CONFIG_PATH = Path(__file__).with_name("color_ranges.json")


@lru_cache(maxsize=1)
def load_color_config() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("color_space") != "opencv_hsv":
        raise ValueError("지원하지 않는 색상 정의 JSON 형식입니다.")
    for name in ("white", "yellow", "green"):
        _bounds(data["colors"][name])
    _bounds(data["road_arrow"]["gray_background"])
    return data


def _bounds(spec: dict) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    lower = spec["hsv_lower"]
    upper = spec["hsv_upper"]
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError("HSV 범위는 세 개의 채널을 지정해야 합니다.")
    for channel, (lo, hi, maximum) in enumerate(zip(lower, upper, (179, 255, 255))):
        if not (isinstance(lo, int) and isinstance(hi, int)
                and 0 <= lo <= hi <= maximum):
            raise ValueError(f"HSV 채널 {channel}의 값 범위가 잘못됐습니다.")
    return tuple(lower), tuple(upper)


def hsv_mask(hsv: np.ndarray, name: str) -> np.ndarray:
    spec = load_color_config()["colors"][name]
    return cv2.inRange(hsv, *_bounds(spec))


def gray_background_mask(hsv: np.ndarray) -> np.ndarray:
    return cv2.inRange(
        hsv, *_bounds(load_color_config()["road_arrow"]["gray_background"])
    )
