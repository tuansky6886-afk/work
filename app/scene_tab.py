"""Scene Prompts tab: a YouTube link becomes one 15-second-scene reconstruction prompt.

A video longer than 20 scenes keeps only the first 20.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings
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

from app.scene_scan import DEFAULT_MODEL, MODEL_CHOICES
from app.scene_utils import ScanOutput
from app.scene_worker import ScanScenesWorker
from app.style import icon

_MODELS = MODEL_CHOICES
_ASPECTS = ("Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3")


class SceneTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("VideoJoiner", "VideoJoiner")
        self._worker: ScanScenesWorker | None = None
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("Scene Prompts")
        title.setObjectName("title")
        header.addWidget(title)
        subtitle = QLabel(
            "Paste a public YouTube link. The app watches the video in 15-second scenes and writes "
            "one prompt you can use to rebuild it. A longer video keeps only the first 20 scenes "
            "(5 minutes, about 21 Gemini calls). Private videos cannot be scanned."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(8)

        link_label = QLabel("YouTube link")
        link_label.setObjectName("sectionLabel")
        card_layout.addWidget(link_label)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.returnPressed.connect(self._on_scan_clicked)
        card_layout.addWidget(self.url_edit)

        key_label = QLabel("Gemini API key")
        key_label.setObjectName("sectionLabel")
        card_layout.addWidget(key_label)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Stored on this PC when you scan")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self.key_edit, stretch=1)
        self.show_key = QCheckBox("Show")
        self.show_key.toggled.connect(self._on_show_key_toggled)
        key_row.addWidget(self.show_key)
        card_layout.addLayout(key_row)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(_MODELS)
        self.model_combo.setMinimumWidth(180)
        options.addWidget(self.model_combo)
        options.addWidget(QLabel("Aspect:"))
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems(_ASPECTS)
        self.aspect_combo.setMinimumWidth(90)
        options.addWidget(self.aspect_combo)
        self.fast_cuts = QCheckBox("Fast cuts (5 fps)")
        options.addWidget(self.fast_cuts)
        options.addStretch(1)
        card_layout.addLayout(options)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.scan_button = QPushButton(" Scan Scenes")
        self.scan_button.setObjectName("primary")
        self.scan_button.setIcon(icon(self, QStyle.StandardPixmap.SP_ArrowRight))
        self.scan_button.setMinimumHeight(38)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        buttons.addWidget(self.scan_button, stretch=1)
        self.cancel_button = QPushButton(" Cancel")
        self.cancel_button.setIcon(icon(self, QStyle.StandardPixmap.SP_DialogCancelButton))
        self.cancel_button.setMinimumHeight(38)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        buttons.addWidget(self.cancel_button)
        card_layout.addLayout(buttons)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("subtitle")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)
        layout.addWidget(card)

        preview_row = QHBoxLayout()
        preview_label = QLabel("Prompt")
        preview_label.setObjectName("sectionLabel")
        preview_row.addWidget(preview_label)
        preview_row.addStretch(1)
        self.copy_button = QPushButton(" Copy")
        self.copy_button.setIcon(icon(self, QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.copy_button.clicked.connect(self._on_copy_clicked)
        preview_row.addWidget(self.copy_button)
        layout.addLayout(preview_row)

        self.prompt_text = QTextEdit()
        self.prompt_text.setPlaceholderText(
            "The full prompt appears here: one locked look, then a block for every 15-second scene. "
            "Edit it if you want, then copy."
        )
        layout.addWidget(self.prompt_text, stretch=1)

    def _load_settings(self) -> None:
        key = self._settings.value("gemini_api_key", "")
        model = self._settings.value("gemini_model", DEFAULT_MODEL)
        if isinstance(key, str) and key:
            self.key_edit.setText(key)
        if isinstance(model, str) and model.strip():
            self.model_combo.setCurrentText(model.strip())

    def _save_settings(self) -> None:
        self._settings.setValue("gemini_api_key", self.key_edit.text().strip())
        self._settings.setValue("gemini_model", self.model_combo.currentText().strip() or DEFAULT_MODEL)

    def _on_show_key_toggled(self, checked: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)

    def _on_scan_clicked(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "No link", "Paste a YouTube link first.")
            return
        if not self.key_edit.text().strip():
            QMessageBox.warning(self, "No API key", "Enter a Gemini API key first.")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._save_settings()
        aspect = self.aspect_combo.currentText()
        self._set_running(True)
        self.status_label.setText("Starting the scan...")
        self.progress_bar.setRange(0, 0)
        self._worker = ScanScenesWorker(
            url,
            self.key_edit.text().strip(),
            self.model_combo.currentText().strip(),
            None if aspect == "Auto" else aspect,
            self.fast_cuts.isChecked(),
        )
        queued = Qt.ConnectionType.QueuedConnection
        self._worker.progress.connect(self._on_progress, queued)
        self._worker.confirm_count.connect(self._on_confirm_count, queued)
        self._worker.finished_ok.connect(self._on_scan_finished, queued)
        self._worker.failed.connect(self._on_scan_failed, queued)
        self._worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.status_label.setText("Stopping after the current scene...")
            self.cancel_button.setEnabled(False)

    def _on_confirm_count(self, scene_count: int, duration_seconds: int, remainder: int, capped: bool) -> None:
        minutes, seconds = divmod(duration_seconds, 60)
        length = f"{minutes} min {seconds} sec" if minutes else f"{seconds} sec"
        calls = scene_count + 1
        if capped:
            covered_minutes, covered_seconds = divmod(scene_count * 15, 60)
            covered = f"{covered_minutes} min {covered_seconds} sec" if covered_seconds else f"{covered_minutes} min"
            detail = (
                f"This video is {length}. Only the first {scene_count} scenes ({covered}) are scanned. "
                f"The rest is left out."
            )
        else:
            detail = f"This video is {length}. It will be split into {scene_count} scenes of 15 seconds."
            if remainder:
                detail += f"\n\nThe last {remainder} seconds are shorter than one scene, so they are left out."
        accepted = False
        try:
            answer = QMessageBox.question(
                self,
                "Scan this video?",
                f"{detail}\n\nThat is {calls} Gemini calls: one to lock the look, then one per scene.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            accepted = answer == QMessageBox.StandardButton.Yes
        finally:
            if self._worker is not None:
                self._worker.answer_confirm(accepted)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(done, total))
        self.status_label.setText(message)

    def _on_scan_finished(self, result: object) -> None:
        self._finish_worker()
        if not isinstance(result, ScanOutput):
            self.status_label.setText("Scan failed.")
            QMessageBox.critical(self, "Scan failed", "The scan returned an unexpected result.")
            return
        self.prompt_text.setPlainText(result.text)
        if result.stopped:
            if result.finished_scenes:
                self.status_label.setText(
                    f"Stopped early — {result.finished_scenes} of {result.planned_scenes} scenes are in the box."
                )
            else:
                self.status_label.setText("Stopped early — only the look notes were written.")
            return
        self.status_label.setText(f"Wrote {result.planned_scenes} scenes for “{result.title}”.")

    def _on_scan_failed(self, error_text: str) -> None:
        self._finish_worker()
        if not error_text:
            self.status_label.setText("Scan cancelled.")
            return
        self.status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Couldn't scan the video", error_text[:2000])

    def _finish_worker(self) -> None:
        self._set_running(False)
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_copy_clicked(self) -> None:
        text = self.prompt_text.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Nothing to copy", "Scan a video first.")
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            QMessageBox.critical(self, "Copy failed", "The clipboard is not available.")
            return
        clipboard.setText(text)
        self.status_label.setText("Copied the prompt to the clipboard.")

    def _set_running(self, running: bool) -> None:
        self.scan_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.url_edit.setEnabled(not running)
        self.key_edit.setEnabled(not running)
        self.show_key.setEnabled(not running)
        self.model_combo.setEnabled(not running)
        self.aspect_combo.setEnabled(not running)
        self.fast_cuts.setEnabled(not running)
        if not running:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
