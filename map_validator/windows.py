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


def scroll_to_bottom(window) -> None:
    """Move a browser-like roadview viewport to its bottom without mouse-wheel zoom."""
    activate(window)
    pyautogui.hotkey("ctrl", "end")
    time.sleep(0.4)


def set_zoom_value(window, value: int) -> None:
    """Set the numeric edit nearest a UI Automation element containing 'zoom'."""
    from pywinauto import Desktop

    if not 1 <= int(value) <= 500:
        raise ValueError("zoom value must be between 1 and 500")

    title = window.title.strip()
    candidates = Desktop(backend="uia").windows(title=title)
    if not candidates:
        raise RuntimeError(f"UI Automation window not found: {title}")

    target = candidates[0]
    controls = target.descendants()
    zoom_labels = [
        control for control in controls
        if "zoom" in control.window_text().casefold()
    ]
    edits = [
        control for control in controls
        if control.element_info.control_type in {"Edit", "Spinner"}
    ]
    if not zoom_labels:
        raise RuntimeError("zoom label was not exposed through Windows UI Automation")
    if not edits:
        raise RuntimeError("zoom numeric input was not exposed through Windows UI Automation")

    label_rect = zoom_labels[0].rectangle()

    def distance(control) -> tuple[int, int]:
        rect = control.rectangle()
        vertical = abs((rect.top + rect.bottom) - (label_rect.top + label_rect.bottom))
        right_side_penalty = 0 if rect.left >= label_rect.left else 10000
        return vertical + right_side_penalty, abs(rect.left - label_rect.right)

    zoom_input = min(edits, key=distance)
    try:
        zoom_input.set_edit_text(str(int(value)))
    except Exception:
        zoom_input.click_input()
        zoom_input.type_keys("^a" + str(int(value)) + "{ENTER}", set_foreground=False)
    else:
        zoom_input.type_keys("{ENTER}", set_foreground=False)
    time.sleep(0.3)
