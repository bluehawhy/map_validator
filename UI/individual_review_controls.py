"""Stored individual WGC capture selector and collapsible review controls."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)


class IndividualReviewControls(QWidget):
    selection_changed = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(7)

        layout.addWidget(QLabel("개별촬영"))
        self.capture_button = QPushButton("개별 촬영")
        self.capture_button.setObjectName("primary")
        self.capture_button.setToolTip("현재 HD_3D Tool 화면을 WGC로 촬영해 원본만 보존합니다.")
        layout.addWidget(self.capture_button)

        self.list_toggle = QPushButton("▾  항목 목록")
        self.list_toggle.setCheckable(True)
        self.list_toggle.setChecked(True)
        self.list_toggle.setObjectName("section_toggle")
        layout.addWidget(self.list_toggle)
        self.list_body = QWidget()
        selection_row = QHBoxLayout(self.list_body)
        selection_row.setContentsMargins(2, 0, 2, 0)
        selection_row.addWidget(QLabel("항목"))
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.setMinimumWidth(0)
        self.combo.setToolTip("설정된 저장 경로의 개별 촬영 폴더와 사진 버전")
        selection_row.addWidget(self.combo, 1)
        self.refresh_button = QPushButton("새로고침")
        selection_row.addWidget(self.refresh_button)
        layout.addWidget(self.list_body)
        self.list_toggle.toggled.connect(
            lambda expanded: self._toggle(self.list_toggle, self.list_body, "항목 목록", expanded)
        )
        self.combo.currentIndexChanged.connect(self._selection_updated)

        self.analyze_button = QPushButton("정지선 분석")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.setEnabled(False)
        layout.addWidget(self.analyze_button)
        self.status_label = QLabel("촬영 항목을 선택한 뒤 분석하세요.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.text_toggle = QPushButton("▾  후보 분석 텍스트")
        self.text_toggle.setCheckable(True)
        self.text_toggle.setChecked(True)
        self.text_toggle.setObjectName("section_toggle")
        layout.addWidget(self.text_toggle)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("분석된 정지선 S/G 및 노란 중앙선 C 포인트가 표시됩니다.")
        layout.addWidget(self.details, 1)
        self.text_toggle.toggled.connect(
            lambda expanded: self._toggle(self.text_toggle, self.details, "후보 분석 텍스트", expanded)
        )
        self.overlay_button = QPushButton("근거 이미지 보기")
        self.overlay_button.setEnabled(False)
        layout.addWidget(self.overlay_button)
        self._overlay_path: Path | None = None
        self.overlay_button.clicked.connect(self._open_current_evidence)
        layout.addStretch(1)
        self._root = Path(".")

    @staticmethod
    def _toggle(button: QPushButton, body: QWidget, title: str, expanded: bool) -> None:
        body.setVisible(expanded)
        button.setText(("▾  " if expanded else "▸  ") + title)

    def current_selection(self) -> tuple[Path, int] | None:
        item = self.combo.currentData()
        if not item:
            return None
        return Path(item[0]), int(item[1])

    def reload(self, output_root: Path, preferred=None) -> None:
        self._root = output_root
        previous = preferred or self.current_selection()
        saved = ((str(previous[0]), int(previous[1])) if previous else None)
        candidates = []
        if output_root.is_dir():
            locations = [p for p in output_root.iterdir()
                         if p.is_dir() and not p.is_symlink()
                         and p.name != "_unassigned_individual"]
            temporary = output_root / "_unassigned_individual"
            if temporary.is_dir() and not temporary.is_symlink():
                locations.extend(p for p in temporary.iterdir()
                                 if p.is_dir() and not p.is_symlink())
            for folder in locations:
                manifest_file = folder / "individual_capture.json"
                if not manifest_file.is_file():
                    continue
                try:
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    if manifest.get("case_id") != folder.name:
                        continue
                    for entry in manifest.get("history", []):
                        revision = int(entry.get("revision", -1))
                        if revision < 1:
                            continue
                        raw = folder / "captures" / "individual" / f"input_tool_r{revision:03d}.png"
                        if raw.is_file() and not raw.is_symlink():
                            candidates.append((folder, revision))
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        candidates.sort(key=lambda item: (item[0].name.casefold(), item[1]), reverse=True)
        self.combo.blockSignals(True)
        self.combo.clear()
        chosen = -1
        for i, (folder, revision) in enumerate(candidates):
            self.combo.addItem(f"{folder.name}  ·  r{revision:03d}", (str(folder), revision))
            if saved == (str(folder), revision):
                chosen = i
        if candidates:
            self.combo.setCurrentIndex(chosen if chosen >= 0 else 0)
        else:
            self.combo.setPlaceholderText("저장된 개별 촬영 없음")
        self.combo.blockSignals(False)
        self._selection_updated()

    def _selection_updated(self, _index=None) -> None:
        selection = self.current_selection()
        self.analyze_button.setEnabled(selection is not None)
        self.selection_changed.emit(selection)

    def set_overlay(self, path: Path | None) -> None:
        self._overlay_path = path
        self.overlay_button.setEnabled(path is not None and path.is_file())

    def _open_current_evidence(self) -> None:
        self.open_evidence(self._overlay_path)

    def open_evidence(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.status_label.setText("근거 이미지를 불러올 수 없습니다.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"근거 이미지 · {path.name}")
        dialog.resize(1050, 750)
        dialog_layout = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(False)
        image = QLabel()
        image.setPixmap(pixmap)
        image.setFixedSize(pixmap.size())
        scroll.setWidget(image)
        dialog_layout.addWidget(scroll)
        close = QPushButton("닫기")
        close.clicked.connect(dialog.accept)
        dialog_layout.addWidget(close)
        dialog.exec()
