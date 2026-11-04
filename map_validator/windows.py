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

def _intersection_number(value: str, kind: str) -> str | None:
    """Extract only a Polygon/Link identifier, not another number in the row."""
    match = re.search(rf"\b{kind}\s*[:#-]?\s*(\d+)\b", value, re.IGNORECASE)
    return match.group(1) if match else None


def _read_uia_intersection(window) -> str | None:
    """Read an accessible selected TreeItem without changing selection."""
    try:
        tree_items = [
            control for control in window.descendants()
            if control.element_info.control_type == "TreeItem"
        ]
    except Exception:
        return None

    def selected(control) -> bool:
        try:
            return bool(control.is_selected())
        except Exception:
            pass
        try:
            return bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:
            pass
        try:
            return bool(control.has_keyboard_focus())
        except Exception:
            return False

    selected_items = [item for item in tree_items if selected(item)]
    selected_polygon = next(
        (
            _intersection_number(item.window_text(), "Polygon")
            for item in selected_items
            if _intersection_number(item.window_text(), "Polygon") is not None
        ),
        None,
    )
    selected_link = next(
        (item for item in selected_items
         if _intersection_number(item.window_text(), "Link") is not None),
        None,
    )
    if selected_link is None:
        return f"Polygon {selected_polygon}" if selected_polygon else None

    link_id = _intersection_number(selected_link.window_text(), "Link")
    polygon_id = None
    try:
        parent = selected_link.parent()
        for _ in range(8):
            if parent is None:
                break
            polygon_id = _intersection_number(parent.window_text(), "Polygon")
            if polygon_id:
                break
            parent = parent.parent()
    except Exception:
        pass
    if not polygon_id:
        try:
            index = tree_items.index(selected_link)
            for item in reversed(tree_items[:index]):
                polygon_id = _intersection_number(item.window_text(), "Polygon")
                if polygon_id:
                    break
        except ValueError:
            pass
    return f"Polygon {polygon_id}- Link {link_id}" if polygon_id else None


def _read_win32_intersection(handle: int) -> str | None:
    """Fallback for native Win32 TreeView controls inside #32770 dialogs."""
    from pywinauto import Desktop

    try:
        window = Desktop(backend="win32").window(handle=handle).wrapper_object()
        controls = [window, *window.descendants()]
    except Exception:
        return None

    for tree in controls:
        try:
            if tree.class_name().casefold() != "systreeview32":
                continue
            roots = tree.roots()
        except Exception:
            continue

        # A tree node is not a native child window: inspect the Win32 TreeView
        # item's selection state, keeping its actual Polygon ancestor.
        stack = [(item, None) for item in reversed(roots)]
        inspected = 0
        last_polygon = None
        while stack and inspected < 3000:
            item, parent_polygon = stack.pop()
            inspected += 1
            try:
                label = item.text()
                polygon_id = _intersection_number(label, "Polygon")
                link_id = _intersection_number(label, "Link")
                selected = item.is_selected()
                children = item.children()
            except Exception:
                continue

            # The tree is walked in display order, so this also covers flat
            # trees where links have no native Polygon parent item.
            if polygon_id:
                last_polygon = polygon_id
            if selected and link_id:
                owner = parent_polygon or last_polygon
                if owner:
                    return f"Polygon {owner}- Link {link_id}"
            if selected and polygon_id:
                return f"Polygon {polygon_id}"
            child_owner = polygon_id or parent_polygon
            stack.extend((child, child_owner) for child in reversed(children))
    return None


def read_selected_intersection_id(title_keyword: str) -> str:
    """Return Polygon ID, with Link ID when a Link is selected.

    UIA window enumeration can omit native #32770 dialogs. Locate the same
    window by Win32 HWND if needed, and read either UIA TreeItems or a native
    SysTreeView32. No selection, clicks or config values are changed.
    """
    import pygetwindow as gw
    from pywinauto import Desktop

    configured_key = _comparable_title(title_keyword)
    if not configured_key:
        raise ValueError("Intersection review window title cannot be empty")

    uia_matches = []
    try:
        uia_matches = [
            window for window in Desktop(backend="uia").windows()
            if configured_key in _comparable_title(window.window_text())
        ]
    except Exception:
        pass

    # pygetwindow uses the Win32 window enumeration, which already detects
    # the user's '교차로 선형 검수' dialog (class #32770).
    win32_matches = []
    try:
        win32_matches = [
            window for window in gw.getAllWindows()
            if configured_key in _comparable_title(window.title)
        ]
    except Exception:
        pass

    handles = []
    for window in uia_matches:
        try:
            handle = int(window.handle)
            if handle and handle not in handles:
                handles.append(handle)
        except Exception:
            pass
    for window in win32_matches:
        handle = int(getattr(window, "_hWnd", 0) or 0)
        if handle and handle not in handles:
            handles.append(handle)

    if not handles and not uia_matches:
        raise RuntimeError(
            f"Intersection review window not found (UIA / Win32): {title_keyword!r}"
        )

    for window in uia_matches:
        result = _read_uia_intersection(window)
        if result:
            return result

    # A Win32-discovered HWND may still have a usable UIA tree even if
    # Desktop(backend='uia').windows() omitted the top-level dialog.
    for handle in handles:
        try:
            window = Desktop(backend="uia").window(handle=handle).wrapper_object()
            result = _read_uia_intersection(window)
            if result:
                return result
        except Exception:
            pass

    for handle in handles:
        result = _read_win32_intersection(handle)
        if result:
            return result

    raise RuntimeError(
        "Intersection review window found, but selected Polygon/Link could "
        "not be read via UIA or Win32. Check the selected tree item and "
        "whether the application exposes a SysTreeView32 control."
    )
