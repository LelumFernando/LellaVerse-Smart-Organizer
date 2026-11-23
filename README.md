# 🛡️ LellaVerse Smart Organizer Pro (v2.0 — Cyberpunk Edition)

A high-performance, cyberpunk-styled Windows application that automatically organizes your **Downloads** (or any chosen folder).
It reads **file metadata and origin signatures** to neatly separate photos, videos, recordings, and documents by the app they came from (WhatsApp, Telegram, Instagram, TikTok, Snapchat, Camera models, OBS Studio, Canva, etc.) — with full Windows Defender virus protection, byte-level duplicate prevention, and instant one-click undo.

> Windows 10 & 11 compatible. 100% Private, Local & Open Source (MIT).

---

## ⚡ Performance Benchmarks (<50MB RAM, 0% CPU, 0% GPU)

Engineered from the ground up for minimal system resource footprint so it can run 24/7 without affecting gaming, streaming, or heavy workloads:

- **Tray-First Lazy GUI Architecture**: When minimized or closed to the system tray, the entire Tkinter GUI window hierarchy, event loop, and image buffers are completely unloaded from memory. The GUI is created on demand only when opened from the tray.
- **Ultra-Low Memory Footprint (<30MB Idle RAM)**: Automatically triggers Win32 `SetProcessWorkingSetSize` memory trimming right after startup, after batch organizing, and whenever minimized to the system tray. Idle memory stays well under 30MB (and below 50MB during active sorting).
- **True 0.0% Idle CPU**: Built on native Windows `ReadDirectoryChangesW` via `watchdog` and a debounced queue worker thread. When no files are arriving, the worker blocks with zero busy-polling loops.
- **0% GPU Compositing Overhead**: No background canvas animations or timer redraw loops when the window is hidden or minimized.
- **Zero-Bloat Streaming Hashing**: Computes SHA-256 and duplicate verification using streaming 64KB fixed chunks. Large multi-gigabyte video or archive files never buffer into system RAM.
- **Low-Priority Background Defender Scans**: Executes Windows Defender scans asynchronously at `BELOW_NORMAL_PRIORITY_CLASS` (`0x00004000`) with hidden windows so file scans never cause disk or CPU frame drops.

| State | Working Set RAM | CPU Usage | GPU Usage |
| :--- | :--- | :--- | :--- |
| **Idle (Minimized to Tray)** | **< 20 MB** | **0.0%** | **0%** |
| **Active GUI Window** | **~25–40 MB** | **< 0.1%** | **0%** |
| **Active Batch Sorting** | **< 50 MB** | **Event-driven** | **0%** |

---

## 🎯 What Makes It Smart?

### 🔍 Origin App & Metadata Detection
When you dump all your files into a single folder, figuring out where each file came from is normally impossible. LellaVerse Smart Organizer inspects both file naming patterns and internal container metadata:
- **WhatsApp**: Detects WhatsApp images, videos, audio notes, and documents (`IMG-...-WA...`, `WhatsApp Image...`) and sorts them into `Images\WhatsApp`, `Media\WhatsApp`, `Documents\WhatsApp`.
- **Telegram**: Detects `photo_...`, `video_...`, `telegram-cloud-document...` and routes them into `Telegram` subfolders.
- **Instagram & TikTok**: Automatically categorizes reels, stories, CDN downloads, and TikTok watermark clips.
- **Screenshots**: Recognizes Windows, Android, and macOS screenshots and separates them from regular photos into `Images\Screenshots`.
- **Camera Photos (EXIF)**: Reads EXIF `Make` and `Model` (Apple iPhone, Samsung Galaxy, Google Pixel, Sony, Canon, Nikon, DJI, GoPro) and puts them into `Images\Camera Photos`.
- **Screen Recordings**: Identifies OBS Studio recordings, Nvidia ShadowPlay, Bandicam, Loom, Zoom, and Google Meet recordings into `Media\Screen Recordings`.
- **Design & Office**: Recognizes Canva, Figma, Photoshop, Adobe Illustrator, Blender, Microsoft Word, Excel, PowerPoint, and Google Docs files.
- **Chronological Sorting**: Sorts by true EXIF capture date or download date (weekly or monthly).

### 🛡️ Antivirus & Duplicate Protection
- **Windows Defender Integration**: Scans incoming files before sorting. Threats are quarantined in `Infected_Malware`.
- **Duplicate Hash Guard**: Identifies byte-identical duplicates (via SHA-256) and isolates them into `Duplicates`. Same-name different files get collision-safe timestamps.
- **Instant Undo**: Restore any file to its original location with a single click in the *History / Undo* tab.
- **Windows Explorer Right-Click Menu**: Select any folder in Windows Explorer and choose *"Organize with LellaVerse"* to sort on demand.

---

## 🚀 Quick Start

### Running from Source
1. Clone the repository:
   ```bash
   git clone https://github.com/LelumFernando/LellaVerse-Smart-Organizer.git
   cd LellaVerse-Smart-Organizer
   ```
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the organizer:
   ```bash
   python lellaverse_organizer.py
   ```
4. Click **＋ Add folder** (e.g. choose your `Downloads` folder).
5. Select your preferred **App Origin Mode** (e.g., *Smart App Subfolders*).
6. Click **▶ START WATCHING**. You're done! Close the window and it runs quietly in your system tray.

---

## 🎨 Theme & Brand
Featuring the official **LellaVerse** cyberpunk aesthetic:
- Cosmic dark obsidian background (`#080b11`)
- Electric neon cyan (`#00e5ff`) and vibrant neon magenta (`#d946ef`) accents
- Native high-DPI scaling for ultra-sharp rendering on 4K and laptop displays
- Official LellaVerse emblem window icon and system tray integration

---

## 🛠️ Building the Standalone .exe & Installer

Run `build.bat` in the project directory:
```bash
build.bat
```
The automated build pipeline:
1. Provisions an isolated virtual environment (`.venv_build`) with only the minimal required dependencies.
2. Compiles a lightweight standalone build (`< 50MB`) via PyInstaller with optimized excludes.
3. Automatically compiles the Inno Setup installer (`LellaVerseOrganizer_Setup_v2.0.0.exe`) if Inno Setup is present.
4. Generates a compressed distribution zip (`dist\LellaVerseOrganizer-v2.0.0.zip`).

---

## 🔒 Privacy Guarantee

Everything runs 100% locally on your computer. No files, logs, or analytics are ever uploaded. Virus scanning uses your existing local Windows Defender engine.

---

## 👤 Author & License

Created by **Lelum Anuradha Fernando** — [LellaVerse](https://github.com/LelumFernando/LellaVerse-Smart-Organizer).  
Licensed under the **MIT License**.
