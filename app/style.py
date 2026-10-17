"""Shared stylesheet and icon helper for every tab/widget in the app."""

from __future__ import annotations

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyle, QWidget

STYLESHEET = """
* {
    font-family: "Aptos", "Segoe UI Variable Text", "Segoe UI", "Arial";
}
QMainWindow, QWidget#root {
    background: #f5f6fa;
}
QTabWidget::pane {
    border: none;
    background: #f5f6fa;
}
QTabBar::tab {
    background: #eceef5;
    color: #5a5f70;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #2f3a8f;
}
QLabel#title {
    font-size: 20px;
    font-weight: 600;
    color: #1f2333;
}
QLabel#subtitle {
    color: #6b7080;
    font-size: 12px;
}
QLabel#sectionLabel {
    color: #444a5a;
    font-size: 12px;
    font-weight: 600;
}
QListWidget, QTextEdit {
    background: #ffffff;
    border: 1px solid #e1e3ea;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 8px 6px;
    border-radius: 6px;
    color: #1f2333;
}
QListWidget::item:alternate {
    background: #fafbfd;
}
QListWidget::item:selected {
    background: #e8eaff;
    color: #2f3a8f;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #e1e3ea;
    border-radius: 8px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d6d9e3;
    border-radius: 6px;
    padding: 6px 12px;
    color: #2b2f3a;
}
QPushButton:hover:!disabled {
    background: #eef0fb;
    border-color: #b9c0f0;
}
QPushButton:disabled {
    color: #a7abb8;
    background: #f2f3f7;
}
QPushButton#primary {
    background: #6366f1;
    border: 1px solid #6366f1;
    color: #ffffff;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#primary:hover:!disabled {
    background: #575ae0;
}
QPushButton#primary:disabled {
    background: #c8caf5;
    border-color: #c8caf5;
    color: #ffffff;
}
QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #d6d9e3;
    border-radius: 6px;
    padding: 6px 8px;
}
QProgressBar {
    background: #eceef5;
    border: none;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #444a5a;
}
QProgressBar::chunk {
    background: #6366f1;
    border-radius: 6px;
}
"""


def icon(widget: QWidget, standard_pixmap: QStyle.StandardPixmap) -> QIcon:
    return widget.style().standardIcon(standard_pixmap)
