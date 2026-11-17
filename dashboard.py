import os
import json
import shutil
import ctypes
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QComboBox, QColorDialog, QFontComboBox, QApplication, QFrame,
    QStackedWidget, QScrollArea, QGridLayout, QCheckBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPixmap, QIcon

DARK_STYLESHEET = """
QWidget {
    background-color: #111318;
    color: #F1F5F9;
    font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
    font-size: 13px;
}
#Sidebar {
    background-color: #0B0D11;
    border-right: 1px solid #1E293B;
}
#AppTitle {
    font-size: 17px;
    font-weight: 700;
    color: #FFFFFF;
    padding: 8px 4px;
}
QPushButton#NavBtn {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 11px 14px;
    text-align: left;
    font-size: 14px;
    font-weight: 500;
    color: #94A3B8;
}
QPushButton#NavBtn:hover {
    background-color: #1A1D24;
    color: #F8FAFC;
}
QPushButton#NavBtn[active="true"] {
    background-color: #1E293B;
    color: #38BDF8;
    font-weight: 600;
}
QPushButton#PrimaryBtn {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#PrimaryBtn:hover {
    background-color: #3B82F6;
}
QPushButton#SecondaryBtn {
    background-color: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 14px;
}
QPushButton#SecondaryBtn:hover {
    background-color: #334155;
}
QFrame#Card {
    background-color: #181B22;
    border: 1px solid #262B36;
    border-radius: 12px;
}
QFrame#Card:hover {
    border: 1px solid #3B82F6;
}
QLabel#SectionHeader {
    font-size: 20px;
    font-weight: 700;
    color: #FFFFFF;
}
QLabel#SubText {
    color: #94A3B8;
    font-size: 12px;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #262B36;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #3B82F6;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QComboBox, QFontComboBox {
    background-color: #181B22;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #F8FAFC;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""


class PresetCard(QFrame):
    selected = Signal(dict)
    deleted = Signal(str)

    def __init__(self, meta: dict, is_active: bool = False):
        super().__init__()
        self.meta = meta
        self.setObjectName("Card")
        self.setFixedSize(240, 195)
        self.setCursor(Qt.PointingHandCursor)

        if is_active:
            self.setStyleSheet("QFrame#Card { border: 2px solid #3B82F6; background-color: #1E2430; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        thumb_label = QLabel()
        thumb_label.setFixedSize(222, 125)
        thumb_label.setStyleSheet("border-radius: 6px; background-color: #0F172A;")
        if os.path.exists(meta["thumb_path"]):
            pix = QPixmap(meta["thumb_path"]).scaled(
                222, 125, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            thumb_label.setPixmap(pix)
        layout.addWidget(thumb_label)

        bottom_row = QHBoxLayout()
        name_lbl = QLabel(meta.get("name", "Wallpaper")[:20])
        name_lbl.setStyleSheet("font-weight: 600; background: transparent;")
        bottom_row.addWidget(name_lbl)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(
            "background: transparent; color: #64748B; border: none; font-weight: bold;"
        )
        del_btn.setToolTip("Delete Preset")
        del_btn.clicked.connect(lambda: self.deleted.emit(meta["id"]))
        bottom_row.addWidget(del_btn)

        layout.addLayout(bottom_row)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.meta)


class LivelyDashboard(QWidget):
    settings_changed = Signal(dict)
    add_wallpaper_requested = Signal()
    preset_selected = Signal(dict)
    startup_toggled = Signal(bool)

    def __init__(self, current_config: dict):
        super().__init__()
        self.config = current_config.copy()
        self.setWindowTitle("DepthFlow — Live Depth Wallpaper")
        self.resize(920, 600)
        self.setStyleSheet(DARK_STYLESHEET)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- LEFT SIDEBAR ---
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 18, 14, 18)
        side_layout.setSpacing(8)

        title = QLabel("✦ DepthFlow")
        title.setObjectName("AppTitle")
        side_layout.addWidget(title)

        add_btn = QPushButton("+  Add Wallpaper")
        add_btn.setObjectName("PrimaryBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.add_wallpaper_requested.emit)
        side_layout.addWidget(add_btn)

        side_layout.addSpacing(12)

        self.nav_buttons = []
        pages = [
            ("🖼   Library", 0),
            ("🕒   Customize Clock", 1),
            ("⚙   System & Effects", 2)
        ]
        for label, idx in pages:
            btn = QPushButton(label)
            btn.setObjectName("NavBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self.switch_page(i))
            side_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        side_layout.addStretch()

        status_lbl = QLabel("Windows 11 Depth Engine\nStatus: Active")
        status_lbl.setObjectName("SubText")
        side_layout.addWidget(status_lbl)

        root.addWidget(sidebar)

        # --- RIGHT CONTENT STACK ---
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.stack.addWidget(self._build_library_page())
        self.stack.addWidget(self._build_clock_page())
        self.stack.addWidget(self._build_settings_page())

        self.switch_page(0)

    def switch_page(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 0:
            self.refresh_library()

    # --- PAGE 0: WALLPAPER LIBRARY ---
    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header = QLabel("Wallpaper Library")
        header.setObjectName("SectionHeader")
        header_row.addWidget(header)
        header_row.addStretch()

        self.loading_lbl = QLabel("")
        self.loading_lbl.setStyleSheet("color: #38BDF8; font-weight: 600;")
        header_row.addWidget(self.loading_lbl)
        layout.addLayout(header_row)

        sub = QLabel("Click any saved wallpaper to apply instantly, or click '+ Add Wallpaper' to process a new image.")
        sub.setObjectName("SubText")
        layout.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self.grid_container)

        layout.addWidget(scroll)
        return page

    def refresh_library(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        presets_dir = "assets/presets"
        os.makedirs(presets_dir, exist_ok=True)
        active_id = self.config.get("active_preset_id", "")

        row, col = 0, 0
        for folder in sorted(os.listdir(presets_dir), reverse=True):
            meta_file = os.path.join(presets_dir, folder, "meta.json")
            if os.path.exists(meta_file):
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                card = PresetCard(meta, is_active=(meta["id"] == active_id))
                card.selected.connect(self._on_card_clicked)
                card.deleted.connect(self._on_card_deleted)
                self.grid_layout.addWidget(card, row, col)
                col += 1
                if col >= 2:
                    col = 0
                    row += 1

    def _on_card_clicked(self, meta: dict):
        self.config["active_preset_id"] = meta["id"]
        self.config["bg_path"] = meta["bg_path"]
        self.config["fg_path"] = meta["fg_path"]
        self.preset_selected.emit(meta)
        self.refresh_library()

    def _on_card_deleted(self, preset_id: str):
        folder = os.path.join("assets/presets", preset_id)
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
        self.refresh_library()

    def set_processing_status(self, text: str):
        self.loading_lbl.setText(text)

    def _on_preset_style_picked(self):
        preset = self.style_combo.currentData()
        # Automatically suggest a fitting font when switching presets (user can still override it)
        font_map = {
            "classic": "Segoe UI Variable Display",
            "stacked": "Segoe UI Variable Display",
            "editorial": "Georgia",
            "tech_mono": "Consolas",
            "outline": "Segoe UI Variable Display",
            "liquid_glass": "Segoe UI Variable Display"
        }
        if preset in font_map:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentFont(font_map[preset])
            self.font_combo.blockSignals(False)
        self._emit_settings()

    # --- PAGE 1: CUSTOMIZE CLOCK ---
    def _build_clock_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        header = QLabel("Clock & Depth Styling")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        card = QFrame()
        card.setObjectName("Card")
        form = QVBoxLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(14)

        # Clock Style Preset Selector
        form.addWidget(QLabel("Clock Style Preset"))
        self.style_combo = QComboBox()
        self.style_combo.addItem("Liquid Glass (iOS 26 Frosted)", "liquid_glass")
        self.style_combo.addItem("Classic Horizontal (iOS Bold)", "classic")
        self.style_combo.addItem("Stacked Vertical (Android / Pixel)", "stacked")
        self.style_combo.addItem("Editorial Serif (Magazine)", "editorial")
        self.style_combo.addItem("Tech Mono (Nothing OS Style)", "tech_mono")
        self.style_combo.addItem("Hollow Outline (See-Through)", "outline")

        saved_style = self.config.get("clock_style", "classic")
        style_idx = self.style_combo.findData(saved_style)
        if style_idx >= 0:
            self.style_combo.setCurrentIndex(style_idx)
        self.style_combo.currentIndexChanged.connect(self._on_preset_style_picked)
        form.addWidget(self.style_combo)

        # Vertical Position
        form.addWidget(QLabel("Vertical Position (Top ↔ Bottom)"))
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(0, 75)
        self.y_slider.setValue(int(self.config.get("y_percent", 12)))
        self.y_slider.valueChanged.connect(self._emit_settings)
        form.addWidget(self.y_slider)

        # Horizontal Position
        form.addWidget(QLabel("Horizontal Offset (Left ↔ Right)"))
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(-35, 35)
        self.x_slider.setValue(int(self.config.get("x_offset_percent", 0)))
        self.x_slider.valueChanged.connect(self._emit_settings)
        form.addWidget(self.x_slider)

        # Font Size
        form.addWidget(QLabel("Clock Font Size"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(60, 260)
        self.size_slider.setValue(int(self.config.get("font_size", 150)))
        self.size_slider.valueChanged.connect(self._emit_settings)
        form.addWidget(self.size_slider)

        # Date-to-Clock Vertical Gap
        form.addWidget(QLabel("Date to Clock Spacing"))
        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setRange(-90, 60)
        self.gap_slider.setValue(int(self.config.get("date_clock_gap", -25)))
        self.gap_slider.valueChanged.connect(self._emit_settings)
        form.addWidget(self.gap_slider)

        # Font Family & 12h/24h Format Row
        row1 = QHBoxLayout()
        col_font = QVBoxLayout()
        col_font.addWidget(QLabel("Font Family"))
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(self.config.get("font_family", "Segoe UI Variable Display"))
        self.font_combo.currentFontChanged.connect(self._emit_settings)
        col_font.addWidget(self.font_combo)
        row1.addLayout(col_font)

        col_fmt = QVBoxLayout()
        col_fmt.addWidget(QLabel("Time Format"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["24-Hour (14:30)", "12-Hour (02:30 PM)"])
        self.format_combo.setCurrentIndex(1 if self.config.get("use_12h", False) else 0)
        self.format_combo.currentIndexChanged.connect(self._emit_settings)
        col_fmt.addWidget(self.format_combo)
        row1.addLayout(col_fmt)
        form.addLayout(row1)

        # Color & Shadow Controls
        row2 = QHBoxLayout()
        color_btn = QPushButton("Pick Clock Color")
        color_btn.setObjectName("SecondaryBtn")
        color_btn.clicked.connect(self._pick_color)
        row2.addWidget(color_btn)

        auto_color_btn = QPushButton("Auto-Contrast Color")
        auto_color_btn.setObjectName("SecondaryBtn")
        auto_color_btn.clicked.connect(self._apply_auto_color)
        row2.addWidget(auto_color_btn)
        form.addLayout(row2)

        self.show_date_check = QCheckBox("Show Date Above Clock")
        self.show_date_check.setChecked(self.config.get("show_date", True))
        self.show_date_check.stateChanged.connect(self._emit_settings)
        form.addWidget(self.show_date_check)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- PAGE 2: SYSTEM & PERFORMANCE ---
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        header = QLabel("System & Performance")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        card = QFrame()
        card.setObjectName("Card")
        form = QVBoxLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(16)

        # AI Model Selector (Hidden for now — defaults to isnet-general-use)
        self.model_label = QLabel("AI Subject Segmentation Model")
        self.model_label.hide()
        self.model_combo = QComboBox()
        self.model_combo.addItem("ISNet General (Fast — ~1s per image, great accuracy)", "isnet-general-use")
        self.model_combo.addItem("BiRefNet General (Ultra Quality — ~4s per image, best hair edges)", "birefnet-general")
        self.model_combo.addItem("U2NetP (Lightweight — ~0.4s per image, low RAM)", "u2netp")
        saved_model = self.config.get("ai_model", "isnet-general-use")
        idx = self.model_combo.findData(saved_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.currentIndexChanged.connect(self._emit_settings)
        self.model_combo.hide()

        # Parallax Toggle
        self.parallax_check = QCheckBox("Enable Subtle 3D Mouse Parallax Motion")
        self.parallax_check.setChecked(self.config.get("enable_parallax", True))
        self.parallax_check.stateChanged.connect(self._emit_settings)
        form.addWidget(self.parallax_check)

       # Pause in Fullscreen Apps
        self.pause_fullscreen_check = QCheckBox("Pause 3D Parallax During Fullscreen Applications / Games")
        self.pause_fullscreen_check.setChecked(self.config.get("pause_fullscreen", True))
        self.pause_fullscreen_check.stateChanged.connect(self._emit_settings)
        form.addWidget(self.pause_fullscreen_check)

        # Pause in Windowed Apps
        self.pause_windowed_check = QCheckBox("Pause 3D Parallax When Any Application Window Is Focused")
        self.pause_windowed_check.setChecked(self.config.get("pause_windowed", False))
        self.pause_windowed_check.stateChanged.connect(self._emit_settings)
        form.addWidget(self.pause_windowed_check)

        # Start with Windows
        self.startup_check = QCheckBox("Launch Automatically When Windows Starts")
        self.startup_check.setChecked(self.config.get("start_with_windows", False))
        self.startup_check.stateChanged.connect(self._on_startup_changed)
        form.addWidget(self.startup_check)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _pick_color(self):
        initial = QColor(self.config.get("color", "#FFFFFF"))
        color = QColorDialog.getColor(initial, self, "Select Clock Color")
        if color.isValid():
            self.config["color"] = color.name()
            self._emit_settings()

    def _apply_auto_color(self):
        bg_path = self.config.get("bg_path", "")
        if bg_path and os.path.exists(bg_path):
            from PIL import Image
            from segmenter import suggest_clock_color
            self.config["color"] = suggest_clock_color(Image.open(bg_path), self.y_slider.value())
            self._emit_settings()

    def _on_startup_changed(self):
        enabled = self.startup_check.isChecked()
        self.config["start_with_windows"] = enabled
        self.startup_toggled.emit(enabled)
        self._emit_settings()

    def _emit_settings(self):
        self.config["y_percent"] = self.y_slider.value()
        self.config["x_offset_percent"] = self.x_slider.value()
        self.config["clock_style"] = self.style_combo.currentData()
        self.config["date_clock_gap"] = self.gap_slider.value()
        self.config["font_size"] = self.size_slider.value()
        self.config["font_family"] = self.font_combo.currentFont().family()
        self.config["use_12h"] = (self.format_combo.currentIndex() == 1)
        self.config["show_date"] = self.show_date_check.isChecked()
        self.gap_slider.setEnabled(self.show_date_check.isChecked())
        self.config["ai_model"] = self.model_combo.currentData()
        parallax_on = self.parallax_check.isChecked()
        self.config["enable_parallax"] = parallax_on
        self.config["pause_fullscreen"] = self.pause_fullscreen_check.isChecked()
        self.config["pause_windowed"] = self.pause_windowed_check.isChecked()

        self.pause_fullscreen_check.setEnabled(parallax_on)
        self.pause_windowed_check.setEnabled(parallax_on)
        self.settings_changed.emit(self.config)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        try:
            ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        except Exception:
            pass