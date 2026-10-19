"""Shared stylesheet and icon helper for every tab/widget in the app.

Colors follow the Windows theme. Dark theme uses white text. Light theme
uses black text. The UI font is Google Sans Medium when that family is
installed.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QStyle, QWidget

_theme_hooked = False


def icon(widget: QWidget, standard_pixmap: QStyle.StandardPixmap) -> QIcon:
    return widget.style().standardIcon(standard_pixmap)


def apply_font(app: QApplication) -> str:
    """Use Google Sans Medium, or Segoe UI when that family is missing."""
    family = _google_sans_family()
    font = QFont()
    if family == "Google Sans":
        font.setFamilies([family, "Segoe UI", "Arial"])
        font.setWeight(QFont.Weight.Medium)
        font.setStyleName("Medium")
    elif family:
        font.setFamilies([family, "Segoe UI", "Arial"])
    else:
        logging.warning("Google Sans Medium is not installed. Using Segoe UI.")
        font.setFamilies(["Segoe UI", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    return family or "Segoe UI"


def install_theme(app: QApplication) -> None:
    """Paint the app for the current scheme and repaint when Windows changes it."""
    global _theme_hooked
    _apply_theme(app)
    if _theme_hooked:
        return
    app.styleHints().colorSchemeChanged.connect(lambda *_changed: _apply_theme(app))
    _theme_hooked = True


def stylesheet(dark: bool, family: str) -> str:
    if dark:
        bg = "#14151a"
        nav = "#1b1c22"
        nav_border = "#2e303a"
        card = "#22232b"
        line = "#343644"
        text = "#ffffff"
        muted = "#b4b8c5"
        secondary = "#dedfe6"
        nav_item = "#d5d8e2"
        nav_selected_bg = "#2e3140"
        nav_hover = "#262833"
        field = "#1a1b21"
        field_border = "#3c3f4e"
        button = "#2a2c36"
        button_hover = "#343746"
        button_border = "#3c3f4e"
        disabled_text = "#7e8494"
        disabled_bg = "#23242c"
        alt = "#262833"
        selection = "#3d4270"
        progress = "#2a2c36"
        primary_disabled = "#3a3d66"
        primary_disabled_text = "#9aa0c7"
        hover_border = "#4b4f63"
    else:
        bg = "#f5f6fa"
        nav = "#eceef5"
        nav_border = "#e1e3ea"
        card = "#ffffff"
        line = "#e1e3ea"
        text = "#111111"
        muted = "#5c6370"
        secondary = "#333844"
        nav_item = "#3a3f4d"
        nav_selected_bg = "#ffffff"
        nav_hover = "#e3e6f0"
        field = "#ffffff"
        field_border = "#d6d9e3"
        button = "#ffffff"
        button_hover = "#eef0fb"
        button_border = "#d6d9e3"
        disabled_text = "#9aa0ad"
        disabled_bg = "#f2f3f7"
        alt = "#fafbfd"
        selection = "#e8eaff"
        progress = "#eceef5"
        primary_disabled = "#c8caf5"
        primary_disabled_text = "#ffffff"
        hover_border = "#b9c0f0"
    return f"""
