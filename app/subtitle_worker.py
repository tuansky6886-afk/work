"""QThread workers for transcription and subtitle burning — same
never-block-the-GUI-thread / never-let-an-exception-escape-the-thread
rules as join_worker.py.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.ffmpeg_utils import FfmpegError, burn_subtitles
from app.subtitle_utils import transcribe_to_srt


class TranscribeWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)  # SRT text
    failed = pyqtSignal(str)

    def __init__(self, video_path: Path, model_size: str, translate_to_english: bool) -> None:
        super().__init__()
        self.video_path = video_path
        self.model_size = model_size
        self.translate_to_english = translate_to_english

    def run(self) -> None:
        try:
            srt_text = transcribe_to_srt(
                self.video_path,
                model_size=self.model_size,
                translate_to_english=self.translate_to_english,
                on_progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            if not srt_text.strip():
                self.failed.emit("No speech was detected in this video's audio.")
                return
            self.finished_ok.emit(srt_text)
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            self.failed.emit(traceback.format_exc())


class BurnSubtitleWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)  # output path
    failed = pyqtSignal(str)

    def __init__(self, subtitle_path: Path, video_path: Path, out_path: Path) -> None:
        super().__init__()
        self.subtitle_path = subtitle_path
        self.video_path = video_path
        self.out_path = out_path

    def run(self) -> None:
        try:
            self.progress.emit(10, "Burning subtitles onto video...")
            burn_subtitles(self.subtitle_path, self.video_path, self.out_path)
            self.progress.emit(100, "Done.")
            self.finished_ok.emit(str(self.out_path))
        except FfmpegError as exc:
            detail = f"{exc}\n\n{exc.stderr[-800:]}" if exc.stderr else str(exc)
            self.failed.emit(detail)
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            self.failed.emit(traceback.format_exc())
