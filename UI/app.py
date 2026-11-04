"""PyQt6 floating control panel, inspired by bluehawhy/nv_c_test's layout."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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
        self.latest_folder: str | None = None
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
        self.setFixedSize(470, 730)
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

        layout.addWidget(self._label("대상 설정", "section"))
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

        self.case_input = QLineEdit(
            self.cfg.get("ui", {}).get("last_case_id", "intersection_001")
        )
        self.case_input.setPlaceholderText("예: intersection_001")
        basic_grid.addWidget(self._label("검수 ID"), 2, 0)
        basic_grid.addWidget(self.case_input, 2, 1, 1, 2)
        basic_grid.setColumnStretch(1, 1)
        layout.addLayout(basic_grid)

        for field in (self.work_input, self.view_input, self.case_input):
            field.editingFinished.connect(self._save_settings)

        template_row = QHBoxLayout()
        self.template_input = QLineEdit(
            self.cfg["windows"].get("open_button_image", "assets/open_roadview.png")
        )
        self.template_input.setPlaceholderText("로드뷰 버튼 캡처 이미지 경로")
        self.template_input.setToolTip("업무 프로그램의 로드뷰 열기 버튼 이미지를 선택하세요.")
        browse = QPushButton("찾기")
        browse.clicked.connect(self._select_template)
        template_row.addWidget(self.template_input, 1)
        template_row.addWidget(browse)
        layout.addLayout(template_row)

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
        output_row.addWidget(self._label("저장 경로"))
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(output_browse)
        layout.addLayout(output_row)

        layout.addWidget(self._label("이동 및 분석", "section"))
        action_row = QHBoxLayout()
        self.move_combo = QComboBox()
        self.move_combo.addItem("이동 없음", "none")
        self.move_combo.addItem("W 전진", "forward")
        self.move_combo.addItem("S 후진", "backward")
        self.step_spin = QSpinBox()
        self.step_spin.setRange(0, max(0, int(self.cfg["movement"].get("max_steps", 5))))
        self.step_spin.setValue(min(2, self.step_spin.maximum()))
        action_row.addWidget(self._label("동작"))
        action_row.addWidget(self.move_combo, 1)
        action_row.addWidget(self._label("횟수"))
        action_row.addWidget(self.step_spin)
        layout.addLayout(action_row)

        self.open_first = QCheckBox("분석 시작 전에 업무 프로그램에서 로드뷰 열기")
        layout.addWidget(self.open_first)
        layout.addWidget(self._label("※ 좌우 시점 회전 없음 · 직진/노면표시 판정 없음", "hint"))

        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        self.open_btn = QPushButton("로드뷰 열기")
        self.capture_btn = QPushButton("캡처만")
        self.start_btn = QPushButton("좌·우 도로 후보 분석")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self._start("open"))
        self.capture_btn.clicked.connect(lambda: self._start("capture"))
        self.start_btn.clicked.connect(lambda: self._start("analyze"))
        self.stop_btn.clicked.connect(self._stop)
        actions.addWidget(self.open_btn, 0, 0)
        actions.addWidget(self.capture_btn, 0, 1)
        actions.addWidget(self.start_btn, 1, 0)
        actions.addWidget(self.stop_btn, 1, 1)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)

        layout.addWidget(self._label("분석 결과 (후보일 뿐, 확정 아님)", "section"))
        decision_row = QHBoxLayout()
        self.left_result = self._label("좌측: 대기", "decision")
        self.right_result = self._label("우측: 대기", "decision")
        decision_row.addWidget(self.left_result, 1)
        decision_row.addWidget(self.right_result, 1)
        layout.addLayout(decision_row)

        layout.addWidget(self._label("작업 로그", "section"))
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(100)
        layout.addWidget(self.logs, 1)

        footer = QHBoxLayout()
        self.save_btn = QPushButton("설정 저장")
        self.folder_btn = QPushButton("결과 폴더")
        self.folder_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_settings)
        self.folder_btn.clicked.connect(self._open_folder)
        footer.addWidget(self.save_btn)
        footer.addWidget(self.folder_btn)
        footer.addStretch(1)
        layout.addLayout(footer)
        self._log("준비 완료. 캡처 전에 로드뷰 창 제목을 확인하세요.")

    @staticmethod
    def _program_title(window_title: str) -> str:
        """Remove per-workspace suffixes while keeping a stable program title."""
        title = window_title.strip()
        if " - " in title:
            title = title.split(" - ", 1)[0].strip()
        return title

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
                target.restore()
            target.activate()
        except Exception as exc:
            self._log(f"{label} 선택 실패: {exc}")

    def _select_template(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "로드뷰 버튼 이미지 선택", str(ROOT), "Images (*.png *.jpg *.jpeg)"
        )
        if filename:
            try:
                self.template_input.setText(str(Path(filename).relative_to(ROOT)))
            except ValueError:
                self.template_input.setText(filename)

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

    def _start_review_monitor(self) -> None:
        self.review_timer = QTimer(self)
        self.review_timer.setInterval(900)
        self.review_timer.timeout.connect(self._refresh_selected_review_id)
        self.review_timer.start()

    def _refresh_selected_review_id(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        review_title = self.cfg.get("windows", {}).get(
            "intersection_review_title", ""
        ).strip()
        if not review_title:
            return

        try:
            import pygetwindow as gw
            from map_validator.windows import read_selected_intersection_id

            active = gw.getActiveWindow()
            if active is None or not active.title.strip():
                return

            comparable = lambda value: re.sub(
                r"[^0-9a-z가-힣]+", "", value.casefold()
            )
            if comparable(review_title) not in comparable(active.title):
                return

            review_id = read_selected_intersection_id(review_title)
            if review_id == self.case_input.text().strip():
                return

            self.case_input.setText(review_id)
            cfg = self._current_settings()
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self.cfg = cfg
            self._log(f"검수 ID 자동 업데이트: {review_id}")
        except Exception:
            # Selection can be momentarily empty while the user changes tree items.
            return

    def _current_settings(self) -> dict:
        cfg = self._read_settings()
        cfg.setdefault("windows", {})
        cfg.setdefault("output", {})
        cfg.setdefault("ui", {})
        cfg["windows"]["work_title"] = self.work_input.text().strip()
        cfg["windows"]["roadview_title"] = self.view_input.text().strip()
        cfg["windows"]["open_button_image"] = self.template_input.text().strip()
        cfg["output"]["directory"] = self.output_input.text().strip() or "results"
        cfg["ui"]["last_case_id"] = self.case_input.text().strip()
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
            self._log(f"설정 저장 실패: {exc}")

    def _start(self, action: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            cfg = self._current_settings()
            if action == "analyze":
                review_title = cfg["windows"].get("intersection_review_title", "").strip()
                if not review_title:
                    raise ValueError("config.yaml에 입력 교차로 타이틀을 설정하세요.")
                from map_validator.windows import read_selected_intersection_id

                case_id = read_selected_intersection_id(review_title)
                self.case_input.setText(case_id)
                self._save_settings()
                cfg = self._current_settings()
                self._log(f"선택 교차로 검수 ID: {case_id}")
            else:
                case_id = self.case_input.text().strip()

            if not case_id:
                raise ValueError("검수 ID를 입력하세요.")
            if not cfg["windows"]["roadview_title"].strip() and action != "open":
                raise ValueError("로드뷰 창 제목을 입력하세요.")
            if not cfg["windows"]["work_title"].strip() and (
                action == "open" or self.open_first.isChecked()
            ):
                raise ValueError("업무 창 제목을 입력하세요.")
            self.cfg = cfg
            from .worker import ControlWorker

            self.worker = ControlWorker(
                config=cfg,
                config_dir=ROOT,
                case_id=case_id,
                action=action,
                movement=self.move_combo.currentData(),
                steps=self.step_spin.value(),
                open_first=self.open_first.isChecked() if action != "open" else False,
                parent=self,
            )
            self.worker.message.connect(self._log)
            self.worker.progress.connect(self.status_label.setText)
            self.worker.result_ready.connect(self._show_result)
            self.worker.hide_panel.connect(self._hide_for_capture)
            self.worker.show_panel.connect(self._restore_panel)
            self.worker.finished.connect(self._done)
            self._busy(True)
            self.left_result.setText("좌측: 분석 전")
            self.right_result.setText("우측: 분석 전")
            self.status_label.setText("진행 중")
            self._log(f"시작: {action} / {case_id}")
            self.worker.start()
        except Exception as exc:
            self._log(f"시작 실패: {exc}")

    def _busy(self, busy: bool) -> None:
        for widget in (
            self.open_btn, self.capture_btn, self.start_btn, self.save_btn,
            self.case_input, self.work_input, self.view_input, self.template_input,
            self.work_select_btn, self.view_select_btn, self.output_input,
            self.move_combo, self.step_spin, self.open_first,
        ):
            widget.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _hide_for_capture(self) -> None:
        self.hide()
        if self.worker is not None:
            self.worker.acknowledge_hidden()

    def _restore_panel(self) -> None:
        if not self.isVisible():
            self.show()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self._log("중지 요청: 현재 캡처 또는 AI 처리 단위 종료 후 중단됩니다.")
            self.status_label.setText("중지 요청됨")

    def _result_text(self, code: str) -> str:
        return {
            "possible": "도로 후보 감지 (검토)",
            "not_detected_review_required": "후보 미감지 (검토)",
            "not_analyzed": "미분석",
        }.get(code, "확인 필요")

    def _show_result(self, result: dict) -> None:
        if "folder" not in result:
            self._log(result.get("message", "완료"))
            return
        self.left_result.setText("좌측: " + self._result_text(result["left"]))
        self.right_result.setText("우측: " + self._result_text(result["right"]))
        self.latest_folder = result["folder"]
        self.folder_btn.setEnabled(True)
        self._log(f"완료: {result['frames']}개 화면 저장")
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

    def _log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {text}")
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
