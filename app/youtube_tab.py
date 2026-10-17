"""YouTube Lyrics tab: paste a link, pull the full caption transcript, copy it."""

from __future__ import annotations

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from app.style import icon
from app.youtube_utils import TranscriptResult, format_transcript
from app.youtube_worker import FetchTranscriptWorker


class YouTubeTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: FetchTranscriptWorker | None = None
        self._result: TranscriptResult | None = None
        self._filling_languages = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("YouTube Lyrics")
        title.setObjectName("title")
        header.addWidget(title)
        subtitle = QLabel(
            "Paste a YouTube link. The app reads the video's caption track — the full lyrics "
            "when the upload has them — so you can copy the text."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        link_card = QFrame()
        link_card.setObjectName("card")
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(14, 12, 14, 14)
        link_layout.setSpacing(8)
        link_label = QLabel("YouTube link")
        link_label.setObjectName("sectionLabel")
        link_layout.addWidget(link_label)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.returnPressed.connect(self._on_fetch_clicked)
        link_layout.addWidget(self.url_edit)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(220)
        self._set_language_placeholder()
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        options.addWidget(self.language_combo)
        self.timestamps_checkbox = QCheckBox("Include timestamps")
        self.timestamps_checkbox.toggled.connect(self._on_timestamps_toggled)
        options.addWidget(self.timestamps_checkbox)
        options.addStretch(1)
        link_layout.addLayout(options)

        self.fetch_button = QPushButton(" Get Transcript")
        self.fetch_button.setObjectName("primary")
        self.fetch_button.setIcon(icon(self, QStyle.StandardPixmap.SP_ArrowDown))
        self.fetch_button.setMinimumHeight(38)
        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        link_layout.addWidget(self.fetch_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        link_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("subtitle")
        self.status_label.setWordWrap(True)
        link_layout.addWidget(self.status_label)
        layout.addWidget(link_card)

        preview_row = QHBoxLayout()
        preview_label = QLabel("Transcript")
        preview_label.setObjectName("sectionLabel")
        preview_row.addWidget(preview_label)
        preview_row.addStretch(1)
        self.copy_button = QPushButton(" Copy")
        self.copy_button.setIcon(icon(self, QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.copy_button.clicked.connect(self._on_copy_clicked)
        preview_row.addWidget(self.copy_button)
        layout.addLayout(preview_row)

        self.transcript_text = QTextEdit()
        self.transcript_text.setPlaceholderText("The full transcript will appear here. Edit it if you want, then copy.")
        layout.addWidget(self.transcript_text, stretch=1)

    def _set_language_placeholder(self) -> None:
        self._filling_languages = True
        self.language_combo.clear()
        self.language_combo.addItem("Auto (original captions)", None)
        self.language_combo.setEnabled(False)
        self._filling_languages = False

    def _on_fetch_clicked(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "No link", "Paste a YouTube link first.")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        language_code = None
        generated = None
        selected = self.language_combo.currentData()
        if isinstance(selected, tuple):
            language_code, generated = selected

        self._set_running(True)
        self.status_label.setText("Fetching captions...")
        self._worker = FetchTranscriptWorker(url, language_code, generated)
        self._worker.finished_ok.connect(self._on_fetch_finished)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_fetch_finished(self, result: object) -> None:
        self._set_running(False)
        if not isinstance(result, TranscriptResult):
            self.status_label.setText("Fetch failed.")
            QMessageBox.critical(self, "Fetch failed", "The caption request returned an unexpected result.")
            return

        self._result = result
        self._fill_languages(result)
        self.transcript_text.setPlainText(
            format_transcript(result.snippets, self.timestamps_checkbox.isChecked())
        )
        title = result.title or result.video_id
        self.status_label.setText(f"Loaded “{title}” — {result.track.label}.")

    def _on_fetch_failed(self, error_text: str) -> None:
        self._set_running(False)
        if self._result is not None:
            self._fill_languages(self._result)
        self.status_label.setText("Fetch failed.")
        QMessageBox.critical(self, "Couldn't get the transcript", error_text[:2000])

    def _fill_languages(self, result: TranscriptResult) -> None:
        self._filling_languages = True
        self.language_combo.clear()
        selected_index = 0
        for index, track in enumerate(result.tracks):
            self.language_combo.addItem(track.label, (track.language_code, track.is_generated))
            if track.language_code == result.track.language_code and track.is_generated == result.track.is_generated:
                selected_index = index
        self.language_combo.setCurrentIndex(selected_index)
        self.language_combo.setEnabled(True)
        self._filling_languages = False

    def _on_language_changed(self, _index: int) -> None:
        if self._filling_languages or self._result is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        selected = self.language_combo.currentData()
        if not isinstance(selected, tuple):
            return
        language_code, generated = selected
        if language_code == self._result.track.language_code and generated == self._result.track.is_generated:
            return
        self._on_fetch_clicked()

    def _on_timestamps_toggled(self, checked: bool) -> None:
        if self._result is None:
            return
        self.transcript_text.setPlainText(format_transcript(self._result.snippets, checked))

    def _on_copy_clicked(self) -> None:
        text = self.transcript_text.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Nothing to copy", "Fetch a transcript first.")
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            QMessageBox.critical(self, "Copy failed", "The clipboard is not available.")
            return
        clipboard.setText(text)
        self.status_label.setText("Copied the full transcript to the clipboard.")

    def _set_running(self, running: bool) -> None:
        self.fetch_button.setEnabled(not running)
        self.url_edit.setEnabled(not running)
        self.language_combo.setEnabled(not running and self._result is not None)
        self.copy_button.setEnabled(not running)
        self.timestamps_checkbox.setEnabled(not running)
        if running:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
