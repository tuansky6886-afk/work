"""Video Joiner — a small PyQt6 GUI to concatenate video files.

A global excepthook is installed below: PyQt6 aborts the whole process
with no visible traceback when an exception escapes a Qt slot, so every
unexpected error (bad file, disk full, ffmpeg surprise) must be caught and
shown to the user instead of silently killing the app.
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

# When PyInstaller-frozen, `__file__` resolves inside the temporary
# _MEIPASS extraction folder (deleted on exit) rather than next to the
# actual .exe — use sys.executable's directory in that case so the log
# actually survives the app closing.
_APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
LOG_PATH = _APP_DIR / "videojoiner.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error("Unhandled exception:\n%s", text)
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(
            None,
            "Unexpected error",
            f"An unexpected error occurred:\n\n{exc_value}\n\nDetails were written to:\n{LOG_PATH}",
        )
    else:
        sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook


def main() -> int:
    app = QApplication(sys.argv)

    from app.main_window import MainWindow
    from app.style import apply_font, install_theme

    apply_font(app)
    install_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
