import os
import sys
import gc
import json
import uuid
import ctypes
import threading

# Force rembg to load bundled offline ONNX models next to the .exe / script
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
LOCAL_MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(LOCAL_MODELS_DIR, exist_ok=True)
os.environ["U2NET_HOME"] = LOCAL_MODELS_DIR

from PIL import Image, ImageOps, ImageFilter, ImageStat

_sessions = {}
_cleanup_timer = None


def _trim_windows_ram():
    """Reclaims freed heap pages back to Windows OS."""
    try:
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
    except Exception:
        pass


def get_session(model_name: str = "isnet-general-use"):
    """Lazily imports rembg and caches the ONNX session only while actively needed."""
    global _cleanup_timer
    if _cleanup_timer is not None:
        _cleanup_timer.cancel()

    if model_name not in _sessions:
        from rembg import new_session
        _sessions[model_name] = new_session(model_name)
    return _sessions[model_name]


def schedule_session_unload(delay_sec: float = 15.0):
    """Unloads ONNX Runtime weights from RAM shortly after segmentation completes."""
    global _cleanup_timer
    if _cleanup_timer is not None:
        _cleanup_timer.cancel()

    def _unload():
        _sessions.clear()
        gc.collect()
        _trim_windows_ram()

    _cleanup_timer = threading.Timer(delay_sec, _unload)
    _cleanup_timer.daemon = True
    _cleanup_timer.start()


def suggest_clock_color(img: Image.Image, y_percent: int = 12) -> str:
    gray = img.convert("L")
    w, h = gray.size
    top = int(h * (y_percent / 100.0))
    crop = gray.crop((int(w * 0.25), top, int(w * 0.75), min(h, top + int(h * 0.22))))
    avg_brightness = ImageStat.Stat(crop).mean[0]
    return "#1E293B" if avg_brightness > 175 else "#FFFFFF"


def add_baked_drop_shadow(fg_img: Image.Image) -> Image.Image:
    """Bakes a soft 3D shadow behind the subject once so runtime rendering uses 0% CPU."""
    w, h = fg_img.size
    alpha = fg_img.split()[3]
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=14))
    shadow_alpha = shadow_alpha.point(lambda p: int(p * 0.45))

    shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    black_fill = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    shadow_layer.paste(black_fill, (0, 8), mask=shadow_alpha)

    return Image.alpha_composite(shadow_layer, fg_img)


def process_wallpaper(
    image_path: str,
    screen_width: int,
    screen_height: int,
    model_name: str = "isnet-general-use",
    presets_dir: str = "assets/presets"
) -> dict:
    from rembg import remove

    preset_id = str(uuid.uuid4())[:8]
    preset_folder = os.path.join(presets_dir, preset_id)
    os.makedirs(preset_folder, exist_ok=True)

    bg_path = os.path.join(preset_folder, "bg.png")
    fg_path = os.path.join(preset_folder, "fg.png")
    thumb_path = os.path.join(preset_folder, "thumb.jpg")
    meta_path = os.path.join(preset_folder, "meta.json")

    raw_img = Image.open(image_path).convert("RGBA")
    fitted_img = ImageOps.fit(raw_img, (screen_width, screen_height), Image.Resampling.LANCZOS)
    fitted_img.save(bg_path, "PNG")

    thumb = ImageOps.fit(raw_img.convert("RGB"), (320, 180), Image.Resampling.LANCZOS)
    thumb.save(thumb_path, "JPEG", quality=85)

    # Extract foreground, feather edges, and pre-bake 3D shadow
    fg_img = remove(fitted_img, session=get_session(model_name))
    r, g, b, a = fg_img.split()
    a = a.filter(ImageFilter.GaussianBlur(radius=0.6))
    fg_img = Image.merge("RGBA", (r, g, b, a))
    fg_shadowed = add_baked_drop_shadow(fg_img)
    fg_shadowed.save(fg_path, "PNG")

    # Release large PIL buffers immediately and schedule ONNX model unload
    del raw_img, fitted_img, thumb, fg_img, fg_shadowed, r, g, b, a
    gc.collect()
    schedule_session_unload(15.0)

    meta = {
        "id": preset_id,
        "name": os.path.splitext(os.path.basename(image_path))[0],
        "bg_path": bg_path.replace("\\", "/"),
        "fg_path": fg_path.replace("\\", "/"),
        "thumb_path": thumb_path.replace("\\", "/"),
        "suggested_color": suggest_clock_color(Image.open(bg_path))
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return meta