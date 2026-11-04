"""On-demand diagnostics for open Windows windows and nested UIA controls.

This dialog is read-only: it never activates windows or writes to config.yaml.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


def _window_class(handle: int) -> str:
    """Read a native Windows class name without activating the target window."""
    buffer = ctypes.create_unicode_buffer(256)
    get_class_name = ctypes.windll.user32.GetClassNameW
    get_class_name.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    get_class_name.restype = ctypes.c_int
    return buffer.value if get_class_name(handle, buffer, len(buffer)) else "-"


def _uia_property(control, property_name: str) -> str:
    try:
        value = getattr(control.element_info, property_name, None)
        return str(value).strip() if value is not None else ""
    except Exception:
        return ""


class WindowInfoDialog(QDialog):
    """Show a snapshot of titled windows, with opt-in inspection of one UIA tree."""

    MAX_CONTROLS = 300
    MAX_DEPTH = 7

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("창 정보 보기")
        self.resize(800, 540)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        description = QLabel(
            "현재 열려 있는 창 제목을 표시합니다. '교차로 선형 검수'가 목록에 없다면 "
            "HD_3D Tool을 선택한 뒤 '선택 창 내부 보기'를 눌러 확인하세요."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("창 제목 검색 (예: HD_3D Tool)")
        self.search_input.textChanged.connect(self._filter_windows)
        filter_row.addWidget(self.search_input, 1)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self._refresh_windows)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["창 제목 / 내부 항목", "유형 / 클래스", "핸들"])
        self.tree.setColumnWidth(0, 405)
        self.tree.setColumnWidth(1, 210)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        inspect_btn = QPushButton("선택 창 내부 보기")
        inspect_btn.setToolTip("선택한 창의 하위 UI Automation 항목을 한 번만 조회합니다.")
        inspect_btn.clicked.connect(self._inspect_selected)
        buttons.addWidget(inspect_btn)
        copy_btn = QPushButton("목록 복사")
        copy_btn.clicked.connect(self._copy_list)
        buttons.addWidget(copy_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh_windows()

    def _refresh_windows(self) -> None:
        """List the same top-level windows that normal window matching can see."""
        import pygetwindow as gw

        self.tree.clear()
        handles: set[int] = set()
        try:
            windows = gw.getAllWindows()
            for window in windows:
                title = window.title.strip()
                handle = int(getattr(window, "_hWnd", 0) or 0)
                if not title or not handle or handle in handles:
                    continue
                handles.add(handle)
                item = QTreeWidgetItem(
                    [title, f"최상위 / {_window_class(handle)}", f"0x{handle:X}"]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, handle)
                self.tree.addTopLevelItem(item)
            self.status.setText(
                f"제목이 있는 창 {self.tree.topLevelItemCount()}개 · "
                "내부 항목은 선택 후 요청할 때만 조회합니다."
            )
            self._filter_windows()
        except Exception as exc:
            self.status.setText(f"창 목록 조회 실패: {exc}")

    def _filter_windows(self) -> None:
        keyword = self.search_input.text().strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setHidden(bool(keyword and keyword not in item.text(0).casefold()))

    def _inspect_selected(self) -> None:
        selected = self.tree.currentItem()
        if selected is None:
            self.status.setText("먼저 내부 정보를 확인할 창을 선택하세요.")
            return
        # Selecting a nested row should still inspect its owning top-level window.
        root = selected
        while root.parent() is not None:
            root = root.parent()
        handle = root.data(0, Qt.ItemDataRole.UserRole)
        if not handle:
            self.status.setText("선택한 창의 핸들을 확인할 수 없습니다.")
            return

        root.takeChildren()
        try:
            from pywinauto import Desktop

            wrapper = Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
            queue = [(wrapper, root, 0)]
            count = 0
            while queue and count < self.MAX_CONTROLS:
                current_control, parent_item, depth = queue.pop(0)
                if depth >= self.MAX_DEPTH:
                    continue
                try:
                    children = current_control.children()
                except Exception:
                    continue
                for child in children:
                    if count >= self.MAX_CONTROLS:
                        break
                    name = _uia_property(child, "name") or "(이름 없음)"
                    control_type = _uia_property(child, "control_type") or "Control"
                    class_name = _uia_property(child, "class_name")
                    native_handle = _uia_property(child, "handle")
                    handle_text = (
                        f"0x{int(native_handle):X}"
                        if native_handle.isdigit() and int(native_handle) > 0
                        else "-"
                    )
                    item = QTreeWidgetItem(
                        [name, f"{control_type} / {class_name or '-'}", handle_text]
                    )
                    parent_item.addChild(item)
                    queue.append((child, item, depth + 1))
                    count += 1
            self.tree.expandItem(root)
            self.status.setText(
                f"'{root.text(0)}' 내부 항목 {count}개 조회"
                + (f" (최대 {self.MAX_CONTROLS}개까지 표시)" if queue else "")
                + " · 조회한 내용은 설정 파일에 저장하지 않습니다."
            )
        except Exception as exc:
            root.addChild(QTreeWidgetItem([f"내부 항목 조회 실패: {exc}", "", ""]))
            self.tree.expandItem(root)
            self.status.setText(
                "이 프로그램은 내부 컨트롤 정보를 제공하지 않을 수 있습니다. "
                f"상세 오류: {exc}"
            )

    def _copy_list(self) -> None:
        lines: list[str] = []

        def append_item(item: QTreeWidgetItem, depth: int) -> None:
            lines.append(
                "  " * depth
                + " | ".join(item.text(column) for column in range(3))
            )
            for index in range(item.childCount()):
                append_item(item.child(index), depth + 1)

        for index in range(self.tree.topLevelItemCount()):
            append_item(self.tree.topLevelItem(index), 0)
        QApplication.clipboard().setText("\n".join(lines))
        self.status.setText(f"창 정보 {len(lines)}개 항목을 클립보드에 복사했습니다.")