* {{
    font-family: "{family}";
    font-weight: 500;
}}
QWidget {{
    color: {text};
}}
QMainWindow, QWidget#root, QDialog, QMessageBox {{
    background: {bg};
    color: {text};
}}
QListWidget#sideNav {{
    background: {nav};
    border: none;
    border-right: 1px solid {nav_border};
    border-radius: 0;
    padding: 12px 8px;
    outline: none;
    color: {nav_item};
}}
QListWidget#sideNav::item {{
    background: transparent;
    color: {nav_item};
    padding: 10px 12px;
    margin: 0;
    border-radius: 8px;
    font-weight: 500;
}}
QListWidget#sideNav::item:selected {{
    background: {nav_selected_bg};
    color: {text};
}}
QListWidget#sideNav::item:hover:!selected {{
    background: {nav_hover};
    color: {text};
}}
QLabel#title {{
    font-size: 20px;
    font-weight: 500;
    color: {text};
}}
QLabel#subtitle {{
    color: {muted};
    font-size: 12px;
}}
QLabel#sectionLabel {{
    color: {secondary};
    font-size: 12px;
    font-weight: 500;
}}
QListWidget, QTextEdit {{
    background: {card};
    color: {text};
    border: 1px solid {line};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {selection};
    selection-color: {text};
}}
QListWidget::item {{
    padding: 8px 6px;
    border-radius: 6px;
    color: {text};
}}
QListWidget::item:alternate {{
    background: {alt};
}}
QListWidget::item:selected {{
    background: {selection};
    color: {text};
}}
QFrame#card {{
    background: {card};
    border: 1px solid {line};
    border-radius: 8px;
}}
QPushButton {{
    background: {button};
    border: 1px solid {button_border};
    border-radius: 6px;
    padding: 6px 12px;
    color: {text};
    font-weight: 500;
}}
QPushButton:hover:!disabled {{
    background: {button_hover};
    border-color: {hover_border};
}}
QPushButton:disabled {{
    color: {disabled_text};
    background: {disabled_bg};
}}
QPushButton#primary {{
    background: #6366f1;
    border: 1px solid #6366f1;
    color: #ffffff;
    font-weight: 500;
    font-size: 13px;
}}
QPushButton#primary:hover:!disabled {{
    background: #575ae0;
}}
QPushButton#primary:disabled {{
    background: {primary_disabled};
    border-color: {primary_disabled};
    color: {primary_disabled_text};
}}
QCheckBox, QRadioButton {{
    color: {text};
}}
QLineEdit, QComboBox, QTextEdit, QAbstractItemView {{
    color: {text};
    selection-background-color: {selection};
    selection-color: {text};
}}
QLineEdit, QComboBox {{
    background: {field};
    border: 1px solid {field_border};
    border-radius: 6px;
    padding: 6px 8px;
    color: {text};
}}
QComboBox QAbstractItemView {{
    background: {card};
    color: {text};
    selection-background-color: {selection};
    selection-color: {text};
}}
QProgressBar {{
    background: {progress};
    border: none;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: {text};
}}
QProgressBar::chunk {{
    background: #6366f1;
    border-radius: 6px;
}}
"""


def _apply_theme(app: QApplication) -> None:
    dark = _is_dark(app)
    _apply_palette(app, dark)
    family = app.font().family() or "Google Sans"
    app.setStyleSheet(stylesheet(dark, family))


def _is_dark(app: QApplication) -> bool:
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    window = app.palette().color(QPalette.ColorRole.Window)
    return window.lightness() < 128


def _apply_palette(app: QApplication, dark: bool) -> None:
    palette = app.palette()
    if dark:
        window = QColor("#14151a")
        text = QColor("#ffffff")
        base = QColor("#1a1b21")
        placeholder = QColor("#9aa0b0")
        button = QColor("#2a2c36")
    else:
        window = QColor("#f5f6fa")
        text = QColor("#111111")
        base = QColor("#ffffff")
        placeholder = QColor("#6b7280")
        button = QColor("#ffffff")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    app.setPalette(palette)


def _google_sans_family() -> str | None:
    families = set(QFontDatabase.families())
    if "Google Sans" in families:
        return "Google Sans"
    if "Google Sans Medium" in families:
        return "Google Sans Medium"
    for path in _font_files():
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        loaded = QFontDatabase.applicationFontFamilies(font_id)
        if "Google Sans" in loaded:
            return "Google Sans"
        if loaded:
            return loaded[0]
    return None


def _font_files() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    windows = os.environ.get("WINDIR", r"C:\Windows")
    app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return [
        Path(local) / "Microsoft" / "Windows" / "Fonts" / "GoogleSans-Medium.ttf",
        Path(windows) / "Fonts" / "GoogleSans-Medium.ttf",
        app_dir / "fonts" / "GoogleSans-Medium.ttf",
    ]
