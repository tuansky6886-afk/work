"""Background fetch for the YouTube Lyrics tab.

The network call must not run on the Qt GUI thread, and an exception must
not escape the thread (PyQt aborts the process when that happens).
"""

from __future__ import annotations

import logging
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from app.youtube_utils import TranscriptError, fetch_youtube_transcript


class FetchTranscriptWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, url: str, language_code: str | None, generated: bool | None) -> None:
        super().__init__()
        self.url = url
        self.language_code = language_code
        self.generated = generated

    def run(self) -> None:
        try:
            result = fetch_youtube_transcript(self.url, self.language_code, self.generated)
            self.finished_ok.emit(result)
        except TranscriptError as exc:
            self.failed.emit(str(exc))
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            logging.exception("YouTube transcript fetch failed")
            self.failed.emit(traceback.format_exc())
