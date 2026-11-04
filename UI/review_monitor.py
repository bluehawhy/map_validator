"""Read intersection selections away from the Qt GUI event loop.

This monitor is deliberately read-only. It polls only while the configured
review window is foreground, and never runs an expensive UIA scan on the GUI
thread. Work sessions pause the monitor to avoid competing UIA reads.
"""
from __future__ import annotations

import logging
import re
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from map_validator.app_logging import log_exception_at_source
from map_validator.com_threading import sta_com_apartment

APP_LOG = logging.getLogger("map_validator.ui.review_monitor")


def _comparable_title(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


class ReviewSelectionMonitor(QThread):
    selection_changed = pyqtSignal(str)

    def __init__(self, review_title: str, parent=None) -> None:
        super().__init__(parent)
        self.review_title = review_title.strip()
        self._paused = threading.Event()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def run(self) -> None:
        try:
            with sta_com_apartment():
                self._poll_selection()
        except Exception as exc:
            log_exception_at_source(APP_LOG, "교차로 선택 감시 스레드 오류", exc)

    def _poll_selection(self) -> None:
        # Both imports and Windows automation run on this dedicated thread.
        import pygetwindow as gw
        from map_validator.windows import read_selected_intersection_id

        target_key = _comparable_title(self.review_title)
        last_selection = None
        while not self.isInterruptionRequested():
            if target_key and not self._paused.is_set():
                try:
                    active = gw.getActiveWindow()
                    if (
                        active is not None
                        and target_key in _comparable_title(active.title or "")
                    ):
                        selected_id = read_selected_intersection_id(self.review_title)
                        if not self._paused.is_set() and selected_id != last_selection:
                            last_selection = selected_id
                            self.selection_changed.emit(selected_id)
                except Exception:
                    # The user can momentarily deselect a tree item, or switch
                    # windows while UIA is inspecting. Keep the monitor alive.
                    APP_LOG.debug("교차로 선택 감시 중 일시적 조회 실패", exc_info=True)

            # Check interruption promptly without a busy spin.
            for _ in range(9):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
