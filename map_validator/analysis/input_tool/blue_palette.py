"""Fixed four-colour blue-marking palette shared by S/G, U and P detectors.

OpenCV images are BGR, palette values are explicitly RGB. Pixel masks are
exact by default to avoid mixing cyan stop marks with guide or approach lines.
Pure blue intersection outlines are excluded from candidate masks, not erased
from the WGC source.
"""
from __future__ import annotations

import cv2
import numpy as np

from .color_config import load_color_config


def blue_palette() -> dict:
    return load_color_config()["blue_markings"]


def blue_color_mask(image: np.ndarray, name: str) -> np.ndarray:
    palette = blue_palette()
    rgb = palette["colors"][name]["rgb"]
    tolerance = int(palette["tolerance_per_channel"])
    if len(rgb) != 3 or not 0 <= tolerance <= 40:
        raise ValueError("파란색 RGB 정의/채널 오차 설정이 잘못되었습니다.")
    values = np.asarray(rgb, dtype=np.int16)
    lower = np.clip(values - tolerance, 0, 255).astype(np.uint8)[::-1]
    upper = np.clip(values + tolerance, 0, 255).astype(np.uint8)[::-1]
    mask = cv2.inRange(image, lower, upper)
    if name != "intersection_outline":
        excluded = cv2.inRange(
            image, np.array([255, 0, 0], dtype=np.uint8),
            np.array([255, 0, 0], dtype=np.uint8),
        )
        # The intersection outline itself is RGB(0,0,255) = BGR(255,0,0).
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(excluded))
    return mask
