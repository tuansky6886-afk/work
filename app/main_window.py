from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QListWidget, QMainWindow, QStackedWidget, QWidget

from app.audio_tab import AudioTab
from app.join_tab import JoinTab
from app.scene_tab import SceneTab
from app.subtitle_tab import SubtitleTab
from app.youtube_tab import YouTubeTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Joiner")
        self.resize(1100, 720)

        root = QWidget()
        root.setObjectName("root")
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("sideNav")
        self.nav.setFixedWidth(176)
        self.nav.setSpacing(4)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.stack = QStackedWidget()
        pages = (
            (JoinTab(), "Join Videos"),
            (SubtitleTab(), "Subtitles"),
            (YouTubeTab(), "YouTube Lyrics"),
            (SceneTab(), "Scene Prompts"),
            (AudioTab(), "Add Music"),
        )
        for page, label in pages:
            self.stack.addWidget(page)
            self.nav.addItem(label)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        row.addWidget(self.nav)
        row.addWidget(self.stack, stretch=1)
        self.setCentralWidget(root)
