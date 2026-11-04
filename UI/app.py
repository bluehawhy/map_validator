"""PyQt6 floating control panel, inspired by bluehawhy/nv_c_test's layout."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PyQt6.QtCore import Qt
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
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
EXAMPLE = ROOT / "config.example.yaml"

STYLE = """
QWidget#panel {
    background-color: rgba(243, 243, 243, 246);
    border-radius: 20px;
    border: 1px solid rgba(225, 228, 232, 215);
}
QWidget#header, QWidget#body, QWidget#content { background: transparent; }
QLabel { color: #313C45; background: transparent; font-size: 11px; }
QLabel#title { color: #263540; font-size: 16px; font-weight: bold; }
QLabel#status {
    color: #2871A3; background: rgba(255,255,255,125);
    border-radius: 7px; padding: 5px 8px; font-weight: bold;
}
QLabel#hint { color: #71808B; font-size: 10px; }
QLabel#section { font-weight: bold; color: #44525D; padding-top: 5px; }
QLabel#decision { color: #53616D; font-weight: bold; }
QLineEdit, QComboBox, QSpinBox {
    color: #263540; background-color: rgba(255, 255, 255, 185);
    border: 1px solid rgba(200, 205, 210, 180);
    border-radius: 8px; padding: 6px 7px; font-size: 11px;
    min-height: 19px;
}
QComboBox::drop-down { border: 0px; width: 18px; }
QCheckBox { color: #53616D; background: transparent; font-size: 11px; spacing: 7px; }
QPushButton {
    color: #46545E; background-color: rgba(255, 255, 255, 190);
    border: 1px solid rgba(205, 211, 216, 140);
    border-radius: 8px; padding: 7px; font-size: 11px;
}
QPushButton:hover { background-color: rgba(228, 240, 247, 235); }
QPushButton:disabled { color: #AAB2B9; background-color: rgba(255,255,255,95); }
QPushButton#primary { background: #3683B4; color: white; font-weight: bold; border: none; }
QPushButton#primary:hover { background: #2573A7; }
QPushButton#danger { color: #C34F4F; }
QPushButton#header_button { min-width: 22px; max-width: 22px; padding: 1px; }
QTextEdit {
    color: #40505B; background: rgba(255, 255, 255, 125);
    border: 1px solid rgba(220, 223, 226, 140);
    border-radius: 9px; font-size: 11px; padding: 6px;
}
"""


class DragHeader(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._last_pos = None
        self.setObjectName("header")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pos = event.globalPosition().toPoint()
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
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker = None
        self.latest_folder: str | None = None
        self.cfg = self._read_settings()
        self._setup()

    def _read_settings(self) -> dict:
        if not EXAMPLE.exists():
            raise FileNotFoundError(f"설정 예제 파일이 없습니다: {EXAMPLE}")

        defaults = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        if not isinstance(defaults, dict):
            raise ValueError("설정 예제 YAML 내용이 올바르지 않습니다.")
        if not CONFIG.exists():
            return defaults

        saved = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("config.yaml 내용이 올바르지 않습니다.")

        def merge(base: dict, override: dict) -> dict:
            result = dict(base)
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key] = merge(result[key], value)
                else:
                    result[key] = value
            return result

        return merge(defaults, saved)

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
        self.setFixedSize(428, 730)
        outer = QWidget()
        outer.setObjectName("panel")
        outer.setStyleSheet(STYLE)
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(18, 14, 18, 15)
        layout.setSpacing(8)

        header = DragHeader()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self._label("🛣  map_validator", "title"))
        header_layout.addStretch(1)
        for label, callback in (("—", self.showMinimized), ("×", self.close)):
            btn = QPushButton(label)
            btn.setObjectName("header_button")
            btn.setFixedSize(25, 23)
            btn.clicked.connect(callback)
            header_layout.addWidget(btn)
        layout.addWidget(header)

        self.status_label = self._label("준비됨 | 현장 최종 검수 필요", "status")
        layout.addWidget(self.status_label)

        layout.addWidget(self._label("대상 설정", "section"))
        basic_grid = QGridLayout()
        basic_grid.setHorizontalSpacing(8)
        basic_grid.setVerticalSpacing(6)
        self.case_input = QLineEdit("intersection_001")
        self.case_input.setPlaceholderText("예: intersection_001")
        basic_grid.addWidget(self._label("검수 ID"), 0, 0)
        basic_grid.addWidget(self.case_input, 0, 1)
        self.work_input = QLineEdit(self.cfg["windows"].get("work_title", ""))
        basic_grid.addWidget(self._label("업무 창 제목"), 1, 0)
        basic_grid.addWidget(self.work_input, 1, 1)
        self.view_input = QLineEdit(self.cfg["windows"].get("roadview_title", ""))
        basic_grid.addWidget(self._label("로드뷰 창 제목"), 2, 0)
        basic_grid.addWidget(self.view_input, 2, 1)
        basic_grid.setColumnStretch(1, 1)
        layout.addLayout(basic_grid)

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

    def _current_settings(self) -> dict:
        cfg = self._read_settings()
        cfg.setdefault("windows", {})
        cfg.setdefault("output", {})
        cfg["windows"]["work_title"] = self.work_input.text().strip()
        cfg["windows"]["roadview_title"] = self.view_input.text().strip()
        cfg["windows"]["open_button_image"] = self.template_input.text().strip()
        cfg["output"]["directory"] = self.output_input.text().strip() or "results"
        return cfg

    def _save_settings(self) -> None:
        try:
            cfg = self._current_settings()
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self.cfg = cfg
            self._log("로컬 config.yaml 저장 완료 (Git에는 업로드되지 않음)")
        except Exception as exc:
            self._log(f"설정 저장 실패: {exc}")

    def _start(self, action: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            case_id = self.case_input.text().strip()
            if not case_id:
                raise ValueError("검수 ID를 입력하세요.")
            cfg = self._current_settings()
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
            self.output_input, self.move_combo, self.step_spin, self.open_first,
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

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._stop()
            self._log("작업 중입니다. 종료하려면 작업 중지 후 다시 닫아주세요.")
            event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
