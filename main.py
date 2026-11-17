import sys
import os
import gc  # Added missing gc import

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)  # Ensures config.json and assets/ always resolve next to DepthFlow.exe

import json
import ctypes
import winreg
from datetime import datetime
import win32gui
import win32con
import win32api

from PIL import Image, ImageFilter
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QSystemTrayIcon, QMenu,
    QFileDialog
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import (
    QPixmap, QFont, QIcon, QAction, QColor, QCursor,
    QPainter, QPainterPath, QPen, QLinearGradient, QImage
)

from segmenter import process_wallpaper
from dashboard import LivelyDashboard

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "clock_style": "classic",
    "date_clock_gap": -25,
    "y_percent": 12,
    "x_offset_percent": 0,
    "font_size": 150,
    "font_family": "Segoe UI Variable Display",
    "color": "#FFFFFF",
    "use_12h": False,
    "show_date": True,
    "enable_shadow": True,
    "enable_parallax": True,
    "pause_fullscreen": True,
    "pause_windowed": False,
    "start_with_windows": False,
    "ai_model": "isnet-general-use",
    "bg_path": "assets/bg.png",
    "fg_path": "assets/fg.png",
    "active_preset_id": ""
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return {**DEFAULT_CONFIG, **json.loads(content)}
        except json.JSONDecodeError:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def set_windows_startup(enable: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "DepthFlowWallpaper"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --minimized'
            else:
                cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}" --minimized'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print("Startup registry error:", e)


def set_native_windows_wallpaper(image_path: str):
    if not os.path.exists(image_path):
        return
    abs_path = os.path.abspath(image_path)
    ctypes.windll.user32.SystemParametersInfoW(20, 0, abs_path, 0x01 | 0x02)


def attach_overlay_to_desktop(hwnd: int, width: int, height: int):
    progman = win32gui.FindWindow("Progman", None)
    child_workerw = win32gui.FindWindowEx(progman, 0, "WorkerW", None)
    if child_workerw:
        win32gui.ShowWindow(child_workerw, win32con.SW_SHOW)

    GWLP_HWNDPARENT = -8
    ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, progman)

    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style |= (
        win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_NOACTIVATE
        | win32con.WS_EX_TRANSPARENT
    )
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    # Pin strictly at the bottom of the Z-order so taskbar & desktop icons stay on top
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_BOTTOM, 0, 0, width, height,
        win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
    )


def get_foreground_window_state(screen_w: int, screen_h: int) -> str:
    """Returns 'desktop', 'windowed', or 'fullscreen' for the active foreground app."""
    fg = win32gui.GetForegroundWindow()
    if not fg or not win32gui.IsWindowVisible(fg):
        return "desktop"

    cls = win32gui.GetClassName(fg)
    if cls in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return "desktop"

    # Ignore DepthFlow's own dashboard window so you can still preview parallax while tweaking settings
    title = win32gui.GetWindowText(fg)
    if title.startswith("DepthFlow"):
        return "desktop"

    left, top, right, bottom = win32gui.GetWindowRect(fg)
    if (right - left) >= screen_w and (bottom - top) >= screen_h:
        return "fullscreen"
    return "windowed"

class SegmentationWorker(QThread):
    finished = Signal(dict)

    def __init__(self, image_path: str, width: int, height: int, model_name: str):
        super().__init__()
        self.image_path = image_path
        self.width = width
        self.height = height
        self.model_name = model_name

    def run(self):
        meta = process_wallpaper(self.image_path, self.width, self.height, self.model_name)
        self.finished.emit(meta)


