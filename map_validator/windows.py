"""Window-safe capture and keyboard control. Windows only."""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
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


def activate(window, *, allow_restore: bool = True) -> None:
    """Focus a window without moving or resizing it.

    Some HD_3D Tool views become blank when restored/relaid out. Work-tool
    callers pass allow_restore=False so only a human can restore that window.
    """
    if window.isMinimized:
        if not allow_restore:
            raise RuntimeError(
                "입력도구가 최소화되어 있습니다. 창 위치/크기 보호를 위해 "
                "자동 복원하지 않습니다. 직접 복원한 뒤 다시 실행하세요."
            )
        window.restore()
    window.activate()
    time.sleep(0.4)


def capture_window(window, region: list[int] | None = None) -> np.ndarray:
    """Read HWND pixels using the shared Windows Graphics Capture backend."""
    from .wgc_capture import capture_window_wgc

    return capture_window_wgc(window, region)


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
    # The template click still requires the work app to be foreground;
    # passive window capture by itself must not steal focus.
    activate(window, allow_restore=False)
    # Shared WGC capture avoids PrintWindow, which can blank the 3D viewport.
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

    # HD_3D Tool must not be restored, resized, or moved automatically.
    activate(window, allow_restore=False)
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
    """Extract a Polygon or a directional Link, never an unrelated row count.

    The updated review tool names Link items like 'Link 888_정' or 'Link 443_역'.
    Both '_' and Hangul are regex word characters; the old digit+word-boundary
    expression failed on these labels and triggered slow fallback searches.
    Keep the direction in the identity to distinguish the two link variants.
    """
    if kind.casefold() == "link":
        match = re.search(
            r"\bLink\s*[:#-]?\s*(\d+)"
            r"(?:\s*[_-]\s*(정방향|역방향|정|역))?(?!\w)",
            value, re.IGNORECASE,
        )
        if not match:
            return None
        direction = match.group(2)
        return f"{match.group(1)}_{direction[0]}" if direction else match.group(1)

    match = re.search(r"\bPolygon\s*[:#-]?\s*(\d+)(?!\w)", value, re.IGNORECASE)
    return match.group(1) if match else None


# Selection lookup handles are reused only while their owning windows exist.
_SELECTION_WINDOW_CACHE: dict[str, int] = {}
_SELECTION_TREE_CACHE: dict[int, list[int]] = {}


def _read_uia_intersection(window, diagnostic=None) -> str | None:
    """Read the Selection provider on Tree controls, not all UIA TreeItems."""
    from pywinauto.controls.uiawrapper import UIAWrapper

    try:
        trees = window.descendants(control_type="Tree")
    except Exception as exc:
        if diagnostic:
            diagnostic(f"UIA Tree 컨트롤 조회 실패: {type(exc).__name__}: {exc}")
        return None
    if diagnostic:
        diagnostic(f"UIA Tree 컨트롤={len(trees)}개 (항목 전체 순회 안 함)")

    for tree in trees:
        try:
            selections = tree.get_selection()
        except Exception as exc:
            if diagnostic:
                diagnostic(f"UIA 선택 공급자 미지원: {type(exc).__name__}")
            continue
        for selected_element in selections:
            try:
                selected = UIAWrapper(selected_element)
                label = selected.window_text()
                polygon = _intersection_number(label, "Polygon")
                link = _intersection_number(label, "Link")
                if polygon:
                    return f"Polygon {polygon}"
                if link:
                    parent = selected.parent()
                    for _ in range(12):
                        if parent is None:
                            break
                        polygon = _intersection_number(parent.window_text(), "Polygon")
                        if polygon:
                            return f"Polygon {polygon}- Link {link}"
                        parent = parent.parent()
            except Exception as exc:
                if diagnostic:
                    diagnostic(f"UIA 선택 항목 읽기 실패: {type(exc).__name__}: {exc}")
    if diagnostic:
        diagnostic("UIA 선택 공급자에서 유효한 Polygon/Link 선택을 찾지 못함")
    return None


