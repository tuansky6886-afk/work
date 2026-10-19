"""Background scan for the Scene Prompts tab.

Gemini calls must not run on the Qt GUI thread, and an exception must not
escape the thread (PyQt aborts the process when that happens).
"""

from __future__ import annotations

import logging
import threading
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from app.scene_scan import ScanCancelled, scan_to_prompt
from app.scene_utils import SceneScanError


class ScanScenesWorker(QThread):
    progress = pyqtSignal(int, int, str)
    confirm_count = pyqtSignal(int, int, int, bool)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, url: str, api_key: str, model: str, aspect_override: str | None, fast_cuts: bool) -> None:
        super().__init__()
        self.url = url
        self.api_key = api_key
        self.model = model
        self.aspect_override = aspect_override
        self.fast_cuts = fast_cuts
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self._accepted = False

    def cancel(self) -> None:
        self._cancel.set()
        self.answer_confirm(False)

    def answer_confirm(self, accepted: bool) -> None:
        """Called on the GUI thread. The first answer wins."""
        if self._confirm.is_set():
            return
        self._accepted = accepted
        self._confirm.set()

    def run(self) -> None:
        try:
            result = scan_to_prompt(
                self.url,
                self.api_key,
                self.model,
                aspect_override=self.aspect_override,
                fast_cuts=self.fast_cuts,
                on_progress=self.progress.emit,
                cancel_event=self._cancel,
                confirm_many=self._ask_confirm,
            )
            self.finished_ok.emit(result)
        except ScanCancelled as exc:
            if exc.output is not None:
                self.finished_ok.emit(exc.output)
            else:
                self.failed.emit("")
        except SceneScanError as exc:
            self.failed.emit(str(exc))
        except Exception:  # noqa: BLE001 - last-resort backstop, never let the thread die silently
            logging.exception("Scene scan failed")
            self.failed.emit(traceback.format_exc())

    def _ask_confirm(self, scene_count: int, duration_seconds: int, remainder: int, capped: bool) -> bool:
        if self._cancel.is_set():
            return False
        self._confirm.clear()
        self._accepted = False
        self.confirm_count.emit(scene_count, duration_seconds, remainder, capped)
        self._confirm.wait()
        return self._accepted
