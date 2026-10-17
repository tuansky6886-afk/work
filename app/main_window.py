from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QTabWidget

from app.audio_tab import AudioTab
from app.join_tab import JoinTab
from app.style import STYLESHEET
from app.subtitle_tab import SubtitleTab
from app.youtube_tab import YouTubeTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Joiner")
        self.resize(920, 720)
        self.setStyleSheet(STYLESHEET)

        tabs = QTabWidget()
        tabs.addTab(JoinTab(), "Join Videos")
        tabs.addTab(SubtitleTab(), "Subtitles")
        tabs.addTab(YouTubeTab(), "YouTube Lyrics")
        tabs.addTab(AudioTab(), "Add Music")
        self.setCentralWidget(tabs)
