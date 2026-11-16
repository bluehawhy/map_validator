"""Responsive read-only image preview for individual capture evidence."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy


class EvidencePreview(QLabel):
    """Scale evidence to available panel space without distorting proportions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._original: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(165)
        self.setMaximumHeight(320)
        self.setText("촬영 후 정지선 후보 S1, S2, ... 표시 이미지가 여기에 나타납니다.")
        self.setWordWrap(True)
        self.setObjectName("evidencePreview")

    def clear_evidence(self) -> None:
        self._original = None
        self.clear()
        self.setText("개별 촬영 후 후보 위치를 표시합니다.")

    def set_evidence(self, path: Path) -> bool:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.clear_evidence()
            self.setText("근거 이미지를 불러올 수 없습니다. 근거 이미지 보기로 확인하세요.")
            return False
        self._original = pixmap
        self._rescale()
        return True

    def _rescale(self) -> None:
        if self._original is None or self._original.isNull():
            return
        size = self.contentsRect().size()
        if size.width() < 10 or size.height() < 10:
            return
        self.setPixmap(self._original.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()
