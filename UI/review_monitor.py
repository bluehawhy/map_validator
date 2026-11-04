"""Update the review ID only after left clicks in the review window.

A native low-level mouse hook detects the user's click without repeatedly
querying Windows UI Automation. The hook callback only queues a notification;
a separate reader thread checks the Polygon/Link selection 200 ms later so
neither the Qt event loop nor the global mouse hook blocks on UIA.
"""
from __future__ import annotations

import ctypes
import logging
import re
import sys
import threading
import time
from ctypes import wintypes

from PyQt6.QtCore import QThread, pyqtSignal

from map_validator.app_logging import log_exception_at_source
from map_validator.com_threading import sta_com_apartment

APP_LOG = logging.getLogger("map_validator.ui.review_monitor")

WH_MOUSE_LL = 14
WM_LBUTTONUP = 0x0202
WM_QUIT = 0x0012
PM_REMOVE = 0x0001
SELECTION_SETTLE_SECONDS = 0.20


def _comparable_title(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


class ReviewSelectionMonitor(QThread):
    """Listen to click events without moving, activating, or resizing windows."""

    selection_changed = pyqtSignal(str)

    def __init__(self, review_title: str, parent=None) -> None:
        super().__init__(parent)
        self.review_title = review_title.strip()
        self._title_key = _comparable_title(self.review_title)
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self._pending = False
        self._last_click_at = 0.0

    def set_paused(self, paused: bool) -> None:
        with self._condition:
            if paused:
                self._paused.set()
                self._pending = False
            else:
                self._paused.clear()
            self._condition.notify_all()

    def _schedule_read(self) -> None:
        # Called by the low-level mouse hook. Never perform any UIA work here.
        if self._paused.is_set() or self._stop.is_set():
            return
        with self._condition:
            self._last_click_at = time.monotonic()
            self._pending = True
            self._condition.notify()

    def _read_after_click(self) -> None:
        try:
            from map_validator.windows import read_selected_intersection_id

            with sta_com_apartment():
                last_selection = None
                while not self._stop.is_set():
                    with self._condition:
                        while not self._pending and not self._stop.is_set():
                            self._condition.wait(timeout=0.25)
                        if self._stop.is_set():
                            return

                        # Coalesce quick/double clicks. Inspect only after the
                        # selection has had time to settle.
                        while not self._stop.is_set():
                            remaining = (
                                self._last_click_at + SELECTION_SETTLE_SECONDS
                                - time.monotonic()
                            )
                            if remaining <= 0:
                                break
                            self._condition.wait(timeout=remaining)
                        if self._stop.is_set():
                            return
                        click_at = self._last_click_at
                        self._pending = False

                    if self._paused.is_set():
                        continue
                    read_started = time.monotonic()
                    APP_LOG.info(
                        "선택 조회 시작 · 클릭 후 %.0fms",
                        (read_started - click_at) * 1000,
                    )
                    outcome = "실패"
                    try:
                        selected = read_selected_intersection_id(
                            self.review_title,
                            diagnostic=lambda message: APP_LOG.info("선택 조회 · %s", message),
                        )
                        outcome = "변경" if selected and selected != last_selection else "변경 없음"
                        if (
                            selected
                            and selected != last_selection
                            and not self._paused.is_set()
                            and not self._stop.is_set()
                        ):
                            last_selection = selected
                            self.selection_changed.emit(selected)
                    except Exception as exc:
                        # The selection or window may disappear during a read.
                        APP_LOG.warning("선택 조회 실패 · %s: %s", type(exc).__name__, exc)
                    finally:
                        finished = time.monotonic()
                        APP_LOG.info(
                            "선택 조회 종료 · 결과 %s · 조회 %.0fms · 클릭 후 %.0fms",
                            outcome, (finished - read_started) * 1000,
                            (finished - click_at) * 1000,
                        )
        except Exception as exc:
            log_exception_at_source(APP_LOG, "클릭 기반 검수 ID 조회 오류", exc)

    def run(self) -> None:
        if not self._title_key:
            return
        if sys.platform != "win32":
            APP_LOG.error("마우스 클릭 감시는 Windows에서만 지원합니다.")
            return

        self._stop.clear()
        reader = threading.Thread(
            target=self._read_after_click,
            name="ReviewSelectionReader",
            daemon=True,
        )
        reader.start()
        try:
            self._run_mouse_hook()
        except Exception as exc:
            log_exception_at_source(APP_LOG, "마우스 클릭 감시 시작 실패", exc)
        finally:
            self._stop.set()
            with self._condition:
                self._pending = False
                self._condition.notify_all()
            # Never block Qt shutdown indefinitely on a stuck target UIA read.
            reader.join(timeout=0.25)

    def _run_mouse_hook(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hook_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, hook_type, ctypes.c_void_p, wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        def on_mouse(code: int, message: int, data: int) -> int:
            if code >= 0 and message == WM_LBUTTONUP and not self._paused.is_set():
                try:
                    handle = user32.GetForegroundWindow()
                    if handle:
                        title_buffer = ctypes.create_unicode_buffer(256)
                        if user32.GetWindowTextW(
                            handle, title_buffer, len(title_buffer)
                        ):
                            if self._title_key in _comparable_title(
                                title_buffer.value
                            ):
                                self._schedule_read()
                except Exception:
                    # Never let exceptions escape a Win32 hook callback.
                    pass
            return user32.CallNextHookEx(None, code, message, data)

        callback = hook_type(on_mouse)
        handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL, callback, kernel32.GetModuleHandleW(None), 0
        )
        if not handle:
            error = ctypes.get_last_error()
            raise OSError(error, "Windows 마우스 클릭 후크 등록 실패")

        APP_LOG.info(
            "검수 ID 클릭 감시 시작: '%s' 창에서 왼쪽 클릭 후 조회",
            self.review_title,
        )
        try:
            message = wintypes.MSG()
            while not self.isInterruptionRequested():
                while user32.PeekMessageW(
                    ctypes.byref(message), None, 0, 0, PM_REMOVE
                ):
                    if message.message == WM_QUIT:
                        return
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                self.msleep(20)
        finally:
            user32.UnhookWindowsHookEx(handle)
            APP_LOG.info("검수 ID 클릭 감시 종료")
