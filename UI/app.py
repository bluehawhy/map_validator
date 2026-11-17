"""PyQt6 floating control panel, inspired by bluehawhy/nv_c_test's layout."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PyQt6.QtCore import QObject, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QFrame,
    QDoubleSpinBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from .individual_review_controls import IndividualReviewControls
from map_validator.app_logging import (
    AppLogFormatter,
    LOG_DIR,
    configure_app_logging,
    log_exception_at_source,
)

APP_LOG = configure_app_logging()


class _UILogRelay(QObject):
    line_ready = pyqtSignal(str)


class _UILogHandler(logging.Handler):
    """Forward records to the UI without directly updating Qt from worker threads."""

    def __init__(self, relay: _UILogRelay) -> None:
        super().__init__()
        self.relay = relay
        self.setFormatter(AppLogFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.relay.line_ready.emit(self.format(record))
        except Exception:
            self.handleError(record)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
EXAMPLE = ROOT / "config.example.yaml"

STYLE_FILE = Path(__file__).with_name("style.qss")


class DragHeader(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._last_pos = None
        self.setObjectName("header")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pos = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._last_pos is not None:
            current = event.globalPosition().toPoint()
            delta = current - self._last_pos
            self.window().move(self.window().pos() + delta)
            self._last_pos = current
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._last_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker = None
        self._scroll_to_results = False
        self.review_monitor = None
        self._close_pending = False
        self.latest_folder: str | None = None
        self._displayed_case_id = ""
        self._panel_sizes_before_collapse = {}
        self.cfg = self._read_settings()
        self._setup()
        self._start_review_monitor()

    def _read_settings(self) -> dict:
        if not EXAMPLE.exists():
            raise FileNotFoundError(f"설정 예제 파일이 없습니다: {EXAMPLE}")

        defaults = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        if not isinstance(defaults, dict):
            raise ValueError("설정 예제 YAML 내용이 올바르지 않습니다.")
        if not CONFIG.exists():
            CONFIG.write_text(
                yaml.safe_dump(defaults, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return defaults

        saved = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("config.yaml 내용이 올바르지 않습니다.")

        def add_missing(existing: dict, default_values: dict) -> dict:
            """Add only absent keys. Existing config.yaml values always win."""
            result = dict(existing)
            for key, default_value in default_values.items():
                if key not in result:
                    result[key] = default_value
                elif isinstance(result[key], dict) and isinstance(default_value, dict):
                    result[key] = add_missing(result[key], default_value)
            return result

        merged = add_missing(saved, defaults)
        if isinstance(merged.get("ui"), dict):
            merged["ui"].pop("last_case_id", None)
        if merged != saved:
            self._backup_config()
            CONFIG.write_text(
                yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        return merged

    def _backup_config(self) -> None:
        if not CONFIG.exists():
            return
        backup_dir = ROOT / "config.backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(CONFIG, backup_dir / f"config-{stamp}.yaml")

    def _label(self, text: str, kind: str | None = None) -> QLabel:
        label = QLabel(text)
        if kind:
            label.setObjectName(kind)
        return label

    def _setup(self) -> None:
        self.setWindowTitle("map_validator")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(485, 570)
        self.resize(510, 760)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        opacity = float(self.cfg.get("ui", {}).get("opacity", 0.92))
        self.setWindowOpacity(max(0.35, min(opacity, 1.0)))
        outer = QWidget()
        outer.setObjectName("panel")
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(18, 14, 18, 15)
        layout.setSpacing(8)

        header = QWidget()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        drag_area = DragHeader()
        drag_area.setToolTip("이 영역을 드래그해 창을 이동합니다.")
        drag_layout = QHBoxLayout(drag_area)
        drag_layout.setContentsMargins(0, 0, 8, 0)
        title_label = self._label("🛣  map_validator", "title")
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        drag_layout.addWidget(title_label)
        drag_layout.addStretch(1)
        header_layout.addWidget(drag_area, 1)

        header_layout.addWidget(self._label("투명도", "hint"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(35, 100)
        self.opacity_slider.setFixedWidth(72)
        self.opacity_slider.setToolTip("제어창 투명도")
        self.opacity_slider.setValue(round(self.windowOpacity() * 100))
        self.opacity_slider.valueChanged.connect(
            lambda value: self.setWindowOpacity(value / 100)
        )
        self.opacity_slider.sliderReleased.connect(self._save_settings)
        header_layout.addWidget(self.opacity_slider)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("header_button")
        self.settings_btn.setFixedSize(25, 23)
        self.settings_btn.setToolTip("분석 설정 · 로드뷰 정지선 threshold")
        self.settings_btn.clicked.connect(self._show_analysis_settings)
        header_layout.addWidget(self.settings_btn)
        for label, callback, tooltip in (
            ("—", self.showMinimized, "숨기기 (Esc)"),
            ("×", self.close, "종료"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("header_button")
            btn.setFixedSize(25, 23)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            header_layout.addWidget(btn)
        layout.addWidget(header)

        # Worker progress remains log-backed; no persistent top status strip.
        self.status_label = self._label("준비됨 | 현장 최종 검수 필요", "status")

        target_header = QHBoxLayout()
        target_header.addWidget(self._label("대상 설정", "section"))
        target_header.addStretch(1)
        self.window_info_btn = QPushButton("창 정보 보기")
        self.window_info_btn.setToolTip("현재 열린 Windows 창과 하위 컨트롤 정보를 확인합니다.")
        self.window_info_btn.clicked.connect(self._show_window_info)
        target_header.addWidget(self.window_info_btn)
        layout.addLayout(target_header)
        basic_grid = QGridLayout()
        basic_grid.setHorizontalSpacing(8)
        basic_grid.setVerticalSpacing(6)
        self.work_input = QLineEdit(self.cfg["windows"].get("work_title", ""))
        self.work_input.setPlaceholderText("이미 실행 중인 입력 프로그램 창")
        self.work_select_btn = QPushButton("선택")
        self.work_select_btn.setObjectName("select_button")
        self.work_select_btn.clicked.connect(
            lambda: self._activate_configured_window(self.work_input, "입력 프로그램")
        )
        basic_grid.addWidget(self._label("입력 프로그램"), 0, 0)
        basic_grid.addWidget(self.work_input, 0, 1)
        basic_grid.addWidget(self.work_select_btn, 0, 2)

        self.view_input = QLineEdit(self.cfg["windows"].get("roadview_title", ""))
        self.view_input.setPlaceholderText("이미 실행 중인 로드뷰 프로그램 창")
        self.view_select_btn = QPushButton("선택")
        self.view_select_btn.setObjectName("select_button")
        self.view_select_btn.clicked.connect(
            lambda: self._activate_configured_window(self.view_input, "로드뷰 프로그램")
        )
        basic_grid.addWidget(self._label("로드뷰 프로그램"), 1, 0)
        basic_grid.addWidget(self.view_input, 1, 1)
        basic_grid.addWidget(self.view_select_btn, 1, 2)

        self.case_input = QLineEdit()
        self.case_input.setPlaceholderText("Polygon 또는 Link 선택 시 자동 입력")
        basic_grid.addWidget(self._label("검수 ID"), 2, 0)
        basic_grid.addWidget(self.case_input, 2, 1)
        self.review_select_btn = QPushButton("선택")
        self.review_select_btn.setObjectName("select_button")
        self.review_select_btn.setToolTip(
            "교차로 선형 검수 창에서 현재 선택한 Polygon/Link ID를 읽습니다."
        )
        self.review_select_btn.clicked.connect(self._refresh_review_selection)
        basic_grid.addWidget(self.review_select_btn, 2, 2)
        basic_grid.setColumnStretch(1, 1)
        layout.addLayout(basic_grid)

        # Selection monitor remains automatic, without a manual UI toggle.

        for field in (self.work_input, self.view_input):
            field.editingFinished.connect(self._save_settings)

        output_row = QHBoxLayout()
        self.output_input = QLineEdit(
            self.cfg.get("output", {}).get("directory", "results")
        )
        self.output_input.setPlaceholderText("스크린샷과 분석 결과 저장 폴더")
        self.output_input.setToolTip(
            "상대 경로는 프로젝트 폴더 기준이며, 다른 드라이브의 절대 경로도 사용할 수 있습니다."
        )
        output_browse = QPushButton("찾기")
        output_browse.clicked.connect(self._select_output)
        self.output_input.editingFinished.connect(self._save_settings)
        self.output_input.editingFinished.connect(self._refresh_stage_states)
        self.output_input.editingFinished.connect(self._refresh_individual_items)
        output_row.addWidget(self._label("저장 경로"))
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(output_browse)
        layout.addLayout(output_row)

        # Entire pages, not a narrow tab strip inside the capture pane.
        self.capture_tabs = QTabWidget()
        self.capture_tabs.setObjectName("captureTabs")
        layout.addWidget(self.capture_tabs, 1)
        staged_page = QWidget()
        staged_layout = QVBoxLayout(staged_page)
        staged_layout.setContentsMargins(4, 6, 4, 4)
        # Staged capture, staged comparison and logs remain resizable.
        self.panel_splitter = QSplitter(Qt.Orientation.Vertical)
        self.panel_splitter.setObjectName("reviewSplitter")
        self.panel_splitter.setChildrenCollapsible(False)
        staged_layout.addWidget(self.panel_splitter, 1)
        self.capture_tabs.addTab(staged_page, "단계별 수동 촬영")

        steps_scroller = QScrollArea()
        self.steps_scroller = steps_scroller
        steps_scroller.setFrameShape(QFrame.Shape.NoFrame)
        steps_scroller.setWidgetResizable(True)
        steps_scroller.setObjectName("stageScroller")
        steps_scroller.setMinimumHeight(110)
        content = QWidget()
        content.setObjectName("content")
        sections = QVBoxLayout(content)
        sections.setContentsMargins(1, 0, 4, 0)
        sections.setSpacing(6)
        steps_scroller.setWidget(content)
        self.panel_splitter.addWidget(steps_scroller)

        from map_validator.stage_types import STAGES, STAGE_BUTTONS, STAGE_LABELS

        sections.addWidget(self._label("단계별 수동 촬영", "section"))
        self.stage_buttons = {}
        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        short_labels = {
            "before": "진입 전",
            "after_left": "진입 후 좌",
            "after_straight": "진입 후 직",
            "after_right": "진입 후 우",
        }
        for stage in STAGES:
            button = QPushButton(short_labels[stage])
            button.setObjectName("stage_capture")
            button.setProperty("stageCaptured", False)
            button.setMinimumWidth(0)
            button.setFixedHeight(30)
            button.setToolTip(
                f"{STAGE_LABELS[stage]} 촬영 · 미촬영"
            )
            button.clicked.connect(
                lambda checked=False, selected=stage: self._start(
                    "capture_" + selected
                )
            )
            button_row.addWidget(button, 1)
            self.stage_buttons[stage] = button
        sections.addLayout(button_row)

        self.stop_line_threshold_value = max(0.35, min(0.95, float(
            self.cfg.get("analysis", {}).get("stop_line_roadview_threshold", 0.68)
        )))
        actions = QHBoxLayout()
        self.start_btn = QPushButton("촬영본 분석")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("분석 중지")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(lambda: self._start("analyze_staged"))
        self.stop_btn.clicked.connect(self._stop)
        actions.addWidget(self.start_btn, 2)
        actions.addWidget(self.stop_btn, 1)
        sections.addLayout(actions)
        sections.addStretch(1)

        # Capture-only workflow and separate review of saved input_tool images.
        self.individual_controls = IndividualReviewControls()
        self.individual_capture_btn = self.individual_controls.capture_button
        self.individual_analyze_btn = self.individual_controls.analyze_button
        self.individual_overlay_btn = self.individual_controls.overlay_button
        self.individual_status = self.individual_controls.status_label
        self.individual_details = self.individual_controls.details
        self._individual_overlay_path = None
        self.individual_capture_btn.clicked.connect(
            lambda: self._start("capture_individual")
        )
        self.individual_analyze_btn.clicked.connect(
            lambda: self._start("analyze_individual")
        )
        self.individual_controls.selection_changed.connect(
            self._on_individual_selection_changed
        )
        self.individual_controls.refresh_button.clicked.connect(
            self._refresh_individual_items
        )
        self.capture_tabs.addTab(self.individual_controls, "개별 촬영")

        self._panels = {}
        result_panel = QFrame()
        result_panel.setObjectName("sectionCard")
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(7, 5, 7, 6)
        result_layout.setSpacing(5)
        self.result_heading = QPushButton("▾  항목별 비교 결과 (검수 보조)")
        self.result_heading.setObjectName("section_toggle")
        self.result_heading.setCheckable(True)
        self.result_heading.setChecked(True)
        result_layout.addWidget(self.result_heading)
        result_body = QWidget()
        result_body_layout = QVBoxLayout(result_body)
        result_body_layout.setContentsMargins(0, 0, 0, 0)
        result_body_layout.setSpacing(5)
        self.geometry_result = self._label("분석 전 · 최종 사람 검수 필요", "decision")
        result_body_layout.addWidget(self.geometry_result)
        self.analysis_details = QTextEdit()
        self.analysis_details.setReadOnly(True)
        self.analysis_details.setPlaceholderText(
            "진입 전: 정지선 / 차로 수 / 화살표 / 컬러유도선\n"
            "진입 후 좌·직·우: 도로 유무 / 차로 수 / 일반·컬러유도선"
        )
        result_body_layout.addWidget(self.analysis_details, 1)
        result_layout.addWidget(result_body, 1)
        self.panel_splitter.addWidget(result_panel)
        self._panels["result"] = (
            result_body, self.result_heading, "항목별 비교 결과 (검수 보조)", 1,
        )
        self.result_heading.toggled.connect(
            lambda expanded: self._toggle_panel("result", expanded)
        )

        log_panel = QFrame()
        log_panel.setObjectName("sectionCard")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(7, 5, 7, 6)
        log_layout.setSpacing(5)
        self.logs_heading = QPushButton("▾  작업 로그")
        self.logs_heading.setObjectName("section_toggle")
        self.logs_heading.setCheckable(True)
        self.logs_heading.setChecked(True)
        log_layout.addWidget(self.logs_heading)
        log_body = QWidget()
        log_body_layout = QVBoxLayout(log_body)
        log_body_layout.setContentsMargins(0, 0, 0, 0)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        log_body_layout.addWidget(self.logs)
        log_layout.addWidget(log_body, 1)
        self.panel_splitter.addWidget(log_panel)
        self._panels["logs"] = (log_body, self.logs_heading, "작업 로그", 2)
        self.logs_heading.toggled.connect(
            lambda expanded: self._toggle_panel("logs", expanded)
        )
        self.panel_splitter.setStretchFactor(0, 2)
        self.panel_splitter.setStretchFactor(1, 3)
        self.panel_splitter.setStretchFactor(2, 2)
        QTimer.singleShot(0, lambda: self.panel_splitter.setSizes([150, 250, 150]))
        self._log_relay = _UILogRelay(self)
        self._log_relay.line_ready.connect(self._append_log_line)
        self._log_handler = _UILogHandler(self._log_relay)
        APP_LOG.addHandler(self._log_handler)

        footer = QHBoxLayout()
        self.save_btn = QPushButton("설정 저장")
        self.folder_btn = QPushButton("결과 폴더")
        self.folder_btn.setEnabled(False)
        self.copy_logs_btn = QPushButton("로그 복사")
        self.logs_folder_btn = QPushButton("로그 폴더")
        self.save_btn.clicked.connect(self._save_settings)
        self.folder_btn.clicked.connect(self._open_folder)
        self.copy_logs_btn.clicked.connect(self._copy_logs)
        self.logs_folder_btn.clicked.connect(self._open_logs_folder)
        footer.addWidget(self.save_btn)
        footer.addWidget(self.folder_btn)
        footer.addWidget(self.copy_logs_btn)
        footer.addWidget(self.logs_folder_btn)
        footer.addStretch(1)
        layout.addLayout(footer)
        self.case_input.textChanged.connect(self._refresh_stage_states)
        self._refresh_stage_states()
        self._refresh_individual_items()
        self._log("준비 완료. 진입 전→좌→직→우 네 방향을 각각 수동 촬영하세요.")

    @staticmethod
    def _program_title(window_title: str) -> str:
        """Remove per-workspace suffixes while keeping a stable program title."""
        title = window_title.strip()
        if " - " in title:
            title = title.split(" - ", 1)[0].strip()
        return title

    def _show_analysis_settings(self) -> None:
        """Open threshold settings without occupying the capture workspace."""
        dialog = QDialog(self)
        dialog.setWindowTitle("분석 설정")
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet("QDialog { background-color: #F3F3F3; }")
        form = QVBoxLayout(dialog)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(11)
        form.addWidget(self._label("로드뷰 정지선 threshold", "section"))
        threshold = QDoubleSpinBox(dialog)
        threshold.setRange(0.35, 0.95)
        threshold.setSingleStep(0.05)
        threshold.setDecimals(2)
        threshold.setValue(self.stop_line_threshold_value)
        threshold.setToolTip(
            "로드뷰 단독 흰색 정지선의 최소 검출 점수입니다."
        )
        form.addWidget(threshold)
        form.addWidget(self._label(
            "높을수록 엄격하게 판정하며, 판단 보류가 늘어날 수 있습니다. "
            "횡단보도는 정지선으로 판정하지 않습니다.", "hint"
        ))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = round(threshold.value(), 2)
            if value != self.stop_line_threshold_value:
                self.stop_line_threshold_value = value
                self._save_settings()
                self._log(f"로드뷰 정지선 threshold 변경: {value:.2f}")

    def _toggle_panel(self, key: str, expanded: bool) -> None:
        """Collapse/expand either pane; splitter handles remain draggable."""
        body, toggle, title, index = self._panels[key]
        sizes = self.panel_splitter.sizes()
        if expanded:
            body.show()
            toggle.setText("▾  " + title)
            desired = self._panel_sizes_before_collapse.get(key, 170)
            delta = min(max(0, desired - sizes[index]), max(0, sizes[0] - 145))
            sizes[index] += delta
            sizes[0] -= delta
        else:
            self._panel_sizes_before_collapse[key] = sizes[index]
            body.hide()
            toggle.setText("▸  " + title)
            gained = max(0, sizes[index] - 37)
            sizes[index] -= gained
            sizes[0] += gained
        QTimer.singleShot(
            0, lambda new_sizes=sizes: self.panel_splitter.setSizes(new_sizes)
        )

    def _show_window_info(self) -> None:
        from .window_info_dialog import WindowInfoDialog

        dialog = WindowInfoDialog(self)
        dialog.exec()

    def _activate_configured_window(self, field: QLineEdit, label: str) -> None:
        try:
            import pygetwindow as gw

            configured = self._program_title(field.text())
            if not configured:
                raise ValueError(f"{label} 프로그램명을 먼저 입력하세요.")

            windows = [
                window for window in gw.getAllWindows()
                if window.title.strip()
                and window.title.strip() != self.windowTitle()
            ]

            direct_matches = [
                window for window in gw.getWindowsWithTitle(configured)
                if window.title.strip() != self.windowTitle()
            ]

            def comparable(value: str) -> str:
                return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())

            configured_key = comparable(configured)
            normalized_matches = [
                window for window in windows
                if configured_key
                and (
                    configured_key == comparable(self._program_title(window.title))
                    or configured_key in comparable(window.title)
                )
            ]
            matches = direct_matches or normalized_matches
            if not matches:
                detected = ", ".join(window.title.strip() for window in windows[:8])
                detail = f" 감지된 창: {detected}" if detected else " 감지된 창 없음"
                raise RuntimeError(
                    f"실행 중인 {label} 창을 찾지 못했습니다: {configured}.{detail}"
                )

            target = next(
                (
                    window for window in matches
                    if comparable(self._program_title(window.title)) == configured_key
                ),
                matches[0],
            )
            field.setText(configured)
            self._save_settings()
            if target.isMinimized:
                if label == "입력 프로그램":
                    raise RuntimeError(
                        "입력도구는 창 위치·크기 보호를 위해 자동 복원하지 않습니다. "
                        "사용자가 직접 복원해 주세요."
                    )
                target.restore()
            target.activate()
        except Exception as exc:
            log_exception_at_source(APP_LOG, f"{label} 선택 실패", exc)

    def _refresh_review_selection(self) -> None:
        """Read the current Polygon/Link selection without changing window focus."""
        monitor = self.review_monitor
        if monitor is None or not monitor.request_selection_refresh():
            self._log(
                "검수 ID 수동 조회 불가: 선택 감시가 실행 중이 아니거나 다른 작업 중입니다.",
                logging.WARNING,
            )
            return
        self.review_select_btn.setEnabled(False)

    def _on_manual_review_selection(self, review_id: str, generation: int) -> None:
        monitor = self.review_monitor
        if (monitor is None or not monitor.is_latest(generation)
                or self._close_pending or (
                    self.worker is not None and self.worker.isRunning()
                )):
            return
        self.case_input.setText(review_id)
        self._log(f"검수 ID 수동 조회 완료: {review_id}")

    def _on_manual_review_finished(self) -> None:
        if not self._close_pending and (
            self.worker is None or not self.worker.isRunning()
        ):
            self.review_select_btn.setEnabled(True)

    def _select_output(self) -> None:
        current = self.output_input.text().strip() or "results"
        start = Path(current)
        if not start.is_absolute():
            start = ROOT / start
        if not start.exists():
            start = start.parent if start.parent.exists() else ROOT
        folder = QFileDialog.getExistingDirectory(
            self, "스크린샷 저장 폴더 선택", str(start)
        )
        if folder:
            selected = Path(folder)
            try:
                self.output_input.setText(str(selected.relative_to(ROOT)))
            except ValueError:
                self.output_input.setText(str(selected))
            # Folder-picker changes do not fire editingFinished on QLineEdit.
            self._save_settings()
            self._refresh_stage_states()
            self._refresh_individual_items()

    def _start_review_monitor(self) -> None:
        from .review_monitor import ReviewSelectionMonitor

        review_title = self.cfg.get("windows", {}).get(
            "intersection_review_title", ""
        ).strip()
        if not review_title:
            self._log("선택 감시 사용 불가: 교차로 선형 검수 창 제목이 없습니다.")
            return
        self.review_monitor = ReviewSelectionMonitor(review_title, self)
        self.review_monitor.selection_changed.connect(self._on_review_selection)
        self.review_monitor.manual_selection_ready.connect(
            self._on_manual_review_selection
        )
        self.review_monitor.manual_selection_finished.connect(
            self._on_manual_review_finished
        )
        self.review_monitor.finished.connect(self._on_review_monitor_finished)
        self.review_monitor.start()

    def _on_review_selection(self, review_id: str, generation: int) -> None:
        monitor = self.review_monitor
        if (monitor is None or not monitor.is_latest(generation)
                or self._close_pending or (
                    self.worker is not None and self.worker.isRunning()
                )):
            return
        if review_id != self.case_input.text().strip():
            self.case_input.setText(review_id)
            self.geometry_result.setText("새 검수 ID · 촬영/분석 전")
            self.analysis_details.clear()
            self._log(f"검수 ID 자동 업데이트: {review_id}")

    def _on_review_monitor_finished(self) -> None:
        if self._close_pending:
            QTimer.singleShot(0, self.close)
            return
        monitor = self.review_monitor
        self.review_monitor = None
        if monitor is not None:
            monitor.deleteLater()
        self.case_input.clear()
        self.review_select_btn.setEnabled(False)
        self._log(
            "교차로 선택 감시 종료 · 검수 ID 자동 갱신 중지",
            logging.WARNING,
        )

    def _on_analysis_case_id(self, case_id: str) -> None:
        self.case_input.setText(case_id)

    def _current_settings(self) -> dict:
        cfg = self._read_settings()
        cfg.setdefault("windows", {})
        cfg.setdefault("output", {})
        cfg.setdefault("ui", {})
        cfg.setdefault("analysis", {})
        cfg["analysis"]["stop_line_roadview_threshold"] = round(
            self.stop_line_threshold_value, 2
        )
        cfg["windows"]["work_title"] = self.work_input.text().strip()
        cfg["windows"]["roadview_title"] = self.view_input.text().strip()
        cfg["output"]["directory"] = self.output_input.text().strip() or "results"
        cfg["ui"]["opacity"] = round(self.opacity_slider.value() / 100, 2)
        return cfg

    def _save_settings(self) -> None:
        try:
            cfg = self._current_settings()
            self._backup_config()
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self.cfg = cfg
            self._log("로컬 config.yaml 저장 완료 (기존 파일은 config.backups에 백업)")
        except Exception as exc:
            log_exception_at_source(APP_LOG, "설정 저장 실패", exc)

    def _case_folder(self) -> Path | None:
        case_id = self.case_input.text().strip()
        if not case_id:
            return None
        from map_validator.stage_types import validate_case_id

        try:
            validate_case_id(case_id)
        except ValueError:
            return None
        configured = Path(self.output_input.text().strip() or "results").expanduser()
        base = configured if configured.is_absolute() else ROOT / configured
        return base / case_id

    def _set_capture_state(
        self, stage: str, captured: bool, revision: int = 0,
        partial: bool = False,
    ) -> None:
        """Show completed shots using a green button, without extra labels."""
        from map_validator.stage_types import STAGE_LABELS

        button = self.stage_buttons[stage]
        if button.property("stageCaptured") != captured:
            button.setProperty("stageCaptured", captured)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()
        state = (
            f"촬영 완료 ({revision}회)" if captured
            else "일부 누락" if partial else "미촬영"
        )
        button.setToolTip(f"{STAGE_LABELS[stage]} · {state}")

    def _refresh_stage_states(self, _text: str = "") -> None:
        from map_validator.stage_types import STAGES
        from map_validator.staged_capture import read_manifest, stage_status

        current_id = self.case_input.text().strip()
        if current_id != self._displayed_case_id:
            self._displayed_case_id = current_id
            self.geometry_result.setText("검수 ID 변경 · 촬영본 분석 전")
            self.analysis_details.clear()
            self.latest_folder = None
            self.folder_btn.setEnabled(False)

        folder = self._case_folder()
        for stage in STAGES:
            self._set_capture_state(stage, False)
        if folder is None:
            return
        try:
            manifest = read_manifest(folder, self.case_input.text().strip())
            for stage in STAGES:
                record = manifest["stages"][stage]
                current = stage_status(folder, record)
                self._set_capture_state(
                    stage, current == "captured", record.get("revision", 0),
                    partial=current == "partial_capture",
                )
            if folder.is_dir():
                self.latest_folder = str(folder)
                self.folder_btn.setEnabled(True)
            else:
                self.latest_folder = None
                self.folder_btn.setEnabled(False)
        except Exception as exc:
            log_exception_at_source(APP_LOG, "검수 단계 상태 읽기 실패", exc)

    def _refresh_individual_items(self, _text: str = "", preferred=None) -> None:
        configured = Path(self.output_input.text().strip() or "results").expanduser()
        root = configured if configured.is_absolute() else ROOT / configured
        self.individual_controls.reload(root, preferred=preferred)

    def _on_individual_selection_changed(self, selection) -> None:
        self._individual_overlay_path = None
        self.individual_controls.set_overlay(None)
        self.individual_details.clear()
        if selection is None:
            self.individual_status.setText("저장 경로에 개별 촬영본이 없습니다.")
            return
        folder, revision = selection
        self.individual_status.setText(
            f"선택: {folder.name} · r{revision:03d} · 정지선 분석 가능"
        )
        report = folder / f"individual_analysis_r{revision:03d}.json"
        if not report.is_file():
            return
        try:
            previous = json.loads(report.read_text(encoding="utf-8"))
            if int(previous.get("revision", -1)) != revision:
                return
            self._show_result({"kind": "individual_analysis", "folder": str(folder),
                               **previous})
        except (ValueError, OSError, KeyError) as exc:
            self._log(f"저장된 분석 결과 불러오기 실패: {exc}", logging.WARNING)

    def _start(self, action: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            from map_validator.stage_types import STAGES

            valid = {"analyze_staged", "capture_individual", "analyze_individual"} | {"capture_" + stage for stage in STAGES}
            if action not in valid:
                raise ValueError(f"지원하지 않는 작업입니다: {action}")
            cfg = self._current_settings()
            case_id = self.case_input.text().strip()
            selected = self.individual_controls.current_selection() if action == "analyze_individual" else None
            if action == "analyze_individual" and selected is None:
                raise ValueError("먼저 저장 경로의 촬영 항목을 선택하세요.")
            if action not in ("capture_individual", "analyze_individual") and not case_id and not cfg["windows"].get(
                "intersection_review_title", ""
            ).strip():
                raise ValueError(
                    "검수 ID가 없습니다. 교차로 선형 검수에서 Polygon/Link를 선택하세요."
                )
            if action not in ("analyze_staged", "analyze_individual"):
                if action != "capture_individual" and not cfg["windows"]["roadview_title"].strip():
                    raise ValueError("로드뷰 창 제목을 입력하세요.")
                if not cfg["windows"]["work_title"].strip():
                    raise ValueError("업무 창 제목을 입력하세요.")
            self.cfg = cfg
            from .worker import ControlWorker

            self.worker = ControlWorker(
                config=cfg, config_dir=ROOT, case_id=case_id,
                action=action, parent=self,
                individual_folder=selected[0] if selected else None,
                individual_revision=selected[1] if selected else None,
            )
            self.worker.progress.connect(self.status_label.setText)
            self.worker.case_id_ready.connect(self._on_analysis_case_id)
            self.worker.result_ready.connect(self._show_result)
            self.worker.show_panel.connect(self._restore_panel)
            self.worker.finished.connect(self._done)
            self._scroll_to_results = False
            scroll_position = self.steps_scroller.verticalScrollBar().value()
            # Move focus outside the scroll area before disabling its buttons.
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self._busy(True)
            if action.startswith("capture_"):
                self.steps_scroller.verticalScrollBar().setValue(scroll_position)
            self.status_label.setText("진행 중")
            self._log(f"시작: {action} / {case_id or '교차로 선택값 조회 중'}")
            self.worker.start()
        except Exception as exc:
            log_exception_at_source(APP_LOG, "시작 실패", exc)

    def _busy(self, busy: bool) -> None:
        for widget in (
            *self.stage_buttons.values(), self.start_btn,
            self.individual_capture_btn, self.individual_analyze_btn,
            self.individual_overlay_btn, self.individual_controls.combo,
            self.individual_controls.refresh_button, self.save_btn,
            self.settings_btn,
            self.case_input, self.work_input, self.view_input,
            self.work_select_btn, self.view_select_btn, self.review_select_btn,
            self.window_info_btn,
            self.output_input,
        ):
            widget.setEnabled(not busy)
        self.individual_overlay_btn.setEnabled(
            not busy and self._individual_overlay_path is not None
            and self._individual_overlay_path.is_file()
        )
        self.individual_analyze_btn.setEnabled(
            not busy and self.individual_controls.current_selection() is not None
        )
        self.stop_btn.setEnabled(busy)
        if self.review_monitor is not None:
            self.review_monitor.set_paused(busy)

    def _restore_panel(self) -> None:
        if not self.isVisible():
            self.show()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self._log("중지 요청: 현재 WGC 캡처 또는 AI 추론 단위 후 중단됩니다.")
            self.status_label.setText("중지 요청됨")

    @staticmethod
    def _format_feature(value) -> str:
        if value is None:
            return "판단 보류"
        if isinstance(value, bool):
            return "있음" if value else "없음"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    def _show_result(self, result: dict) -> None:
        if "folder" not in result:
            self._log(result.get("message", "완료"))
            return
        self.latest_folder = result["folder"]
        self.folder_btn.setEnabled(True)
        kind = result.get("kind")
        if kind == "staged_capture":
            from map_validator.stage_types import STAGE_LABELS

            stage = result["stage"]
            self._log(
                f"{STAGE_LABELS[stage]} 입력툴·로드뷰 촬영 완료 "
                f"(버전 {result['revision']})"
            )
            self.status_label.setText("단계 촬영 완료")
            self.geometry_result.setText("사진 변경됨 · 촬영본 분석을 다시 실행하세요")
            self.analysis_details.clear()
            self._refresh_stage_states()
        elif kind == "individual_capture":
            self.capture_tabs.setCurrentIndex(1)
            self._refresh_individual_items(
                preferred=(Path(result["folder"]), int(result["revision"]))
            )
            self._individual_overlay_path = None
            self.individual_overlay_btn.setEnabled(False)
            self.individual_details.clear()
            self.individual_status.setText(
                f"개별 촬영 r{result['revision']:03d} 저장됨 · 사진 선택 후 정지선 분석"
            )
            self._log(f"개별 원본 촬영 저장: {result['input_tool_image']}")
        elif kind == "individual_analysis":
            self.capture_tabs.setCurrentIndex(1)
            self._individual_overlay_path = (
                Path(result["folder"]) / result["input_tool_overlay"]
            )
            self.individual_controls.set_overlay(self._individual_overlay_path)
            focus_path = (
                Path(result["folder"])
                / result.get("input_tool_focus", result["input_tool_overlay"])
            )
            # Full-resolution evidence opens in a popup instead of an inline preview.
            marker = result.get("red_marker", {})
            point = marker.get("point")
            stop = result.get("checks", {}).get("stop_line", {})
            center_line = result.get("checks", {}).get("center_line", {})
            center_points = center_line.get("line_groups", [])
            guide = result.get("checks", {}).get("guidance_lines", {})
            guide_groups = guide.get("groups", [])
            paths = result.get("checks", {}).get("approach_paths", {})
            path_groups = paths.get("groups", [])
            arrow_candidates = result.get("checks", {}).get("road_arrows", {})
            arrow_items = arrow_candidates.get("candidates", [])
            original_white = result.get("checks", {}).get("white_marking_candidates_raw")
            after_ui_white = result.get("checks", {}).get("white_marking_candidates_after_ui")
            ui_text = result.get("checks", {}).get("ui_text_exclusion", {})
            white_raw = result.get("checks", {}).get("white_marking_candidates")
            lane_line = result.get("checks", {}).get("lane_line", {})
            lane_points = lane_line.get("line_groups", [])
            dashed_lane = result.get("checks", {}).get("dashed_lane_line", {})
            dashed_points = dashed_lane.get("line_groups", [])
            diagnostics = marker.get("diagnostics", {})
            location = result.get("location", {})
            marker_text = (
                f"현재 위치 후보: ({point[0]:.1f}, {point[1]:.1f})px"
                if point is not None else "현재 위치 미확인"
            )
            candidates = stop.get("line_candidates", [])
            groups = stop.get("line_groups", [])
            omitted = int(stop.get("omitted_segments", 0) or 0)
            candidate_label = (
                f"선 후보 {len(candidates)}개 표시 / 총 {len(candidates) + omitted}개"
                if omitted else f"선 후보 {len(candidates)}개"
            )
            grouping_label = (
                f"선 그룹 후보 {len(groups)}개 / {candidate_label}"
                if stop.get("grouping_complete", True)
                else f"표시된 선 그룹 {len(groups)}개 / {candidate_label} (일부만 그룹화)"
            )
            white_status = (
                f"화살표 A {len(arrow_items)}개 · 흰색 W {white_raw.get('shown_segments', 0)}개 · 분류 보류"
                if white_raw is not None else
                f"실선 L {len(lane_points)}개 · 점선 D {len(dashed_points)}개"
            )
            self.individual_status.setText(
                f"개별 촬영 {result['revision']}회 · {marker_text} · "
                f"{grouping_label} · 중앙선 포인트 {len(center_points)}개 "
                f"· 유도선 U {len(guide_groups)}개 · 진입 경로 P {len(path_groups)}개 "
                f"· {white_status} · 사람 검수 필요"
            )
            details = [
                (
                    "검수 ID: 미확인 · 별도 임시 촬영으로 저장됨"
                    if result.get("unassigned")
                    else f"검수 ID: {result['case_id']}"
                ),
                f"위치 검출 상태: {marker.get('status', 'unknown')}",
                f"현재 위치: {point if point is not None else '판단 보류'} (이미지 픽셀)",
                f"검은 도면 영역: {location.get('canvas_bounds', '미확인')}",
                f"도면 중심: {location.get('canvas_center', '미확인')}",
                f"도면 중심 대비 이동량(px): {location.get('center_offset_px', '미확인')}",
                f"도면 내부 상대 위치: {location.get('canvas_normalized_point', '미확인')}",
                "실제 지도 좌표 / 현재 도로 / 진행 방향: 미확인",
                f"검출 근거: {marker.get('reason', '')}",
                "── 빨간 점 검출 단계별 진단 ──",
                f"HSV 원본 빨간 픽셀: {diagnostics.get('hsv_red_pixels', '미확인')}",
                f"원본 연결 객체: {diagnostics.get('raw_component_count', '미확인')}",
                f"3×3 OPENING 후 빨간 픽셀: {diagnostics.get('opening_pixels', '미확인')}",
                f"OPENING 후 연결 객체: {diagnostics.get('opened_component_count', '미확인')}",
                f"형태필터 통과: {diagnostics.get('accepted_count', '미확인')}",
                f"형태필터 탈락 내역: {diagnostics.get('rejected_by_rule', {})}",
                f"도면 중앙 근접 원본 객체(최대 8개): {diagnostics.get('raw_nearest_components', [])}",
                f"정지선: {stop.get('reason', '판단 보류')}",
                f"STOP ROI: {stop.get('roi', '미확인')}",
                f"GUIDE ROI: {guide.get('roi', '미확인')}",
                f"PATH ROI: {paths.get('roi', '미확인')}",
                f"정지선 하단 기준: {result.get('stop_line_reference',{}).get('status','미확인')} "
                f"({result.get('stop_line_reference',{}).get('reason','')})",
                f"STOP 상단 GUIDE 비율: {stop.get('roi_rules',{}).get('guide_fraction','미확인')}",
                f"중앙선·흰선 내부 탐색: {result.get('candidate_search_bounds','미확인')} "
                "(별도 ROI 테두리 없음)",
                f"시안색 선 후보: {candidate_label} (실제 정지선 개수 아님)",
                f"기하학적 선 그룹: {len(groups)}개 (정지선 수 확정 아님)",
                f"그룹화 기준: {stop.get('grouping_rules', '미확인')}",
                "── 선 그룹 (G) · 구성 선 조각 (S) ──",
            ]
            for group in groups:
                details.append(
                    f"  {group['group_id']}: {', '.join(group['member_ids'])} "
                    f"· {group['member_count']}조각 "
                    f"· 방향 {group['angle_deg']:.1f}° ({group['orientation']}) "
                    f"· 길이 {group['length_px']:.1f}px "
                    f"· 통합 좌표 {group['endpoints']}"
                )
            if omitted:
                details.append(f"※ 선 조각 {omitted}개는 표시 상한(24개) 때문에 생략됨")
            for i, candidate in enumerate(candidates, 1):
                details.append(
                    f"  {candidate.get('candidate_id', f'S{i}')}. 좌표 "
                    f"{candidate['endpoints']} 길이 {candidate['length_px']}px "
                    f"그룹 {candidate.get('group_id', '미할당')}"
                )
            details.append("── 노란 중앙선 포인트 후보 (C) ──")
            details.append(
                f"중앙선: {center_line.get('reason', '판단 보류')}"
            )
            details.append(
                f"노란 선 조각 {center_line.get('shown_segments', 0)}/"
                f"{center_line.get('total_segments', 0)}개, "
                f"포인트 {center_line.get('shown_points', 0)}/"
                f"{center_line.get('group_count', 0)}개 표시 (확정 개수 아님)"
            )
            for group in center_points:
                details.append(
                    f"  {group['group_id']}: 포인트 {group['point']}px · "
                    f"방향 {group['orientation']} ({group['angle_deg']:.1f}°) · "
                    f"길이 {group['length_px']:.1f}px · 조각 {', '.join(group['member_ids'])}"
                )
            if center_line.get('omitted_points', 0):
                details.append(
                    f"※ 중앙선 포인트 {center_line['omitted_points']}개는 표시 상한으로 생략됨"
                )
            details.append("── 검수 범위별 후보 · 근거 이미지 테두리 ──")
            for kind, spec in result.get("review_regions", {}).items():
                details.append(
                    f"  {kind}: 후보 {spec.get('candidate_count', 0)}개 · "
                    f"ROI {spec.get('roi')} · {spec.get('border')}"
                )
            details.append("※ 교차로 외곽 RGB(0,0,255)는 검출 후보에서 제외하며 원본 유지")
            details.append("── 유도선 파랑 RGB(0,128,255) 연결 그룹 (U) ──")
            details.append(
                f"유도선: {guide.get('reason', '과거 기록 또는 분석 보류')}"
            )
            details.append(
                f"GUIDE ROI: {guide.get('roi', '미확인')} · "
                f"후보 그룹 {guide.get('group_count', 0)}개 · "
                f"색상별 {guide.get('color_counts', {})}"
            )
            details.append(
                f"색상표: {guide.get('palette', '미확인')} · "
                f"그룹 기준: {guide.get('grouping', '미확인')}"
            )
            for group in guide_groups:
                details.append(
                    f"  {group['group_id']}: {group['label']} "
                    f"RGB {group['color_rgb']} · 중심 {group['point']}px · "
                    f"외곽 {group['bbox']} · 연결 영역 "
                    f"{group['connected_pixels']}px · 실제 색상 픽셀 "
                    f"{group['original_color_pixels']}px"
                )
            details.append("── 진입 전 경로선 RGB(121,171,255) 연결 그룹 (P) ──")
            details.append(
                f"PATH ROI: {paths.get('roi', '미확인')} · "
                f"후보 {paths.get('group_count', 0)}개 · "
                f"{paths.get('reason', '판단 보류')}"
            )
            for group in path_groups:
                details.append(
                    f"  {group['candidate_id']}: 대표점 {group['point']}px · "
                    f"외곽 {group['bbox']} · 연결 픽셀 {group['connected_pixels']}"
                )
            if road_arrows := (arrow_candidates if arrow_candidates else None):
                details.append("── 노면화살표 검출 후보 (A · 검수 필요) ──")
                details.append(
                    f"화살표 후보 {road_arrows.get('candidate_count', 0)}개 · "
                    f"초록 외곽 기준 제외영역 {road_arrows.get('excluded_region_pixels', 0)}px · "
                    f"포함 흰색 {road_arrows.get('excluded_white_pixels', 0)}px"
                )
                details.append(f"검출 결과: {road_arrows.get('reason', '판단 보류')}")
                for item in arrow_items:
                    details.append(
                        f"  {item['candidate_id']}: 중심 {item['point']}px · "
                        f"회전 {item['angle_deg']:.1f}° · 외곽 {item['polygon']} · "
                        f"회색 {item['gray_pixels']}px / 초록 테두리 "
                        f"{item['green_edge_pixels']}px / 흰색 {item['white_pixels']}px "
                        f"· 마스킹 {item.get('mask_bbox')} (여유 {item.get('mask_margin_px', 0)}px)"
                    )
            if white_raw is not None:
                details.append("── 흰색 선 조각 W (UI 문자·화살표 제외 후 · 미분류) ──")
                if original_white is not None:
                    details.append(
                        f"원본 W {original_white.get('total_segments', 0)}개 → "
                        f"문자 제외 후 W {after_ui_white.get('total_segments', '미확인') if after_ui_white else '미확인'}개 → "
                        f"화살표 제외 후 W {white_raw.get('total_segments', 0)}개"
                    )
                if ui_text:
                    details.append(
                        f"상단 UI 문자 흰색 제외: {ui_text.get('excluded_white_pixels', 0)}px · "
                        f"영역 {ui_text.get('regions', [])}"
                    )
                details.append(f"흰색 검출: {white_raw.get('reason', '판단 보류')}")
                details.append(
                    f"제외 영역과 겹친 W 선분 제거: "
                    f"{white_raw.get('rejected_mask_overlap_segments', 0)}개"
                )
                details.append(
                    f"원시 선 조각 {white_raw.get('shown_segments', 0)}/"
                    f"{white_raw.get('total_segments', 0)}개 "
                    f"(실선·점선·기타 오브젝트 미분류)"
                )
                details.append(
                    f"검출 조건: {white_raw.get('detection_rules', '미확인')}"
                )
                for item in white_raw.get("line_candidates", []):
                    details.append(
                        f"  {item['candidate_id']}: 포인트 {item['point']}px · "
                        f"방향 {item['orientation']} ({item['angle_deg']:.1f}°) · "
                        f"길이 {item['length_px']:.1f}px · 좌표 {item['endpoints']}"
                    )
                if white_raw.get("omitted_segments", 0):
                    details.append(
                        f"※ 흰색 원시 조각 {white_raw['omitted_segments']}개 표시 생략"
                    )
            else:
                details.append("── 흰색 차선 포인트 후보 (L) ──")
                details.append(f"차선: {lane_line.get('reason', '판단 보류')}")
                details.append(
                    f"흰색 선 조각 {lane_line.get('shown_segments', 0)}/"
                    f"{lane_line.get('total_segments', 0)}개, "
                    f"포인트 {lane_line.get('shown_points', 0)}/"
                    f"{lane_line.get('group_count', 0)}개 표시 (확정 개수 아님)"
                )
                for group in lane_points:
                    details.append(
                        f"  {group['group_id']}: 포인트 {group['point']}px · "
                        f"방향 {group['orientation']} ({group['angle_deg']:.1f}°) · "
                        f"길이 {group['length_px']:.1f}px · 조각 {', '.join(group['member_ids'])}"
                    )
                if lane_line.get('omitted_points', 0):
                    details.append(
                        f"※ 차선 포인트 {lane_line['omitted_points']}개는 표시 상한으로 생략됨"
                    )
                details.append("── 흰색 점선 후보 (D) ──")
                details.append(f"점선: {dashed_lane.get('reason', '판단 보류')}")
                details.append(
                    f"짧은 흰 선 조각 {dashed_lane.get('shown_segments', 0)}/"
                    f"{dashed_lane.get('total_segments', 0)}개, "
                    f"점선 포인트 {dashed_lane.get('shown_points', 0)}/"
                    f"{dashed_lane.get('group_count', 0)}개 (실제 차선 수 아님)"
                )
                details.append(
                    f"점선 그룹화 기준: {dashed_lane.get('grouping_rules', '미확인')}"
                )
                for group in dashed_points:
                    details.append(
                        f"  {group['group_id']}: 포인트 {group['point']}px · "
                        f"방향 {group['orientation']} ({group['angle_deg']:.1f}°) · "
                        f"공백 구간 {group.get('gaps_px', [])}px · "
                        f"반복 조각 {group.get('dash_count', '미확인')}개 · "
                        f"구성 {', '.join(group['member_ids'])}"
                    )
                if dashed_lane.get('omitted_points', 0):
                    details.append(
                        f"※ 점선 포인트 {dashed_lane['omitted_points']}개 표시 상한 생략"
                    )
            details.extend([
                "※ 선 후보는 정지선 확정이 아닙니다. 횡단보도/도로 경계를 구별하세요.",
                "※ A는 회색/초록/흰색으로 검출한 화살표 후보이며, 제외 전 W는 JSON에 보존합니다. 최종 판정은 수동입니다.",
                "※ 노란 선/포인트는 중앙선 검수용 후보이며 실제 중앙선 2개·4개를 확정하지 않습니다.",
                "※ U#/P#는 지정 RGB의 연결 집합 후보입니다. 실제 유도선·진입 경로로 확정하지 않습니다.",
                f"원본: {result['input_tool_image']}",
                f"근거: {result['input_tool_overlay']}",
                f"후보 미리보기: {result.get('input_tool_focus', '없음')}",
                f"보고서: individual_analysis.json",
            ])
            self.individual_details.setPlainText("\n".join(details))
            self.individual_details.verticalScrollBar().setValue(0)
            self.status_label.setText(
                "개별 촬영 저장 · 검수 ID 미확인 (최종 검수 필요)"
                if result.get("unassigned")
                else "개별 촬영 분석 완료 · 최종 검수 필요"
            )
            if result.get("unassigned"):
                self._log(
                    "검수 ID를 확인하지 못해 임시 촬영 폴더에 따로 저장했습니다. "
                    "정식 검수 ID와 자동 연결하지 않습니다.",
                    logging.WARNING,
                )
            self._log(
                f"개별 촬영 {result['revision']}회 · {marker_text} · "
                f"선 그룹 {len(groups)}개 / 시안색 선 조각 {len(candidates)}개"
            )
        elif kind == "staged_analysis":
            from map_validator.stage_types import STAGES, STAGE_LABELS, FIELD_LABELS

            summary = result["summary"]
            status_label = {
                "mismatch_review": "불일치 의심 · 직접 확인 필요",
                "partial_evidence_review": "일부 일치 후보 · 판단 보류 포함",
                "insufficient_evidence": "근거 부족 · 재확인 필요",
            }.get(summary["status"], "사람 검수 필요")
            self.geometry_result.setText(
                f"분석 {summary['captured_stages']}/4 · {status_label}"
            )
            labels = {
                "match_candidate": "일치 후보",
                "mismatch_review": "불일치 의심",
                "insufficient_evidence": "판단 보류",
                "not_applicable": "해당 없음",
            }
            road_scores = result.get("road_scores", {})
            before_scores = road_scores.get("before", {})
            after_scores = road_scores.get("after", {})

            def display_score(value) -> str:
                return "—" if value is None else f"{value:.4f}"

            lines = []
            if road_scores:
                directions = (("left", "좌"), ("straight", "직"), ("right", "우"))
                input_items = []
                geometry_items = []
                for direction, label in directions:
                    stage_item = result["stages"].get("after_" + direction, {})
                    expected = stage_item.get("input_expected", {}).get("road_exists", {})
                    value = self._format_feature(expected.get("value"))
                    confidence = expected.get("confidence")
                    score = "—" if confidence is None else f"{confidence:.2f}"
                    input_items.append(f"{label} {value} (후보 점수 {score})")
                    comparison = stage_item.get("comparison", {}).get("road_exists", {})
                    verdict = {
                        "match_candidate": "P",
                        "mismatch_review": "F",
                    }.get(comparison.get("status"), "N")
                    geometry_items.append(f"{label} {verdict}")
                lines.append("입력툴: " + "  |  ".join(input_items))
                lines.append("")
                lines.append("도로 선형: " + "  |  ".join(geometry_items))
                lines.append("")
                lines.append("※ P: 일치 후보 / F: 불일치 의심 / N: 판단 보류 · 최종 확인 필요")
                lines.append("")
                lines.append("※ 입력툴 점수는 색상 경로 후보의 고정 휴리스틱 점수이며 확률이 아닙니다.")
                lines.append("")
                lines.extend([
                    "[도로 영역 스코어 · 0~1, 높을수록 ROI 내 도로 픽셀 많음]",
                    "진입 전 : 좌 {0}  |  직 {1}  |  우 {2}".format(
                        display_score(before_scores.get("left")),
                        display_score(before_scores.get("straight")),
                        display_score(before_scores.get("right")),
                    ),
                    "진입 후 : 좌→정면 {0}  |  직→정면 {1}  |  우→정면 {2}".format(
                        display_score(after_scores.get("left", {}).get("straight_score")),
                        display_score(after_scores.get("straight", {}).get("straight_score")),
                        display_score(after_scores.get("right", {}).get("straight_score")),
                    ),
                    "※ 진입 후 도로 존재는 각 사진의 전방 중앙을 따로 확인합니다.",
                    "",
                ])
            for stage in STAGES:
                item = result["stages"][stage]
                lines.append(f"[{STAGE_LABELS[stage]}]")
                if item.get("capture_state") != "captured":
                    lines.append("  사진 부족 · 먼저 해당 단계 촬영 필요")
                    continue
                for field, comparison in item.get("comparison", {}).items():
                    exp = self._format_feature(comparison.get("expected_value"))
                    obs = self._format_feature(comparison.get("observed_value"))
                    if field == "stop_line":
                        verdict = {
                            "PASS": "PASS",
                            "FAIL": "FAIL",
                            "REVIEW": "검수 필요",
                        }.get(comparison.get("verdict"), "검수 필요")
                    else:
                        verdict = labels.get(comparison.get("status"), "확인 필요")
                    lines.append(
                        f"  {FIELD_LABELS[field]}: 입력툴 {exp} / 로드뷰 {obs}"
                        f"  → {verdict}"
                    )
                    if field == "stop_line" and comparison.get("verdict") == "REVIEW":
                        lines.append("    횡단보도와 구분이 어려우면 직접 확인하세요.")
                    if comparison.get("status") == "mismatch_review":
                        lines.append("    " + comparison.get("reason", ""))
            self.analysis_details.setPlainText("\n".join(lines))
            self.analysis_details.verticalScrollBar().setValue(0)
            self._scroll_to_results = True
            self.status_label.setText("단계별 분석 완료 · 최종 검수 필요")
            self._log(
                f"4단계 사진 {summary['captured_stages']}/4 분석 완료 · "
                f"{status_label}"
            )
            self._log(f"분석 결과: {Path(self.latest_folder) / 'staged_analysis.json'}")
            if result.get("score_files"):
                self._log(
                    "교차로 점수: {0}/6개 기록 · 통합 CSV: {1}".format(
                        road_scores.get("available_scores", 0),
                        result["score_files"]["all_cases_csv"],
                    )
                )
        else:
            self._log(f"미지원 결과 형식: {kind}")
        self._log(f"결과 폴더: {self.latest_folder}")
        self._log("최종 판정은 반드시 사용자가 진행해야 합니다.")

    def _done(self) -> None:
        self._restore_panel()
        scroll_position = self.steps_scroller.verticalScrollBar().value()
        show_results = self._scroll_to_results
        self._scroll_to_results = False
        self._busy(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if show_results:
            QTimer.singleShot(0, self._show_comparison_section)
        else:
            self.steps_scroller.verticalScrollBar().setValue(scroll_position)

    def _show_comparison_section(self) -> None:
        # Expand the independent result pane instead of scrolling capture controls.
        self.result_heading.setChecked(True)
        sizes = self.panel_splitter.sizes()
        if sizes[1] < 185 and sizes[0] > 145:
            grow = min(185 - sizes[1], sizes[0] - 145)
            sizes[0] -= grow
            sizes[1] += grow
            self.panel_splitter.setSizes(sizes)
        self.analysis_details.verticalScrollBar().setValue(0)

    def _open_individual_overlay(self) -> None:
        self.individual_controls.open_evidence(self._individual_overlay_path)

    def _open_folder(self) -> None:
        if self.latest_folder and Path(self.latest_folder).is_dir():
            if sys.platform == "win32":
                os.startfile(self.latest_folder)
            else:
                self._log("결과 폴더 열기는 Windows에서 지원합니다.")

    def _copy_logs(self) -> None:
        QApplication.clipboard().setText(self.logs.toPlainText())
        self._log("표시된 작업 로그를 클립보드에 복사했습니다.")

    def _open_logs_folder(self) -> None:
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))
        else:
            self._log("로그 폴더 열기는 Windows에서 지원합니다.", logging.WARNING)

    def _log(self, text: str, level: int = logging.INFO) -> None:
        APP_LOG.log(level, text, stacklevel=2)

    def _append_log_line(self, text: str) -> None:
        self.logs.append(text)
        bar = self.logs.verticalScrollBar()
        bar.setValue(bar.maximum())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.showMinimized()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._stop()
            self._log("작업 중입니다. 종료하려면 작업 중지 후 다시 닫아주세요.")
            event.ignore()
            return
        if self.review_monitor is not None and self.review_monitor.isRunning():
            if not self._close_pending:
                self._close_pending = True
                self.review_monitor.set_paused(True)
                self.review_monitor.requestInterruption()
                self.status_label.setText("선택 감시 종료 중")
                self._log("선택 감시 스레드 종료 요청")
            event.ignore()
            return
        APP_LOG.removeHandler(self._log_handler)
        self._log_handler.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    if not STYLE_FILE.exists():
        raise FileNotFoundError(f"UI 스타일 파일이 없습니다: {STYLE_FILE}")
    app.setStyleSheet(STYLE_FILE.read_text(encoding="utf-8"))
    app.setFont(QFont("Malgun Gothic", 10))
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
