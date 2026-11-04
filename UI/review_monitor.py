"""Read intersection selections away from the Qt GUI event loop.

This monitor is deliberately read-only. It polls the configured review
window even when Chrome or map_validator has focus. Work sessions pause
the monitor to avoid competing UIA reads. It never moves or resizes a window.
"""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from map_validator.app_logging import log_exception_at_source
from map_validator.com_threading import sta_com_apartment

APP_LOG = logging.getLogger("map_validator.ui.review_monitor")


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
        from map_validator.windows import read_selected_intersection_id

        last_selection = None
        while not self.isInterruptionRequested():
            if self.review_title and not self._paused.is_set():
                try:
                    # UIA and Win32 tree selection can be queried without
                    # foreground focus; never activate, move, or resize the
                    # HD_3D Tool or its review dialog.
                    selected_id = read_selected_intersection_id(self.review_title)
                    if not self._paused.is_set() and selected_id != last_selection:
                        last_selection = selected_id
                        self.selection_changed.emit(selected_id)
                except Exception:
                    # Selection can be empty or the dialog can close briefly.
                    # Keep last_selection and retry without touching focus.
                    APP_LOG.debug("교차로 선택 감시 중 일시적 조회 실패", exc_info=True)

            # Check interruption promptly without a busy spin.
            for _ in range(7):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
