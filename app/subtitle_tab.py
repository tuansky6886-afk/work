"""Subtitles tab: either auto-transcribe a video's speech (faster-whisper)
or load an existing subtitle file (.srt/.ass), preview/edit it, then burn
it onto the video's picture."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ffmpeg_utils import resolve_ffmpeg
from app.style import icon
from app.subtitle_utils import WHISPER_MODEL_SIZES
from app.subtitle_worker import BurnSubtitleWorker, TranscribeWorker

_VIDEO_FILTER = "Video files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.ts *.flv *.wmv)"
_SUBTITLE_FILTER = "Subtitle files (*.srt *.ass)"


class SubtitleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._transcribe_worker: TranscribeWorker | None = None
        self._burn_worker: BurnSubtitleWorker | None = None
        self._loaded_path: Path | None = None
        self._loaded_text: str = ""
        self._loaded_ext: str = ".srt"
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("Subtitles")
        title.setObjectName("title")
        header.addWidget(title)
        subtitle = QLabel(
            "Auto-transcribe speech into English captions, or load a subtitle file you already "
            "have, then burn it onto the video."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        # -- video picker -----------------------------------------------
        video_card = QFrame()
        video_card.setObjectName("card")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(14, 12, 14, 14)
        video_layout.setSpacing(8)
        video_label = QLabel("Video")
        video_label.setObjectName("sectionLabel")
        video_layout.addWidget(video_label)

        video_row = QHBoxLayout()
        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("Choose the video to caption...")
        self.video_edit.textChanged.connect(self._update_button_states)
        video_row.addWidget(self.video_edit, stretch=1)
        video_browse = QPushButton(" Browse...")
        video_browse.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogOpenButton))
        video_browse.clicked.connect(self._on_browse_video)
        video_row.addWidget(video_browse)
        video_layout.addLayout(video_row)
        layout.addWidget(video_card)

        # -- get subtitles ------------------------------------------------
        get_card = QFrame()
        get_card.setObjectName("card")
        get_layout = QVBoxLayout(get_card)
        get_layout.setContentsMargins(14, 12, 14, 14)
        get_layout.setSpacing(8)
        get_label = QLabel("Get Subtitles")
        get_label.setObjectName("sectionLabel")
        get_layout.addWidget(get_label)

        transcribe_row = QHBoxLayout()
        transcribe_row.setSpacing(8)
        transcribe_row.addWidget(QLabel("Whisper model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(WHISPER_MODEL_SIZES)
        self.model_combo.setCurrentText("small")
        transcribe_row.addWidget(self.model_combo)
        self.translate_checkbox = QCheckBox("Translate to English")
        self.translate_checkbox.setChecked(True)
        transcribe_row.addWidget(self.translate_checkbox)
        transcribe_row.addStretch(1)
        self.transcribe_button = QPushButton(" Transcribe from Audio")
        self.transcribe_button.setIcon(icon(self, QStyle.StandardPixmap.SP_MediaVolume))
        self.transcribe_button.clicked.connect(self._on_transcribe_clicked)
        transcribe_row.addWidget(self.transcribe_button)
        get_layout.addLayout(transcribe_row)

        load_row = QHBoxLayout()
        load_row.addWidget(QLabel("Already have a subtitle file (.srt / .ass)?"))
        load_row.addStretch(1)
        load_button = QPushButton(" Load Subtitle File...")
        load_button.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogOpenButton))
        load_button.clicked.connect(self._on_load_subtitle_file)
        load_row.addWidget(load_button)
        get_layout.addLayout(load_row)

        layout.addWidget(get_card)

        # -- preview / edit -------------------------------------------------
        preview_label = QLabel("Subtitle preview (editable before burning)")
        preview_label.setObjectName("sectionLabel")
        layout.addWidget(preview_label)

        self.subtitle_text = QTextEdit()
        self.subtitle_text.setPlaceholderText(
            "Transcribed or loaded subtitle text will appear here. You can edit it before burning."
        )
        layout.addWidget(self.subtitle_text, stretch=1)

        # -- output / burn ----------------------------------------------
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
        self.output_edit.setPlaceholderText("Choose where to save the captioned video...")
        output_row.addWidget(self.output_edit, stretch=1)
        output_browse = QPushButton(" Browse...")
        output_browse.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogSaveButton))
        output_browse.clicked.connect(self._on_browse_output)
        output_row.addWidget(output_browse)
        output_layout.addLayout(output_row)

        self.burn_button = QPushButton(" Burn Subtitles onto Video")
        self.burn_button.setObjectName("primary")
        self.burn_button.setIcon(icon(self, QStyle.StandardPixmap.SP_MediaPlay))
        self.burn_button.setMinimumHeight(38)
        self.burn_button.clicked.connect(self._on_burn_clicked)
        output_layout.addWidget(self.burn_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        output_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("subtitle")
        output_layout.addWidget(self.status_label)

        layout.addWidget(output_card)

        self._update_button_states()

    def _update_button_states(self) -> None:
        has_video = bool(self.video_edit.text().strip())
        self.transcribe_button.setEnabled(has_video)

    # -- video / output pickers ----------------------------------------------

    def _on_browse_video(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose a video", "", _VIDEO_FILTER)
        if file_path:
            self.video_edit.setText(file_path)

    def _on_browse_output(self) -> None:
        default_dir = os.path.dirname(self.output_edit.text()) or os.path.dirname(self.video_edit.text())
        default_dir = default_dir or str(Path.home() / "Videos")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save captioned video as", os.path.join(default_dir, "captioned.mp4"), "MP4 video (*.mp4)"
        )
        if file_path:
            if not file_path.lower().endswith(".mp4"):
                file_path += ".mp4"
            self.output_edit.setText(file_path)

    # -- get subtitles ---------------------------------------------------

    def _on_load_subtitle_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Load subtitle file", "", _SUBTITLE_FILTER)
        if not file_path:
            return
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.critical(self, "Failed to read file", str(exc))
            return
        self._loaded_path = path
        self._loaded_text = text
        self._loaded_ext = path.suffix.lower() if path.suffix.lower() in (".srt", ".ass") else ".srt"
        self.subtitle_text.setPlainText(text)
        self.status_label.setText(f"Loaded: {path.name}")

    def _on_transcribe_clicked(self) -> None:
        video_path = self.video_edit.text().strip()
        if not video_path:
            QMessageBox.warning(self, "No video", "Choose a video first.")
            return
        if not resolve_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.",
            )
            return

        self._set_running(True)
        self.status_label.setText("Loading model...")
        self._transcribe_worker = TranscribeWorker(
            Path(video_path), self.model_combo.currentText(), self.translate_checkbox.isChecked()
        )
        self._transcribe_worker.progress.connect(self._on_progress)
        self._transcribe_worker.finished_ok.connect(self._on_transcribe_finished)
        self._transcribe_worker.failed.connect(self._on_transcribe_failed)
        self._transcribe_worker.start()

    def _on_transcribe_finished(self, srt_text: str) -> None:
        self._set_running(False)
        self._loaded_path = None
        self._loaded_text = srt_text
        self._loaded_ext = ".srt"
        self.subtitle_text.setPlainText(srt_text)
        self.status_label.setText("Transcription complete — review the text below, then burn it in.")

    def _on_transcribe_failed(self, error_text: str) -> None:
        self._set_running(False)
        self.status_label.setText("Transcription failed.")
        QMessageBox.critical(self, "Transcription failed", error_text[:2000])

    # -- burn --------------------------------------------------------------

    def _on_burn_clicked(self) -> None:
        video_path = self.video_edit.text().strip()
        if not video_path:
            QMessageBox.warning(self, "No video", "Choose a video first.")
            return
        text = self.subtitle_text.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "No subtitles", "Transcribe or load a subtitle file first.")
            return
        if not resolve_ffmpeg():
            QMessageBox.critical(
                self,
                "FFmpeg not found",
                "FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.",
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

        # Burn the ORIGINAL file untouched when it's still exactly what was
        # loaded — re-saving a styled .ass file through a plain QTextEdit
        # round-trip risks corrupting encoding/line-endings even if the
        # visible text is unchanged. Only fall back to writing a fresh file
        # when the user actually edited the text (or it came from
        # transcription, which never had a source file to begin with).
        if self._loaded_path is not None and text == self._loaded_text:
            subtitle_source = self._loaded_path
        else:
            tmp_path = Path(tempfile.gettempdir()) / f"videojoiner_subtitle{self._loaded_ext}"
            tmp_path.write_text(text, encoding="utf-8")
            subtitle_source = tmp_path

        self._set_running(True)
        self._burn_worker = BurnSubtitleWorker(subtitle_source, Path(video_path), out)
        self._burn_worker.progress.connect(self._on_progress)
        self._burn_worker.finished_ok.connect(self._on_burn_finished)
        self._burn_worker.failed.connect(self._on_burn_failed)
        self._burn_worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_burn_finished(self, output_path: str) -> None:
        self._set_running(False)
        self.status_label.setText(f"Done: {output_path}")
        QMessageBox.information(self, "Burn complete", f"Saved to:\n{output_path}")

    def _on_burn_failed(self, error_text: str) -> None:
        self._set_running(False)
        self.status_label.setText("Failed.")
        QMessageBox.critical(self, "Burn failed", error_text[:2000])

    def _set_running(self, running: bool) -> None:
        self.transcribe_button.setEnabled(not running and bool(self.video_edit.text().strip()))
        self.burn_button.setEnabled(not running)
        self.video_edit.setEnabled(not running)
        self.subtitle_text.setEnabled(not running)
