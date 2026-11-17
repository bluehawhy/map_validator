"""Stored individual WGC capture selector and collapsible review controls."""
from __future__ import annotations

from pathlib import Path

from map_validator.individual_capture_index import list_individual_capture_files

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)


class ZoomEvidenceView(QGraphicsView):
    """Ctrl + mouse wheel zooms around the cursor; wheel and drag pan."""

    def __init__(self, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        scene = QGraphicsScene(self)
        scene.addPixmap(pixmap)
        self.setScene(scene)
        self._zoom = 1.0
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setToolTip("Ctrl + 마우스 휠: 확대/축소 · 휠/드래그: 이동")

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                target = max(0.2, min(8.0, self._zoom * (1.2 ** steps)))
                self.scale(target / self._zoom, target / self._zoom)
                self._zoom = target
            event.accept()
            return
        super().wheelEvent(event)


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
        self.details.setPlaceholderText("정지선 S/G, 중앙선 C, 흰색 실선 L과 점선 D 후보가 표시됩니다.")
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
                # Raw PNGs are authoritative: the manifest may have been
                # deleted or partially cleared by the inspector.
                try:
                    for revision in list_individual_capture_files(folder):
                        candidates.append((folder, revision))
                except OSError:
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
        hint = QLabel("Ctrl + 마우스 휠: 확대/축소  |  휠: 스크롤  |  드래그: 이동")
        dialog_layout.addWidget(hint)
        viewer = ZoomEvidenceView(pixmap, dialog)
        dialog_layout.addWidget(viewer, 1)
        close = QPushButton("닫기")
        close.clicked.connect(dialog.accept)
        dialog_layout.addWidget(close)
        dialog.exec()
