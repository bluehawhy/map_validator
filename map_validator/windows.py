"""Window-safe capture and keyboard control. Windows only."""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15


def _program_title(window_title: str) -> str:
    title = window_title.strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    return title


def _comparable_title(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def find_window(title_keyword: str):
    configured = _program_title(title_keyword)
    if not configured:
        raise ValueError("Window title keyword cannot be empty")

    configured_key = _comparable_title(configured)
    windows = [window for window in gw.getAllWindows() if window.title.strip()]
    matches = [
        window for window in windows
        if configured.casefold() in window.title.casefold()
        or configured_key == _comparable_title(_program_title(window.title))
        or configured_key in _comparable_title(window.title)
    ]
    if not matches:
        detected = ", ".join(window.title.strip() for window in windows[:8])
        detail = f"; detected windows: {detected}" if detected else "; no windows detected"
        raise RuntimeError(f"Window not found: {configured!r}{detail}")

    return next(
        (
            window for window in matches
            if window.width > 150 and window.height > 150
        ),
        matches[0],
    )


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
    """Reach the requested zoom by scrolling over the zoom number and reading changes."""
    from pywinauto import Desktop

    requested = int(value)
    if not 1 <= requested <= 500:
        raise ValueError("zoom value must be between 1 and 500")

    activate(window)
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
    if not zoom_labels:
        raise RuntimeError("zoom label was not exposed through Windows UI Automation")

    label = zoom_labels[0]
    label_rect = label.rectangle()

    def numeric_value(control) -> int | None:
        texts: list[str] = []
        try:
            texts.append(control.window_text())
        except Exception:
            pass
        try:
            texts.extend(control.texts())
        except Exception:
            pass
        try:
            texts.append(str(control.get_value()))
        except Exception:
            pass
        for text in texts:
            numbers = re.findall(r"(?<![A-Za-z])\d{1,3}(?![A-Za-z])", str(text))
            if numbers:
                return int(numbers[-1])
        return None

    same_row = []
    label_center_y = (label_rect.top + label_rect.bottom) // 2
    for control in controls:
        try:
            rect = control.rectangle()
        except Exception:
            continue
        center_y = (rect.top + rect.bottom) // 2
        if abs(center_y - label_center_y) <= max(20, label_rect.height()):
            number = numeric_value(control)
            if number is not None:
                same_row.append((control, number))

    label_number = numeric_value(label)
    if label_number is not None:
        same_row.append((label, label_number))
    if not same_row:
        raise RuntimeError("zoom number was not exposed through Windows UI Automation")

    def candidate_score(item) -> tuple[int, int]:
        control, _ = item
        rect = control.rectangle()
        right_penalty = 0 if rect.left >= label_rect.left else 10000
        return right_penalty + abs(rect.top - label_rect.top), abs(rect.left - label_rect.right)

    zoom_control, current = min(same_row, key=candidate_score)
    rect = zoom_control.rectangle()
    x = (rect.left + rect.right) // 2
    y = (rect.top + rect.bottom) // 2
    pyautogui.moveTo(x, y, duration=0.15)

    def read_current() -> int:
        result = numeric_value(zoom_control)
        if result is None:
            raise RuntimeError("zoom number could not be read after scrolling")
        return result

    if current == requested:
        return

    pyautogui.scroll(1)
    time.sleep(0.15)
    after_up = read_current()
    if after_up != current:
        increase_scroll = 1 if after_up > current else -1
        current = after_up
    else:
        pyautogui.scroll(-1)
        time.sleep(0.15)
        after_down = read_current()
        if after_down == current:
            raise RuntimeError("zoom value did not change when the mouse wheel was scrolled")
        increase_scroll = -1 if after_down > current else 1
        current = after_down

    for _ in range(250):
        if current == requested:
            return
        direction = increase_scroll if requested > current else -increase_scroll
        pyautogui.scroll(direction)
        time.sleep(0.08)
        updated = read_current()
        if updated == current:
            raise RuntimeError(f"zoom stopped changing at {current}; target is {requested}")
        current = updated

    raise RuntimeError(f"zoom could not reach {requested}; last value was {current}")