def _read_win32_intersection(handle: int, diagnostic=None) -> str | None:
    """Directly read TVGN_CARET and its Polygon ancestry; never scan all nodes."""
    from pywinauto import Desktop, win32defines
    from pywinauto.controls.common_controls import _treeview_element

    desktop = Desktop(backend="win32")
    try:
        window = desktop.window(handle=handle).wrapper_object()
    except Exception as exc:
        if diagnostic:
            diagnostic(f"Win32 창 연결 실패: {type(exc).__name__}: {exc}")
        _SELECTION_TREE_CACHE.pop(handle, None)
        return None

    def selected_from_tree(tree) -> str | None:
        try:
            chosen = tree.send_message(
                win32defines.TVM_GETNEXTITEM, win32defines.TVGN_CARET, 0
            )
            if not chosen:
                return None
            item = _treeview_element(chosen, tree)
            label = item.text()
            polygon = _intersection_number(label, "Polygon")
            if polygon:
                return f"Polygon {polygon}"
            link = _intersection_number(label, "Link")
            if not link:
                return None

            # Prefer the actual native parent chain rather than assuming the
            # preceding visual row belongs to the same Polygon.
            current = chosen
            for _ in range(12):
                current = tree.send_message(
                    win32defines.TVM_GETNEXTITEM, win32defines.TVGN_PARENT,
                    current,
                )
                if not current:
                    break
                polygon = _intersection_number(
                    _treeview_element(current, tree).text(), "Polygon"
                )
                if polygon:
                    return f"Polygon {polygon}- Link {link}"

            # Some review controls use a flat list rather than native parents.
            # Walk only neighbouring previous siblings (bounded), not 3000
            # nodes, and never return a Link without its Polygon.
            current = chosen
            for _ in range(64):
                current = tree.send_message(
                    win32defines.TVM_GETNEXTITEM, win32defines.TVGN_PREVIOUS,
                    current,
                )
                if not current:
                    break
                polygon = _intersection_number(
                    _treeview_element(current, tree).text(), "Polygon"
                )
                if polygon:
                    return f"Polygon {polygon}- Link {link}"
            if diagnostic:
                diagnostic(f"Win32 선택 Link {link}: 상위 Polygon 확인 실패")
        except Exception as exc:
            if diagnostic:
                diagnostic(f"Win32 직접 선택 조회 예외: {type(exc).__name__}: {exc}")
        return None

    # Revalidate cached tree HWNDs against the parent HWND on every read.
    # A recreated dialog may reuse a numeric HWND but not its child handles.
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_bool
    user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.IsChild.restype = ctypes.c_bool
    cached = [
        child for child in _SELECTION_TREE_CACHE.get(handle, [])
        if user32.IsWindow(child) and user32.IsChild(handle, child)
    ]
    for child in cached:
        try:
            tree = desktop.window(handle=child).wrapper_object()
            if tree.class_name().casefold() != "systreeview32":
                continue
            result = selected_from_tree(tree)
            if result:
                if diagnostic:
                    diagnostic("Win32 캐시 TreeView 현재 선택 직접 조회 성공")
                return result
        except Exception:
            pass

    try:
        controls = [window, *window.descendants()]
        tree_controls = [
            tree for tree in controls
            if tree.class_name().casefold() == "systreeview32"
        ]
    except Exception as exc:
        if diagnostic:
            diagnostic(f"Win32 TreeView 목록 조회 실패: {type(exc).__name__}: {exc}")
        return None
    _SELECTION_TREE_CACHE[handle] = [int(tree.handle) for tree in tree_controls]
    if diagnostic:
        diagnostic(f"Win32 TreeView={len(tree_controls)}개 (TVGN_CARET 직접 조회)")
    for tree in tree_controls:
        result = selected_from_tree(tree)
        if result:
            return result
    return None


def read_selected_intersection_id(title_keyword: str, diagnostic=None) -> str:
    """Read Polygon/Link selection from the review dialog without focus changes.

    Prefer HWND-based lookup to avoid enumerating the entire UI Automation
    desktop on each background poll. UIA enumeration is a fallback only when
    the native Win32 title enumeration cannot locate the dialog.
    """
    import pygetwindow as gw
    from pywinauto import Desktop

    def timed(label, operation):
        if diagnostic is None:
            return operation()
        diagnostic(f"{label} 시작")
        started = time.monotonic()
        outcome = "완료"
        try:
            return operation()
        except Exception:
            outcome = "오류"
            raise
        finally:
            diagnostic(f"{label} {outcome} · {(time.monotonic() - started) * 1000:.0f}ms")

    configured_key = _comparable_title(title_keyword)
    if not configured_key:
        raise ValueError("Intersection review window title cannot be empty")

    handles = []
    cached_window = _SELECTION_WINDOW_CACHE.get(configured_key)
    if cached_window:
        try:
            text = Desktop(backend="win32").window(
                handle=cached_window
            ).wrapper_object().window_text()
            if configured_key in _comparable_title(text):
                handles.append(cached_window)
        except Exception:
            pass
    if not handles:
        try:
            win32_matches = timed("Win32 창 목록 조회", lambda: [
                window for window in gw.getAllWindows()
                if configured_key in _comparable_title(window.title)
            ])
            handles = list(dict.fromkeys(
                int(getattr(window, "_hWnd", 0) or 0)
                for window in win32_matches
                if getattr(window, "_hWnd", 0)
            ))
            if handles:
                _SELECTION_WINDOW_CACHE[configured_key] = handles[0]
        except Exception:
            handles = []


    if diagnostic is not None:
        diagnostic(f"Win32 일치 유효HWND={len(handles)}, 캐시조회={bool(cached_window)}")
    if handles:
        # Direct TVGN_CARET + parent-chain lookup avoids scanning thousands
        # of items. UIA Selection is a fallback only, never a full item walk.
        for handle in handles:
            result = timed("Win32 트리 선택 조회", lambda: _read_win32_intersection(handle, diagnostic))
            if result:
                return result

        # Custom-drawn review trees may not expose a native TreeView.
        # Use the slower UIA path only when the fast native lookup fails.
        for handle in handles:
            try:
                wrapper = timed("UIA 창 연결", lambda: Desktop(backend="uia").window(handle=handle).wrapper_object())
                result = timed("UIA 트리 선택 조회", lambda: _read_uia_intersection(wrapper, diagnostic))
                if result:
                    return result
            except Exception:
                pass
    else:
        # Only use the expensive desktop UIA enumeration for dialogs that
        # Win32 cannot see at all.
        try:
            uia_matches = timed("UIA 전체 창 검색", lambda: [
                window for window in Desktop(backend="uia").windows()
                if configured_key in _comparable_title(window.window_text())
            ])
        except Exception:
            uia_matches = []

        if not uia_matches:
            raise RuntimeError(
                f"Intersection review window not found (Win32 / UIA): {title_keyword!r}"
            )

        for window in uia_matches:
            result = timed("UIA 트리 선택 조회", lambda: _read_uia_intersection(window, diagnostic))
            if result:
                return result
            try:
                handle = int(window.handle)
                if handle:
                    result = timed("Win32 트리 선택 조회", lambda: _read_win32_intersection(handle, diagnostic))
                    if result:
                        return result
            except Exception:
                pass

    raise RuntimeError(
        "Intersection review window found, but selected Polygon/Link could "
        "not be read via UIA or Win32. Check the selected tree item and "
        "whether the application exposes a SysTreeView32 control."
    )
