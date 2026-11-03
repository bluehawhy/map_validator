"""Window-safe capture and keyboard control. Windows only."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15


def find_window(title_keyword: str):
    if not title_keyword.strip():
        raise ValueError("Window title keyword cannot be empty")
    windows = [w for w in gw.getAllWindows() if title_keyword.casefold() in w.title.casefold()]
    windows = [w for w in windows if w.width > 150 and w.height > 150]
    if not windows:
        raise RuntimeError(f"Window not found: {title_keyword!r}")
    return windows[0]


def activate(window) -> None:
    if window.isMinimized:
        window.restore()
    window.activate()
    time.sleep(0.4)


def capture_window(window, region: list[int] | None = None) -> np.ndarray:
    """Returns BGR pixels. Window must be visible and not occluded."""
    activate(window)
    left, top = int(window.left), int(window.top)
    width, height = int(window.width), int(window.height)
    if region is not None:
        if len(region) != 4:
            raise ValueError("capture.region must be [left, top, width, height]")
        dx, dy, rw, rh = (int(x) for x in region)
        left, top = left + dx, top + dy
        width, height = rw, rh
    if width <= 0 or height <= 0:
        raise ValueError("Capture region has non-positive size")
    with mss.mss() as screenshot:
        raw = np.array(screenshot.grab({"left": left, "top": top, "width": width, "height": height}))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def move_roadview(window, key: str, duration_seconds: float) -> None:
    """Only sends the configured key after activating the identified roadview."""
    activate(window)
    if key.lower() not in {"w", "s"}:
        raise ValueError("Only W/S movement is allowed")
    try:
        pyautogui.keyDown(key)
        time.sleep(max(0.05, min(duration_seconds, 2.0)))
    finally:
        pyautogui.keyUp(key)


def click_template_in_window(window, template_path: str, threshold: float = 0.88) -> bool:
    """Clicks a matched template in the visible window; false if no safe match."""
    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"Template image missing: {path}")
    image = capture_window(window)
    template = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if template is None:
        raise ValueError(f"Cannot decode template: {path}")
    ih, iw = image.shape[:2]
    th, tw = template.shape[:2]
    if tw > iw or th > ih:
        return False
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (px, py) = cv2.minMaxLoc(scores)
    if score < threshold:
        return False
    pyautogui.click(int(window.left) + px + tw // 2, int(window.top) + py + th // 2)
    return True
