"""
全局样式：shadcn/ui slate 风格 + 蓝色主色调 + 思源黑体
"""

STYLE_SHEET = """
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", "Source Han Sans SC", sans-serif;
    font-size: 13px;
    font-weight: 400;
    color: #1E293B;
    background: #FFFFFF;
}

QWidget#appShell {
    background: #F8FAFC;
}

QFrame#sidebar {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
}

QFrame#contentFrame {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
}

QStackedWidget#contentStack {
    background: transparent;
    border: none;
}

QLabel {
    color: #1E293B;
    background: transparent;
}

QLabel#brandTitle {
    color: #0F172A;
    font-size: 18px;
    font-weight: 700;
}

QLabel#brandSubtitle {
    color: #64748B;
    font-size: 12px;
    font-weight: 400;
}

QLabel#sideNote {
    color: #94A3B8;
    font-size: 11px;
}

QLabel#lblTitle {
    font-size: 20px;
    font-weight: 700;
    color: #0F172A;
}

QLabel#lblSubtitle {
    font-size: 13px;
    color: #64748B;
}

QLabel#lblStatus {
    color: #475569;
    font-size: 12px;
}

QLabel#mutedText {
    color: #64748B;
}

QLabel#linkLabel {
    color: #2563EB;
    font-weight: 500;
}

QLabel#lblError {
    color: #DC2626;
}

/* ─── Buttons ─── */

QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
    font-size: 13px;
    min-height: 36px;
}

QPushButton:hover {
    background-color: #1D4ED8;
    border-color: #1D4ED8;
}

QPushButton:pressed {
    background-color: #1E40AF;
    border-color: #1E40AF;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border-color: #E2E8F0;
    color: #94A3B8;
}

QPushButton#navButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: #475569;
    font-size: 14px;
    font-weight: 500;
    padding: 9px 14px;
    text-align: left;
    min-height: 36px;
}

QPushButton#navButton:hover {
    background: #F1F5F9;
    color: #0F172A;
}

QPushButton#navButton:checked {
    background: #EFF6FF;
    border-color: #BFDBFE;
    color: #1D4ED8;
    font-weight: 600;
}

QPushButton#btnDanger {
    background-color: #DC2626;
    border-color: #DC2626;
    color: #FFFFFF;
}

QPushButton#btnDanger:hover {
    background-color: #B91C1C;
    border-color: #B91C1C;
}

QPushButton#btnSuccess {
    background-color: #16A34A;
    border-color: #16A34A;
    color: #FFFFFF;
}

QPushButton#btnSuccess:hover {
    background-color: #15803D;
    border-color: #15803D;
}

QPushButton#btnWarning {
    background-color: #D97706;
    border-color: #D97706;
    color: #FFFFFF;
}

QPushButton#btnWarning:hover {
    background-color: #B45309;
    border-color: #B45309;
}

QPushButton#btnFlat {
    background-color: #FFFFFF;
    color: #334155;
    border: 1px solid #E2E8F0;
}

QPushButton#btnFlat:hover {
    background-color: #F8FAFC;
    border-color: #CBD5E1;
    color: #0F172A;
}

/* ─── Inputs ─── */

QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 8px 12px;
    color: #0F172A;
    selection-background-color: #BFDBFE;
    selection-color: #0F172A;
    min-height: 22px;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #2563EB;
}

QLineEdit:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
}

/* ─── GroupBox (Card) ─── */

QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    margin-top: 20px;
    padding-top: 12px;
    color: #0F172A;
    font-weight: 600;
    font-size: 13px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 2px;
    padding: 2px 8px;
    color: #334155;
    background: #FFFFFF;
    border-radius: 4px;
    font-size: 13px;
    min-height: 16px;
}

/* ─── Tables & Trees ─── */

QTreeWidget, QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    gridline-color: #F1F5F9;
    outline: none;
    selection-background-color: #EFF6FF;
    selection-color: #0F172A;
}

QTreeWidget::viewport, QTableWidget::viewport {
    background-color: transparent;
    border-radius: 8px;
}

QTreeWidget::item, QTableWidget::item {
    padding: 8px 12px;
    border-bottom: 1px solid #F1F5F9;
    min-height: 32px;
}

QTreeWidget::item:hover, QTableWidget::item:hover {
    background-color: #F8FAFC;
}

QTreeWidget::item:selected, QTableWidget::item:selected {
    background-color: #EFF6FF;
    color: #0F172A;
}

QHeaderView::section {
    background-color: #F8FAFC;
    color: #64748B;
    padding: 8px 12px;
    border: none;
    border-right: 1px solid #F1F5F9;
    border-bottom: 1px solid #E2E8F0;
    font-weight: 500;
    font-size: 12px;
    min-height: 32px;
}

QHeaderView {
    background: transparent;
    border: none;
}

QHeaderView::section:first {
    border-top-left-radius: 7px;
}

QHeaderView::section:last {
    border-top-right-radius: 7px;
    border-right: none;
}

QTableCornerButton::section {
    background-color: #F8FAFC;
    border: none;
    border-bottom: 1px solid #E2E8F0;
    border-top-left-radius: 7px;
}

QAbstractScrollArea::corner {
    background: transparent;
    border: none;
}

/* ─── Progress Bar ─── */

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #E2E8F0;
    color: #475569;
    min-height: 20px;
    max-height: 20px;
    text-align: center;
    font-size: 11px;
}

QProgressBar::chunk {
    background-color: #2563EB;
    border-radius: 4px;
}

/* ─── ComboBox & SpinBox ─── */

QComboBox, QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 8px 12px;
    color: #0F172A;
    min-height: 30px;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background: #F8FAFC;
}

QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 0;
    border: none;
    background: transparent;
}

QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 0;
    border: none;
    background: transparent;
}

QSpinBox::up-arrow, QSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
}

QComboBox:hover, QSpinBox:hover {
    border-color: #94A3B8;
}

QComboBox:focus, QSpinBox:focus {
    border-color: #2563EB;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    selection-background-color: #EFF6FF;
    selection-color: #0F172A;
    outline: none;
    padding: 4px;
}

/* ─── Slider ─── */

QSlider::groove:horizontal {
    height: 6px;
    background: #E2E8F0;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #FFFFFF;
    border: 2px solid #2563EB;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}

QSlider::sub-page:horizontal {
    background: #2563EB;
    border-radius: 3px;
}

/* ─── ScrollBar ─── */

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #CBD5E1;
    min-height: 30px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #94A3B8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #CBD5E1;
    min-width: 30px;
    border-radius: 4px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ─── Status Bar ─── */

QStatusBar#appStatusBar {
    background-color: #F8FAFC;
    color: #64748B;
    border-top: 1px solid #E2E8F0;
    font-size: 12px;
}

/* ─── Menu ─── */

QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
    font-size: 13px;
}

QMenu::item:selected {
    background-color: #EFF6FF;
}

/* ─── CheckBox ─── */

QCheckBox {
    spacing: 8px;
    color: #0F172A;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #CBD5E1;
    background: #FFFFFF;
}

QCheckBox::indicator:checked {
    background: #2563EB;
    border-color: #2563EB;
}

/* ─── Misc ─── */

QFrame#browserPlaceholder {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}

QDialog, QMessageBox {
    background-color: #FFFFFF;
}

QToolTip {
    background-color: #1E293B;
    color: #F8FAFC;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}
"""
