"""Add Music tab: lay a music file over a video, looping it to the video's length."""

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

from app.audio_worker import AttachAudioWorker
from app.ffmpeg_utils import resolve_ffmpeg
from app.style import icon

_VIDEO_FILTER = "Video files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.ts *.flv *.wmv)"
_AUDIO_FILTER = "Audio files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma)"


class AudioTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: AttachAudioWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("Add Music")
        title.setObjectName("title")
        header.addWidget(title)
        subtitle = QLabel(
            "Pick a video and a music file. If the music is shorter than the video, "
            "it is repeated back-to-back until it matches the video. The video's own "
            "sound is replaced."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        layout.addWidget(self._path_card(
            "Video",
            "Choose the video...",
            "_video_edit",
            self._on_browse_video,
            QStyle.StandardPixmap.SP_DialogOpenButton,
        ))
        layout.addWidget(self._path_card(
            "Music",
            "Choose the music file...",
            "_audio_edit",
            self._on_browse_audio,
            QStyle.StandardPixmap.SP_MediaVolume,
        ))

        output_card = QFrame()
        output_card.setObjectName("card")
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(14, 12, 14, 14)
        output_layout.setSpacing(8)
        output_label = QLabel("Output")
        output_label.setObjectName("sectionLabel")
        output_layout.addWidget(output_label)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose where to save the video with music...")
        output_row.addWidget(self.output_edit, stretch=1)
        output_browse = QPushButton(" Browse...")
        output_browse.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogSaveButton))
        output_browse.clicked.connect(self._on_browse_output)
        output_row.addWidget(output_browse)
        output_layout.addLayout(output_row)

        self.attach_button = QPushButton(" Add Music")
        self.attach_button.setObjectName("primary")
        self.attach_button.setIcon(icon(self, QStyle.StandardPixmap.SP_MediaPlay))
        self.attach_button.setMinimumHeight(38)
        self.attach_button.clicked.connect(self._on_attach_clicked)
        output_layout.addWidget(self.attach_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        output_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("subtitle")
        self.status_label.setWordWrap(True)
        output_layout.addWidget(self.status_label)
        layout.addWidget(output_card)
        layout.addStretch(1)

        self._update_button_states()

    def _path_card(self, title: str, placeholder: str, attr: str, on_browse, pixmap: QStyle.StandardPixmap) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionLabel")
        card_layout.addWidget(label)

        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._update_button_states)
        setattr(self, attr, edit)
        row.addWidget(edit, stretch=1)
        browse = QPushButton(" Browse...")
        browse.setIcon(icon(self, pixmap))
        browse.clicked.connect(on_browse)
        row.addWidget(browse)
        card_layout.addLayout(row)
        return card

    def _update_button_states(self) -> None:
        running = self._worker is not None and self._worker.isRunning()
        self.attach_button.setEnabled(
            not running and bool(self._video_edit.text().strip()) and bool(self._audio_edit.text().strip())
        )

    def _on_browse_video(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose a video", "", _VIDEO_FILTER)
        if not file_path:
            return
        self._video_edit.setText(file_path)
        if not self.output_edit.text().strip():
            source = Path(file_path)
            self.output_edit.setText(str(source.with_name(f"{source.stem}_music.mp4")))

    def _on_browse_audio(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose a music file", "", _AUDIO_FILTER)
        if file_path:
            self._audio_edit.setText(file_path)

    def _on_browse_output(self) -> None:
        default_dir = os.path.dirname(self.output_edit.text()) or os.path.dirname(self._video_edit.text())
        default_dir = default_dir or str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save video with music as", os.path.join(default_dir, "with_music.mp4"), "MP4 video (*.mp4)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".mp4"):
            file_path += ".mp4"
        self.output_edit.setText(file_path)

    def _on_attach_clicked(self) -> None:
        video_path = self._video_edit.text().strip()
        audio_path = self._audio_edit.text().strip()
        if not video_path or not audio_path:
            QMessageBox.warning(self, "Missing files", "Choose both a video and a music file.")
            return
        if not resolve_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.",
            )
            return
        if self._worker is not None and self._worker.isRunning():
            return

        output_path = self.output_edit.text().strip()
        if not output_path:
            self._on_browse_output()
            output_path = self.output_edit.text().strip()
            if not output_path:
                return
        out = Path(output_path)
        if out.resolve() == Path(video_path).resolve():
            QMessageBox.warning(
                self,
                "Output overlaps the video",
                "Choose an output file that is different from the source video.",
            )
            return
        out.parent.mkdir(parents=True, exist_ok=True)

        self._set_running(True)
        self.status_label.setText("Attaching music...")
        self._worker = AttachAudioWorker(Path(video_path), Path(audio_path), out)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_finished(self, output_path: str) -> None:
        self._set_running(False)
        self.status_label.setText(f"Done: {output_path}")
        QMessageBox.information(self, "Music added", f"Saved to:\n{output_path}")

    def _on_failed(self, error_text: str) -> None:
        self._set_running(False)
        self.status_label.setText("Failed.")
        QMessageBox.critical(self, "Couldn't add the music", error_text[:2000])

    def _set_running(self, running: bool) -> None:
        self._video_edit.setEnabled(not running)
        self._audio_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.attach_button.setEnabled(
            not running and bool(self._video_edit.text().strip()) and bool(self._audio_edit.text().strip())
        )
        if not running:
            self.progress_bar.setValue(0)
