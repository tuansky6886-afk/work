"""QListWidget that accepts video files dropped from Explorer, supports
manual reordering by dragging, and defaults new additions to chronological
(file creation time) order."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".flv", ".wmv"}


def _creation_time(path: Path) -> float:
    try:
        # os.path.getctime is the actual file-creation timestamp on
        # Windows (unlike Linux/macOS, where it's metadata-change time) —
        # this app targets Windows, so that's exactly "when was this clip
        # recorded/produced" for files fresh off a camera or export.
        return os.path.getctime(path)
    except OSError:
        return 0.0


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _item_text(path: Path) -> str:
    try:
        stat = path.stat()
        created = datetime.fromtimestamp(_creation_time(path)).strftime("%Y-%m-%d %H:%M")
        size = _format_size(stat.st_size)
        return f"{path.name}\n{created}  ·  {size}"
    except OSError:
        return path.name


class VideoListWidget(QListWidget):
    files_added = pyqtSignal(list)  # list[Path]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def add_paths(self, paths: list[Path]) -> None:
        added: list[Path] = []
        for path in paths:
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            self._add_item(path)
            added.append(path)
        if added:
            self.sort_by_created_time()
            self.files_added.emit(added)

    def _add_item(self, path: Path) -> None:
        item = QListWidgetItem(_item_text(path))
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(str(path))
        self.addItem(item)

    def paths(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.count())]

    def sort_by_created_time(self) -> None:
        """Default ordering for newly-added clips: oldest-recorded first,
        which is the natural join order for footage shot over time. Kept
        as an explicit, re-runnable action (not just an on-add side
        effect) so the user can snap back to it after manual reordering."""
        current_paths = self.paths()
        if len(current_paths) < 2:
            return
        ordered = sorted(current_paths, key=_creation_time)
        if ordered == current_paths:
            return
        selected_paths = {self.item(i).data(Qt.ItemDataRole.UserRole) for i in self._selected_rows()}
        self.clear()
        for path in ordered:
            self._add_item(path)
        for i in range(self.count()):
            if self.item(i).data(Qt.ItemDataRole.UserRole) in selected_paths:
                self.item(i).setSelected(True)

    def _selected_rows(self) -> list[int]:
        return [self.row(item) for item in self.selectedItems()]

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))

    def move_selected(self, direction: int) -> None:
        row = self.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.count():
            return
        item = self.takeItem(row)
        self.insertItem(target, item)
        self.setCurrentRow(target)

    # -- drag-drop from Explorer --------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            self.add_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
