"""Four coordinated palettes; all controls use the active theme tokens."""
from string import Template

THEMES = {
    "paper": dict(name="暖纸", hint="温暖的纸张与松针色", base="#F5F2EB", surface="#FFFDFA",
                  field="#FBF8F2", border="#E8E1D4", text="#35433D", muted="#747B71",
                  accent="#566E5E", hover="#EDE8DD", selection="#E0E8DB", light="#FFFFFF"),
    "sage": dict(name="鼠尾草", hint="安静的浅绿与奶白", base="#EDF2EC", surface="#FAFCF8",
                 field="#F2F6EF", border="#DAE4D5", text="#33483B", muted="#6B7E6D",
                 accent="#526F54", hover="#E2EBDD", selection="#D9E8D1", light="#FFFFFF"),
    "mist": dict(name="雾蓝", hint="轻盈的灰蓝与浅砂色", base="#EDF2F5", surface="#FAFCFD",
                 field="#F2F6F8", border="#D9E3E8", text="#344752", muted="#6F818B",
                 accent="#4D7183", hover="#E1EAF0", selection="#D8E7EF", light="#FFFFFF"),
    "ink": dict(name="夜墨", hint="低亮度的石墨与柔绿", base="#202725", surface="#29312E",
                field="#252D2A", border="#3B4640", text="#E2E7DF", muted="#A7B2A7",
                accent="#B1C6A6", hover="#344039", selection="#40533E", light="#202725"),
}

_QSS = Template("""
QWidget { font-family: 'Microsoft YaHei', 'Microsoft YaHei UI'; font-size: 13px; color: $text; }
QMainWindow, QDialog { background: $base; }
QWidget#tabBody, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#sidebar { background: $surface; border: 1px solid $border; border-radius: 20px; }
QLabel#brand { font-size: 22px; font-weight: 700; letter-spacing: -1px; }
QLabel#heading { font-size: 27px; font-weight: 600; }
QLabel#subtitle, QLabel#muted, QLabel#pathText { color: $muted; }
QLabel#eyebrow { color: $accent; font-size: 11px; font-weight: 600; }
QLabel#warning { color: $accent; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
QLabel#imagePreview { background: $field; border: 1px dashed $border; border-radius: 16px; color: $muted; padding: 12px; }
QLabel#destination { padding: 10px; background: $selection; border-radius: 10px; color: $text; }
QFrame#rootCard, QFrame#actionBar, QFrame#detailPanel { background: $surface; border: 1px solid $border; border-radius: 14px; }
QGroupBox { background: $surface; border: 1px solid $border; border-radius: 16px; margin-top: 18px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 18px; padding: 0 6px; color: $muted; }
QLineEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget { background: $field; color: $text; border: 1px solid $border; border-radius: 9px; padding: 7px; selection-background-color: $selection; selection-color: $text; }
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus { border: 1px solid $accent; }
QLineEdit#rootPath { background: transparent; border: none; font-size: 12px; }
QComboBox { padding-right: 22px; min-height: 20px; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView { background: $surface; color: $text; selection-background-color: $selection; selection-color: $text; outline: 0; }
QAbstractItemView { alternate-background-color: $surface; outline: 0; }
QAbstractItemView::item { padding: 3px; border: none; }
QAbstractItemView::item:selected { background: $selection; color: $text; }
QPushButton, QToolButton { background: $field; color: $text; border: 1px solid $border; border-radius: 10px; padding: 9px 14px; font-weight: 500; }
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $muted; }
QPushButton#primary { background: $accent; color: $light; border-color: $accent; font-weight: 600; padding: 10px 22px; }
QPushButton#primary:hover { background: $text; color: $base; }
QPushButton:disabled, QToolButton:disabled { color: $muted; background: $field; border-color: $border; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 13px 16px; font-size: 14px; border-radius: 12px; }
QPushButton#nav:hover { background: $hover; }
QPushButton#nav:checked { background: $selection; color: $text; font-weight: 600; }
QPushButton#quiet { background: transparent; border-color: transparent; color: $muted; }
QPushButton#quiet:hover { background: $hover; color: $text; }
QToolButton#disclosure { background: transparent; border: none; padding: 8px 2px; text-align: left; color: $muted; }
QPushButton#themeChoice { text-align: left; padding: 18px; min-height: 34px; }
QPushButton#themeChoice:checked { border: 2px solid $accent; background: $selection; }
QTabWidget::pane { border: none; background: transparent; }
QHeaderView::section { background: $surface; color: $muted; padding: 10px 8px; border: none; border-bottom: 1px solid $border; font-weight: 500; }
QTableWidget { gridline-color: $border; }
QTableWidget QComboBox { border: none; border-radius: 5px; padding: 3px 18px 3px 5px; min-height: 18px; }
QSplitter::handle { background: $border; width: 1px; height: 1px; margin: 6px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; min-height: 26px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: $field; border: none; border-radius: 3px; height: 6px; max-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QStatusBar { background: $base; color: $muted; font-size: 11px; border: none; }
QStatusBar::item { border: none; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QRadioButton::indicator { background: $field; border: 1px solid $muted; border-radius: 8px; }
QRadioButton::indicator:checked { background: $accent; border-color: $accent; }
QMenu { background: $surface; border: 1px solid $border; padding: 6px; }
QMenu::item { padding: 9px 24px; border-radius: 5px; }
QMenu::item:selected { background: $selection; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 5px; }
QSlider::groove:horizontal { background: $border; height: 5px; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: 16px; margin: -5px 0; border-radius: 8px; }
""")


def stylesheet(theme="paper"):
    return _QSS.substitute(THEMES.get(theme, THEMES["paper"]))


STYLE = stylesheet()
