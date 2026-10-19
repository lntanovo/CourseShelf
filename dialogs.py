"""Confirmations use a safe default and an explicit consequence."""
from PySide6.QtWidgets import QMessageBox


def confirmation(parent, title, text, action):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText(action)
    box.button(QMessageBox.StandardButton.No).setText("否")
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setEscapeButton(QMessageBox.StandardButton.No)
    return box


def confirm(parent, title, text, action=None):
    return confirmation(parent, title, text, action or title).exec() == QMessageBox.StandardButton.Yes
