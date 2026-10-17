"""QThread worker for the join operation.

Never call ffmpeg_utils.join_videos directly from a Qt slot — subprocess
calls block for seconds to minutes, which would freeze the whole window.
Any exception here is caught and reported via `failed`, never left to
escape the thread (an uncaught exception in a Qt slot/thread can abort the
whole process with no Python traceback shown to the user).
"""

from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.ffmpeg_utils import FfmpegError, join_videos


class JoinWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[Path], out_path: Path) -> None:
        super().__init__()
        self.paths = paths
        self.out_path = out_path

    def run(self) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="videojoiner_") as tmp:
                join_videos(
                    self.paths,
                    self.out_path,
                    Path(tmp),
                    on_progress=lambda pct, msg: self.progress.emit(pct, msg),
                )
            self.finished_ok.emit(str(self.out_path))
        except FfmpegError as exc:
            detail = f"{exc}\n\n{exc.stderr[-800:]}" if exc.stderr else str(exc)
            self.failed.emit(detail)
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            self.failed.emit(traceback.format_exc())