class StyledClockWidget(QWidget):
    """Renders Classic, Stacked, Editorial, Tech Mono, Hollow Outline, and Liquid Glass clocks."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.style_mode = "classic"
        self.hours_text = "12"
        self.mins_text = "00"
        self.show_date = True
        self.date_text = "TUESDAY, NOV 17"
        self.date_clock_gap = -25
        self.font_family = "Segoe UI Variable Display"
        self.font_size = 150
        self.color = QColor("#FFFFFF")
        self.blurred_bg_pixmap = None

    def set_background_source(self, bg_path: str):
        self.bg_path = bg_path
        if self.style_mode == "liquid_glass":
            self._build_blurred_bg()
        else:
            self.blurred_bg_pixmap = None

    def _build_blurred_bg(self):
        if not getattr(self, "bg_path", "") or not os.path.exists(self.bg_path):
            self.blurred_bg_pixmap = None
            return
        # Downscale by 4x before blurring — identical frosted look, 16x less RAM & instant blur
        img = Image.open(self.bg_path).convert("RGBA")
        small = img.resize((max(1, img.width // 4), max(1, img.height // 4)), Image.Resampling.BILINEAR)
        blurred = small.filter(ImageFilter.GaussianBlur(radius=6))
        blurred = blurred.resize((img.width, img.height), Image.Resampling.BILINEAR)
        data = blurred.tobytes("raw", "RGBA")
        qimg = QImage(data, blurred.width, blurred.height, QImage.Format_RGBA8888)
        self.blurred_bg_pixmap = QPixmap.fromImage(qimg)

    def update_state(self, style_mode: str, font_family: str, font_size: int, color_hex: str, date_clock_gap: int = -25, show_date: bool = True):
        if style_mode == "liquid_glass" and self.blurred_bg_pixmap is None:
            self._build_blurred_bg()
        elif style_mode != "liquid_glass" and self.blurred_bg_pixmap is not None:
            self.blurred_bg_pixmap = None
            gc.collect()
        self.style_mode = style_mode
        self.font_family = font_family
        self.font_size = font_size
        self.color = QColor(color_hex)
        self.date_clock_gap = date_clock_gap
        self.show_date = show_date
        self.update()

    def set_time_strings(self, hours: str, mins: str, date_str: str):
        if (hours, mins, date_str) != (self.hours_text, self.mins_text, self.date_text):
            self.hours_text = hours
            self.mins_text = mins
            self.date_text = date_str
            self.update()

    def _draw_liquid_glass_path(self, painter: QPainter, path: QPainterPath):
        """Renders realistic frosted glass refraction, tint, and specular rim highlights."""
        painter.save()
        painter.setClipPath(path)

        # 1. Draw the refracted/blurred background aligned to screen coordinates
        if self.blurred_bg_pixmap:
            # Map widget's current position on screen so background lines up seamlessly
            pos = self.pos()
            painter.drawPixmap(-pos.x(), -pos.y(), self.blurred_bg_pixmap)

        # 2. Translucent frosted milk/glass gradient tint (brighter at top, deeper at bottom)
        bounds = path.boundingRect()
        glass_grad = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
        tint_top = QColor(self.color)
        tint_top.setAlpha(115)
        tint_bottom = QColor(self.color)
        tint_bottom.setAlpha(45)
        glass_grad.setColorAt(0.0, tint_top)
        glass_grad.setColorAt(0.55, QColor(255, 255, 255, 35))
        glass_grad.setColorAt(1.0, tint_bottom)
        painter.fillPath(path, glass_grad)

        # 3. Glossy upper specular reflection band (gives the curved 3D glass lens look)
        gloss_grad = QLinearGradient(bounds.topLeft(), bounds.center())
        gloss_grad.setColorAt(0.0, QColor(255, 255, 255, 130))
        gloss_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, gloss_grad)
        painter.restore()

        # 4. Crisp outer specular glass rim border
        rim_grad = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 220))
        rim_grad.setColorAt(0.5, QColor(255, 255, 255, 90))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 180))

        rim_pen = QPen(rim_grad, max(2.0, self.font_size * 0.016))
        rim_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(rim_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w = self.width()
        date_size = max(14, int(self.font_size * 0.16))
        date_rect_h = date_size + 18

     # 1. Draw Date Header (if enabled)
        if self.show_date:
            date_font = QFont(self.font_family, date_size, QFont.DemiBold)
            date_font.setLetterSpacing(QFont.AbsoluteSpacing, 4 if self.style_mode == "editorial" else 2.5)
            painter.setFont(date_font)

            date_color = QColor(self.color)
            if self.style_mode == "liquid_glass":
                date_color.setAlpha(215)
            painter.setPen(date_color)

            display_date = f"[ {self.date_text} ]" if self.style_mode == "tech_mono" else self.date_text
            painter.drawText(0, 0, w, date_rect_h, Qt.AlignHCenter | Qt.AlignVCenter, display_date)
            top_y = date_rect_h + 4 + self.date_clock_gap
        else:
            top_y = 0

        # 2. Configure Main Clock Font
        weight = QFont.Normal if self.style_mode == "editorial" else QFont.Bold
        clock_font = QFont(self.font_family, self.font_size, weight)
        painter.setFont(clock_font)
        painter.setPen(self.color)
        fm = painter.fontMetrics()

        # Use tight capHeight when date is hidden so digits reach the very top edge
        baseline_y = top_y + (fm.ascent() if self.show_date else fm.capHeight() + 4)

        if self.style_mode == "liquid_glass":
            time_str = f"{self.hours_text}:{self.mins_text}"
            t_width = fm.horizontalAdvance(time_str)
            path = QPainterPath()
            path.addText(int((w - t_width) / 2), baseline_y, clock_font, time_str)
            self._draw_liquid_glass_path(painter, path)

        elif self.style_mode == "stacked":
            line_step = int(fm.capHeight() * 1.08)
            h_width = fm.horizontalAdvance(self.hours_text)
            m_width = fm.horizontalAdvance(self.mins_text)
            painter.drawText(int((w - h_width) / 2), baseline_y, self.hours_text)
            painter.drawText(int((w - m_width) / 2), baseline_y + line_step, self.mins_text)

        elif self.style_mode == "outline":
            time_str = f"{self.hours_text}:{self.mins_text}"
            t_width = fm.horizontalAdvance(time_str)
            path = QPainterPath()
            path.addText(int((w - t_width) / 2), baseline_y, clock_font, time_str)

            pen = QPen(self.color, max(2.5, self.font_size * 0.022))
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        else:
            sep = "." if self.style_mode == "tech_mono" else ":"
            time_str = f"{self.hours_text}{sep}{self.mins_text}"
            t_width = fm.horizontalAdvance(time_str)
            painter.drawText(int((w - t_width) / 2), baseline_y, time_str)


class DepthWallpaperWindow(QWidget):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Layer 1 (Back): Background image (with 6px overscan margin for parallax)
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)

        # Layer 2 (Middle): Clock widget
        self.clock_widget = StyledClockWidget(self)

        # Layer 3 (Front): Foreground subject cutout
        self.fg_label = QLabel(self)
        self.fg_label.setScaledContents(True)

        self.base_clock_x = 0
        self.base_clock_y = 0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: save_config(self.config))

        geo = QApplication.primaryScreen().geometry()
        self.screen_w, self.screen_h = geo.width(), geo.height()
        self.setGeometry(geo)
        self.bg_label.setGeometry(-6, -6, self.screen_w + 12, self.screen_h + 12)
        self.fg_label.setGeometry(-14, -14, self.screen_w + 28, self.screen_h + 28)

        self.apply_config(self.config)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

        self.parallax_timer = QTimer(self)
        self.parallax_timer.timeout.connect(self.update_parallax)
        self.parallax_timer.start(33)

        bg = self.config.get("bg_path", "")
        fg = self.config.get("fg_path", "")
        if os.path.exists(bg) and os.path.exists(fg):
            self.apply_layers(bg, fg)

    def apply_config(self, cfg: dict):
        self.config = cfg
        self._save_timer.start(400)

        w, h = self.screen_w, self.screen_h
        x_offset = int(w * (cfg["x_offset_percent"] / 100.0))
        y_top = int(h * (cfg["y_percent"] / 100.0))
        font_size = cfg["font_size"]
        font_family = cfg["font_family"]
        color = cfg["color"]
        style_mode = cfg.get("clock_style", "classic")
        date_clock_gap = cfg.get("date_clock_gap", -25)
        show_date = cfg.get("show_date", True)
        self.base_clock_x = x_offset
        self.base_clock_y = y_top

        box_h = int(font_size * 3.6) if style_mode == "stacked" else int(font_size * 1.8)
        self.clock_widget.setGeometry(x_offset, y_top, w, box_h)
        self.clock_widget.update_state(style_mode, font_family, font_size, color, date_clock_gap, show_date)

    def update_clock(self):
        now = datetime.now()
        if self.config.get("use_12h", False):
            hours = now.strftime("%I")
            date_str = now.strftime("%A, %b %d  •  %p").upper()
        else:
            hours = now.strftime("%H")
            date_str = now.strftime("%A, %b %d").upper()
        mins = now.strftime("%M")
        self.clock_widget.set_time_strings(hours, mins, date_str)

    def update_parallax(self):
        # Keep overlay pinned behind the Windows taskbar & desktop icons
        win32gui.SetWindowPos(
            int(self.winId()), win32con.HWND_BOTTOM, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )

        if not self.config.get("enable_parallax", True):
            return

        app_state = get_foreground_window_state(self.screen_w, self.screen_h)
        if app_state == "fullscreen" and self.config.get("pause_fullscreen", True):
            return
        if app_state == "windowed" and self.config.get("pause_windowed", False):
            return

        cursor = QCursor.pos()
        cx, cy = self.screen_w / 2.0, self.screen_h / 2.0
        dx = (cursor.x() - cx) / cx
        dy = (cursor.y() - cy) / cy

        # 3-plane depth parallax: Background (slow) -> Clock (mid) -> Foreground (fast)
        self.bg_label.move(int(-6 - dx * 4), int(-6 - dy * 4))
        self.clock_widget.move(int(self.base_clock_x - dx * 10), int(self.base_clock_y - dy * 10))
        self.fg_label.move(int(-14 - dx * 4), int(-14 - dy * 4))

    def apply_layers(self, bg_path: str, fg_path: str):
        set_native_windows_wallpaper(bg_path)
        self.bg_label.setPixmap(QPixmap(bg_path))
        self.clock_widget.set_background_source(bg_path)
        self.fg_label.setPixmap(QPixmap(fg_path))


class AppController:
    def __init__(self, wallpaper_win: DepthWallpaperWindow):
        self.win = wallpaper_win
        self.dashboard = LivelyDashboard(self.win.config)
        self.dashboard.settings_changed.connect(self.win.apply_config)
        self.dashboard.add_wallpaper_requested.connect(self.pick_image)
        self.dashboard.preset_selected.connect(self.apply_preset)
        self.dashboard.startup_toggled.connect(set_windows_startup)

        # Loading the .ico application branding directly
        icon_path = os.path.join(BASE_DIR, "app.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
        else:
            pix = QPixmap(32, 32)
            pix.fill(QColor("#2563EB"))
            app_icon = QIcon(pix)

        QApplication.setWindowIcon(app_icon)
        self.dashboard.setWindowIcon(app_icon)

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(app_icon)
        self.tray.setToolTip("DepthFlow Wallpaper")
        self.tray.activated.connect(self._on_tray_clicked)

        menu = QMenu()
        open_action = QAction("Open DepthFlow Dashboard", menu)
        open_action.triggered.connect(self.show_dashboard)
        menu.addAction(open_action)

        add_action = QAction("Add New Wallpaper...", menu)
        add_action.triggered.connect(self.pick_image)
        menu.addAction(add_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _on_tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_dashboard()

    def show_dashboard(self):
        self.dashboard.refresh_library()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def pick_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.dashboard, "Select Wallpaper", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if file_path:
            progman = win32gui.FindWindow("Progman", None)
            left, top, right, bottom = win32gui.GetWindowRect(progman)
            phys_w, phys_h = right - left, bottom - top
            model = self.win.config.get("ai_model", "isnet-general-use")

            self.dashboard.set_processing_status("⏳ Separating subject with AI...")
            self.tray.showMessage("DepthFlow", "Separating subject from background...")

            self.worker = SegmentationWorker(file_path, phys_w, phys_h, model)
            self.worker.finished.connect(self.on_processed)
            self.worker.start()

    def on_processed(self, meta: dict):
        self.dashboard.set_processing_status("")
        self.apply_preset(meta)
        self.dashboard.refresh_library()
        self.tray.showMessage("DepthFlow", f"Applied '{meta['name']}'!")

    def apply_preset(self, meta: dict):
        cfg = self.win.config
        cfg["active_preset_id"] = meta["id"]
        cfg["bg_path"] = meta["bg_path"]
        cfg["fg_path"] = meta["fg_path"]
        self.win.apply_config(cfg)
        self.win.apply_layers(meta["bg_path"], meta["fg_path"])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = load_config()
    window = DepthWallpaperWindow(cfg)

    progman = win32gui.FindWindow("Progman", None)
    left, top, right, bottom = win32gui.GetWindowRect(progman)
    attach_overlay_to_desktop(int(window.winId()), right - left, bottom - top)
    window.show()

    controller = AppController(window)

    # Stay silent in the system tray when launched via Windows Startup (--minimized)
    if "--minimized" not in sys.argv:
        controller.show_dashboard()
    else:
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())

    sys.exit(app.exec())