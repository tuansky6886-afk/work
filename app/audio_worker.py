"""Background worker for attaching a music file to a video."""

from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.ffmpeg_utils import FfmpegError, attach_audio


class AttachAudioWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, video_path: Path, audio_path: Path, out_path: Path) -> None:
        super().__init__()
        self.video_path = video_path
        self.audio_path = audio_path
        self.out_path = out_path

    def run(self) -> None:
        try:
            attach_audio(
                self.video_path,
                self.audio_path,
                self.out_path,
                on_progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_ok.emit(str(self.out_path))
        except FfmpegError as exc:
            detail = f"{exc}\n\n{exc.stderr[-800:]}" if exc.stderr else str(exc)
            self.failed.emit(detail)
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            self.failed.emit(traceback.format_exc())
