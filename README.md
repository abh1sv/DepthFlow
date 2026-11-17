# ✦ DepthFlow

A lightweight, AI-powered live depth wallpaper engine for Windows 11. **DepthFlow** automatically separates foreground subjects from any wallpaper, layers a customizable clock behind the subject, and applies smooth 3-plane 3D mouse parallax—all while idling under ~100 MB of RAM.

## Features
- **AI Subject Segmentation:** Offline foreground cutout powered by `rembg` (`isnet-general-use`) with baked 3D drop shadows and automatic session unloading.
- **6 Clock Styles:** Liquid Glass (frosted refraction), Classic Horizontal, Stacked Vertical, Editorial Serif, Tech Mono, and Hollow Outline.
- **3-Layer 3D Mouse Parallax:** Independent depth movement across Background, Clock, and Foreground layers with smart pause toggles for fullscreen or windowed apps.
- **Native Windows Integration:** Pinned behind desktop icons and the taskbar with system tray controls and silent `--minimized` startup support.

## Quick Start (Windows Users)
1. Download the latest `DepthFlow-Windows.zip` from the **Releases** tab on the right.
2. Extract the folder anywhere on your PC and run `DepthFlow.exe`.

## Run from Source
```bash
git clone https://github.com/abh1sv/DepthFlow.git
cd DepthFlow
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py
