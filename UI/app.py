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
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QFrame,
    QDoubleSpinBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
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
        self.review_monitor = None
        self._close_pending = False
        self.latest_folder: str | None = None
        self._displayed_case_id = ""
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
        self.setMinimumSize(485, 590)
        self.resize(510, 740)
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

        self.status_label = self._label("준비됨 | 현장 최종 검수 필요", "status")
        layout.addWidget(self.status_label)

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
        basic_grid.addWidget(self.case_input, 2, 1, 1, 2)
        basic_grid.setColumnStretch(1, 1)
        layout.addLayout(basic_grid)

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
        output_row.addWidget(self._label("저장 경로"))
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(output_browse)
        layout.addLayout(output_row)

        # Keep stage controls accessible on smaller displays. Only the
        # map_validator panel may resize; neither target application is touched.
        steps_scroller = QScrollArea()
        steps_scroller.setFrameShape(QFrame.Shape.NoFrame)
        steps_scroller.setWidgetResizable(True)
        steps_scroller.setObjectName("stageScroller")
        content = QWidget()
        content.setObjectName("content")
        sections = QVBoxLayout(content)
        sections.setContentsMargins(1, 0, 4, 0)
        sections.setSpacing(6)
        steps_scroller.setWidget(content)
        layout.addWidget(steps_scroller, 2)

        from map_validator.stage_types import STAGES, STAGE_BUTTONS, STAGE_LABELS

        sections.addWidget(self._label("1. 단계별 수동 촬영", "section"))
        sections.addWidget(self._label(
            "※ 각 방향은 도로가 없어도 촬영하세요. 위치·시점은 직접 조정합니다.", "hint"
        ))
        self.stage_buttons = {}
        self.stage_status_labels = {}
        for stage in STAGES:
            row = QHBoxLayout()
            button = QPushButton(STAGE_BUTTONS[stage])
            button.setToolTip(
                f"{STAGE_LABELS[stage]}의 현재 HD_3D Tool/로드뷰 화면을 각각 1장 저장"
            )
            button.clicked.connect(
                lambda checked=False, selected=stage: self._start(
                    "capture_" + selected
                )
            )
            status = self._label("미촬영", "hint")
            status.setMinimumWidth(112)
            row.addWidget(button, 3)
            row.addWidget(status, 2)
            sections.addLayout(row)
            self.stage_buttons[stage] = button
            self.stage_status_labels[stage] = status

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(self._label("로드뷰 정지선 threshold", "hint"))
        self.stop_line_threshold = QDoubleSpinBox()
        self.stop_line_threshold.setRange(0.35, 0.95)
        self.stop_line_threshold.setSingleStep(0.05)
        self.stop_line_threshold.setDecimals(2)
        self.stop_line_threshold.setValue(
            max(0.35, min(0.95, float(
                self.cfg.get("analysis", {}).get("stop_line_roadview_threshold", 0.68)
            )))
        )
        self.stop_line_threshold.setToolTip(
            "로드뷰 단독 흰색 정지선의 최소 검출 신뢰도. "
            "높일수록 엄격하게 판정하며 횡단보도는 정지선에서 제외합니다."
        )
        # Save after editing, not on every spinbox increment/keystroke.
        self.stop_line_threshold.editingFinished.connect(self._save_settings)
        threshold_row.addWidget(self.stop_line_threshold)
        threshold_row.addStretch(1)
        sections.addLayout(threshold_row)

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

        sections.addWidget(self._label("2. 항목별 비교 결과 (검수 보조)", "section"))
        self.geometry_result = self._label("분석 전 · 최종 사람 검수 필요", "decision")
        sections.addWidget(self.geometry_result)
        self.analysis_details = QTextEdit()
        self.analysis_details.setReadOnly(True)
        self.analysis_details.setMinimumHeight(115)
        self.analysis_details.setPlaceholderText(
            "진입 전: 정지선 / 차로 수 / 화살표 / 컬러유도선\n"
            "진입 후 좌·직·우: 도로 유무 / 차로 수 / 일반·컬러유도선"
        )
        sections.addWidget(self.analysis_details, 1)

        layout.addWidget(self._label("작업 로그", "section"))
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(78)
        layout.addWidget(self.logs, 1)
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
        self._log("준비 완료. 진입 전→좌→직→우 네 방향을 각각 수동 촬영하세요.")

    @staticmethod
    def _program_title(window_title: str) -> str:
        """Remove per-workspace suffixes while keeping a stable program title."""
        title = window_title.strip()
        if " - " in title:
            title = title.split(" - ", 1)[0].strip()
        return title

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

    def _start_review_monitor(self) -> None:
        from .review_monitor import ReviewSelectionMonitor

        review_title = self.cfg.get("windows", {}).get(
            "intersection_review_title", ""
        ).strip()
        if not review_title:
            return
        self.review_monitor = ReviewSelectionMonitor(review_title, self)
        self.review_monitor.selection_changed.connect(self._on_review_selection)
        self.review_monitor.finished.connect(self._on_review_monitor_finished)
        self.review_monitor.start()

    def _on_review_selection(self, review_id: str) -> None:
        if self._close_pending or (
            self.worker is not None and self.worker.isRunning()
        ):
            return
        if review_id != self.case_input.text().strip():
            self.case_input.setText(review_id)
            self.geometry_result.setText("새 검수 ID · 촬영/분석 전")
            self.analysis_details.clear()
            self._log(f"검수 ID 자동 업데이트: {review_id}")

    def _on_review_monitor_finished(self) -> None:
        if self._close_pending:
            QTimer.singleShot(0, self.close)

    def _on_analysis_case_id(self, case_id: str) -> None:
        self.case_input.setText(case_id)

    def _current_settings(self) -> dict:
        cfg = self._read_settings()
        cfg.setdefault("windows", {})
        cfg.setdefault("output", {})
        cfg.setdefault("ui", {})
        cfg.setdefault("analysis", {})
        cfg["analysis"]["stop_line_roadview_threshold"] = round(
            self.stop_line_threshold.value(), 2
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
        states = {
            "not_captured": "미촬영",
            "partial_capture": "일부 누락",
            "captured": "촬영 완료",
        }
        for stage in STAGES:
            label = self.stage_status_labels.get(stage)
            if label is not None:
                label.setText("미촬영")
        if folder is None:
            return
        try:
            manifest = read_manifest(folder, self.case_input.text().strip())
            for stage in STAGES:
                record = manifest["stages"][stage]
                current = stage_status(folder, record)
                revision = record.get("revision", 0)
                suffix = f" · {revision}회" if current == "captured" else ""
                self.stage_status_labels[stage].setText(
                    states.get(current, "확인 필요") + suffix
                )
            if folder.is_dir():
                self.latest_folder = str(folder)
                self.folder_btn.setEnabled(True)
            else:
                self.latest_folder = None
                self.folder_btn.setEnabled(False)
        except Exception as exc:
            log_exception_at_source(APP_LOG, "검수 단계 상태 읽기 실패", exc)

    def _start(self, action: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            from map_validator.stage_types import STAGES

            valid = {"analyze_staged"} | {"capture_" + stage for stage in STAGES}
            if action not in valid:
                raise ValueError(f"지원하지 않는 작업입니다: {action}")
            cfg = self._current_settings()
            case_id = self.case_input.text().strip()
            if not case_id and not cfg["windows"].get(
                "intersection_review_title", ""
            ).strip():
                raise ValueError(
                    "검수 ID가 없습니다. 교차로 선형 검수에서 Polygon/Link를 선택하세요."
                )
            if action != "analyze_staged":
                if not cfg["windows"]["roadview_title"].strip():
                    raise ValueError("로드뷰 창 제목을 입력하세요.")
                if not cfg["windows"]["work_title"].strip():
                    raise ValueError("업무 창 제목을 입력하세요.")
            self.cfg = cfg
            from .worker import ControlWorker

            self.worker = ControlWorker(
                config=cfg, config_dir=ROOT, case_id=case_id,
                action=action, parent=self,
            )
            self.worker.progress.connect(self.status_label.setText)
            self.worker.case_id_ready.connect(self._on_analysis_case_id)
            self.worker.result_ready.connect(self._show_result)
            self.worker.show_panel.connect(self._restore_panel)
            self.worker.finished.connect(self._done)
            self._busy(True)
            self.status_label.setText("진행 중")
            self._log(f"시작: {action} / {case_id or '교차로 선택값 조회 중'}")
            self.worker.start()
        except Exception as exc:
            log_exception_at_source(APP_LOG, "시작 실패", exc)

    def _busy(self, busy: bool) -> None:
        for widget in (
            *self.stage_buttons.values(), self.start_btn, self.save_btn,
            self.stop_line_threshold,
            self.case_input, self.work_input, self.view_input,
            self.work_select_btn, self.view_select_btn, self.window_info_btn,
            self.output_input,
        ):
            widget.setEnabled(not busy)
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
                    route = stage_item.get("route_candidate", {})
                    angle = route.get("turn_angle_deg")
                    if route.get("status") == "candidate" and angle is not None:
                        geometry = f"{angle:.1f}° 후보"
                    else:
                        geometry = "판독 보류"
                    geometry_items.append(f"{label} {geometry} / 코드 판독 불가")
                lines.append("입력툴: " + "  |  ".join(input_items))
                lines.append("도로 선형: " + "  |  ".join(geometry_items))
                lines.append("※ 입력툴 점수는 색상 경로 후보의 고정 휴리스틱 점수이며 확률이 아닙니다.")
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
        self._busy(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

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
