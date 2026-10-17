from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.ffmpeg_utils import resolve_ffmpeg
from app.join_worker import JoinWorker
from app.style import icon
from app.video_list_widget import VIDEO_EXTENSIONS, VideoListWidget

_VIDEO_FILTER = "Video files (" + " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS)) + ")"


class JoinTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self._worker: JoinWorker | None = None
        self._build_ui()
        self._check_ffmpeg()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("Video Joiner")
        title.setObjectName("title")
        header.addWidget(title)
        subtitle = QLabel("Drag video files in, arrange the order, and join them into one file.")
        subtitle.setObjectName("subtitle")
        header.addWidget(subtitle)
        layout.addLayout(header)

        list_label = QLabel("Clips (drag to reorder)")
        list_label.setObjectName("sectionLabel")
        layout.addWidget(list_label)

        self.list_widget = VideoListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSpacing(2)
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.list_widget.model().rowsInserted.connect(lambda *_: self._update_button_states())
        self.list_widget.model().rowsRemoved.connect(lambda *_: self._update_button_states())
        layout.addWidget(self.list_widget, stretch=1)

        list_buttons = QHBoxLayout()
        list_buttons.setSpacing(8)
        self.add_button = QPushButton(" Add Files...")
        self.add_button.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogOpenButton))
        self.add_button.clicked.connect(self._on_add_files)
        self.remove_button = QPushButton(" Remove Selected")
        self.remove_button.setIcon(icon(self, QStyle.StandardPixmap.SP_TrashIcon))
        self.remove_button.clicked.connect(self.list_widget.remove_selected)
        self.up_button = QPushButton()
        self.up_button.setIcon(icon(self, QStyle.StandardPixmap.SP_ArrowUp))
        self.up_button.setToolTip("Move up")
        self.up_button.clicked.connect(lambda: self.list_widget.move_selected(-1))
        self.down_button = QPushButton()
        self.down_button.setIcon(icon(self, QStyle.StandardPixmap.SP_ArrowDown))
        self.down_button.setToolTip("Move down")
        self.down_button.clicked.connect(lambda: self.list_widget.move_selected(1))
        self.sort_button = QPushButton(" Sort by Date")
        self.sort_button.setIcon(icon(self, QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.sort_button.setToolTip("Reorder clips by their creation time (oldest first)")
        self.sort_button.clicked.connect(self.list_widget.sort_by_created_time)
        self.clear_button = QPushButton(" Clear All")
        self.clear_button.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogResetButton))
        self.clear_button.clicked.connect(self.list_widget.clear)
        for btn in (
            self.add_button,
            self.remove_button,
            self.up_button,
            self.down_button,
            self.sort_button,
            self.clear_button,
        ):
            list_buttons.addWidget(btn)
        list_buttons.addStretch(1)
        layout.addLayout(list_buttons)

        output_card = QFrame()
        output_card.setObjectName("card")
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(14, 12, 14, 14)
        output_layout.setSpacing(8)

        output_label = QLabel("Output")
        output_label.setObjectName("sectionLabel")
        output_layout.addWidget(output_label)

        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose where to save the joined video...")
        output_row.addWidget(self.output_edit, stretch=1)
        browse_button = QPushButton(" Browse...")
        browse_button.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogSaveButton))
        browse_button.clicked.connect(self._on_browse_output)
        output_row.addWidget(browse_button)
        output_layout.addLayout(output_row)

        self.join_button = QPushButton(" Join Videos")
        self.join_button.setObjectName("primary")
        self.join_button.setIcon(icon(self, QStyle.StandardPixmap.SP_MediaPlay))
        self.join_button.setMinimumHeight(38)
        self.join_button.clicked.connect(self._on_join_clicked)
        output_layout.addWidget(self.join_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        output_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("subtitle")
        output_layout.addWidget(self.status_label)

        layout.addWidget(output_card)

        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setObjectName("subtitle")
        layout.addWidget(self.ffmpeg_label)

        self._update_button_states()

    def _check_ffmpeg(self) -> None:
        ffmpeg_path = resolve_ffmpeg()
        if ffmpeg_path:
            self.ffmpeg_label.setText(f"FFmpeg: {ffmpeg_path}")
        else:
            self.ffmpeg_label.setText("FFmpeg: NOT FOUND — install FFmpeg or `pip install imageio-ffmpeg`.")
            self.ffmpeg_label.setStyleSheet("color: #c0392b; font-weight: 600;")

    def _update_button_states(self) -> None:
        has_selection = bool(self.list_widget.selectedItems())
        has_items = self.list_widget.count() > 0
        self.remove_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection)
        self.down_button.setEnabled(has_selection)
        self.sort_button.setEnabled(self.list_widget.count() > 1)
        self.clear_button.setEnabled(has_items)
        self.join_button.setEnabled(has_items and self.list_widget.count() >= 2)

    # -- slots ---------------------------------------------------------------

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add video files", "", _VIDEO_FILTER)
        if files:
            self.list_widget.add_paths([Path(f) for f in files])

    def _on_browse_output(self) -> None:
        default_dir = os.path.dirname(self.output_edit.text()) or str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save joined video as", os.path.join(default_dir, "joined.mp4"), "MP4 video (*.mp4)"
        )
        if file_path:
            if not file_path.lower().endswith(".mp4"):
                file_path += ".mp4"
            self.output_edit.setText(file_path)

    def _on_join_clicked(self) -> None:
        if self.list_widget.count() < 2:
            QMessageBox.warning(self, "Not enough videos", "Add at least 2 videos to join.")
            return
        if not resolve_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.\n\n"
                "Install FFmpeg, or run: pip install imageio-ffmpeg",
            )
            return

        output_path = self.output_edit.text().strip()
        if not output_path:
            self._on_browse_output()
            output_path = self.output_edit.text().strip()
            if not output_path:
                return

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        self._set_running(True)
        self._worker = JoinWorker(self.list_widget.paths(), out)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_join_finished)
        self._worker.failed.connect(self._on_join_failed)
        self._worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_join_finished(self, output_path: str) -> None:
        self._set_running(False)
        self.status_label.setText(f"Done: {output_path}")
        QMessageBox.information(self, "Join complete", f"Saved to:\n{output_path}")

    def _on_join_failed(self, error_text: str) -> None:
        self._set_running(False)
        self.status_label.setText("Failed.")
        QMessageBox.critical(self, "Join failed", error_text[:2000])

    def _set_running(self, running: bool) -> None:
        self.join_button.setEnabled(not running and self.list_widget.count() >= 2)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running and bool(self.list_widget.selectedItems()))
        self.sort_button.setEnabled(not running and self.list_widget.count() > 1)
        self.clear_button.setEnabled(not running and self.list_widget.count() > 0)
        self.list_widget.setEnabled(not running)
        if not running:
            self._update_button_states()

    # -- accept drops on the whole tab, forward to the list ------------------

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            self.list_widget.add_paths(paths)
            event.acceptProposedAction()
