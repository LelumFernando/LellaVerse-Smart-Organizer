"""
LellaVerse Smart Organizer Pro  (v3.6 - Cyberpunk Edition)

A high-performance Windows organizer that automatically sorts downloads and media folders.
Features:
- Smart Metadata & App Origin Detection (WhatsApp, Telegram, Instagram, TikTok, Snapchat, Facebook, Screenshots, Camera Makes, Screen Recorders, Canva, Photoshop, Office)
- Cyberpunk / Gamer Neon Dark Theme matching the official LellaVerse brand
- Preview Sort (Dry run simulation before moving files)
- Windows Explorer Right-Click Menu Integration ("Organize with LellaVerse")
- Storage & Cleanup Statistics (MB/GB sorted and duplicate space saved)
- Windows Defender Virus Scanning & Quarantine
- Content-hash Duplicate Detection
- Chronological Sorting by EXIF capture date or arrival date (Weekly / Monthly)
- Complete Undo History
- System Tray Minimization & Startup Support

Install:  pip install -r requirements.txt
Run:      python lellaverse_organizer.py
"""

import os
import sys

# ----------------------------------------------------------------------------
# Tcl / Tk Library Path Auto-Resolver (Must run BEFORE import tkinter)
# Handles Windows OneDrive GetShortPathName path-truncation bug
# ----------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    local_app_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LellaVerseOrganizer", "tcl_runtime")
    tcl_dest = os.path.join(local_app_dir, "tcl8.6")
    tk_dest = os.path.join(local_app_dir, "tk8.6")

    search_dirs = [
        getattr(sys, "_MEIPASS", exe_dir),
        exe_dir,
        os.path.join(exe_dir, "_internal"),
    ]
    tcl_src, tk_src = None, None
    for b in search_dirs:
        for tcl_sub in ["_tcl_data", "tcl", "tcl8.6"]:
            cand = os.path.join(b, tcl_sub)
            if os.path.exists(os.path.join(cand, "init.tcl")):
                tcl_src = cand
                break
        for tk_sub in ["_tk_data", "tk", "tk8.6"]:
            cand = os.path.join(b, tk_sub)
            if os.path.exists(os.path.join(cand, "tk.tcl")):
                tk_src = cand
                break
        if tcl_src and tk_src:
            break

    # If the app is run from a OneDrive folder or path with spaces/reparse points,
    # Windows Kernel32 GetShortPathNameW bug corrupts the path inside Tcl's C runtime.
    # Staging to %LOCALAPPDATA% ensures 100% crash-free launch anywhere.
    needs_staging = "onedrive" in exe_dir.lower() or not os.path.exists(os.path.join(tcl_dest, "init.tcl"))

    if needs_staging and tcl_src and tk_src:
        try:
            import shutil
            os.makedirs(local_app_dir, exist_ok=True)
            if not os.path.exists(os.path.join(tcl_dest, "init.tcl")):
                shutil.copytree(tcl_src, tcl_dest, dirs_exist_ok=True)
            if not os.path.exists(os.path.join(tk_dest, "tk.tcl")):
                shutil.copytree(tk_src, tk_dest, dirs_exist_ok=True)
            tcl8_src = os.path.join(os.path.dirname(tcl_src), "tcl8")
            if os.path.exists(tcl8_src) and not os.path.exists(os.path.join(local_app_dir, "tcl8")):
                shutil.copytree(tcl8_src, os.path.join(local_app_dir, "tcl8"), dirs_exist_ok=True)
            os.environ["TCL_LIBRARY"] = tcl_dest
            os.environ["TK_LIBRARY"] = tk_dest
        except Exception:
            os.environ["TCL_LIBRARY"] = tcl_src
            os.environ["TK_LIBRARY"] = tk_src
    elif tcl_src and tk_src:
        os.environ["TCL_LIBRARY"] = tcl_src
        os.environ["TK_LIBRARY"] = tk_src

import calendar
import copy
import filecmp
import hashlib
import json
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from glob import glob
from tkinter import filedialog, messagebox, ttk

# PIL for modern image handling, logo rendering & EXIF parsing
try:
    from PIL import Image, ImageTk, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Watchdog for real-time filesystem monitoring
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Metadata & Origin detector
try:
    import metadata_detector as md
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import metadata_detector as md


# ----------------------------------------------------------------------------
# High-DPI Awareness for Windows
# ----------------------------------------------------------------------------
IS_WIN = sys.platform == "win32"
if IS_WIN:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Constants & Paths
# ----------------------------------------------------------------------------
APP_NAME = "LellaVerse Smart Organizer"
APP_VERSION = "2.0.0"
AUTHOR = "Lelum Anuradha Fernando"
GITHUB_URL = "https://github.com/LelumFernando/LellaVerse-Smart-Organizer"
HOME = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, "LellaVerse_Organizer_config.json")
HISTORY_FILE = os.path.join(HOME, "LellaVerse_Organizer_history.json")
LOCK_PORT = 48653
STARTUP_DELAY_MS = 20000
HISTORY_LIMIT = 500

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

SPECIAL = ["Folders", "Infected_Malware", "Others", "Duplicates"]
KNOWN_APP_FOLDERS = [
    "WhatsApp", "Telegram", "Instagram", "TikTok", "Snapchat",
    "Facebook & Messenger", "Twitter", "Screenshots", "Screen Recordings",
    "Camera Photos", "Canva", "Photoshop", "Illustrator", "Blender",
    "Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint", "Google Docs"
]
NO_DATE_FOLDERS = {"folders", "infected_malware", "duplicates"}
TEMP_EXT = (".crdownload", ".part", ".tmp", ".download", ".partial", ".opdownload")
IGNORED_NAMES = {"desktop.ini", "thumbs.db"}
INVALID_CHARS = set('\\/:*?"<>|')
EXT_RE = re.compile(r"^\.[a-z0-9_+\-]{1,15}$")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DATE_MODES = ["off", "week", "month"]
DATE_LABELS = [
    "Off  -  files go straight into category / app folder",
    "Week by week  (e.g.  2026-10-Oct-Week3)",
    "Month by month  (e.g.  2026-10-Oct)",
]
DATE_SHORT = {"off": "Off", "week": "Weekly", "month": "Monthly"}

ORGANIZE_MODES = ["smart_app", "app_first", "direct_app", "category_only"]
ORGANIZE_LABELS = [
    "Smart App Subfolders  (e.g.  Images \\ WhatsApp,  Images \\ Screenshots,  Media \\ TikTok)",
    "App First  (e.g.  WhatsApp \\ Images,  WhatsApp \\ Videos,  Screenshots)",
    "Direct App Folders  (e.g.  WhatsApp,  Telegram,  Screenshots,  Camera Photos)",
    "Category Only  (Flat:  Images,  Documents,  Media,  Software ...)",
]
ORGANIZE_SHORT = {
    "smart_app": "Smart App Subfolders",
    "app_first": "App First",
    "direct_app": "Direct App Folders",
    "category_only": "Category Only",
}

KIND_LABELS = {"move": "Sorted", "duplicate": "Duplicate", "virus": "Virus Quarantined"}

DEFAULT_CATEGORIES = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg", ".ico", ".raw", ".dng"],
    "Software": [".exe", ".msi", ".bat", ".cmd", ".iso"],
    "Compressed": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx", ".csv", ".rtf", ".epub"],
    "Media": [".mp4", ".mp3", ".wav", ".mkv", ".mov", ".avi", ".flac", ".m4a", ".opus", ".webm"],
}

DEFAULT_SETTINGS = {
    "sort_existing": True,
    "scan_virus": True,
    "scan_existing": False,
    "check_duplicates": True,
    "detect_metadata": True,
    "detect_apps": True,
    "separate_screenshots": True,
    "separate_recordings": True,
    "auto_start_watching": False,
    "close_to_tray": True,
    "start_with_windows": False,
    "explorer_context_menu": False,
}

CONFIG_LOAD_ERROR = None


# ----------------------------------------------------------------------------
# Neon Cyberpunk Color Theme (Exact Match to LellaVerse Logo)
# ----------------------------------------------------------------------------
BG = "#080b11"             # Deep space / pitch cosmic black
CARD = "#111624"           # Dark card panel surface
CARD2 = "#161d2d"          # Secondary panel / treeview / input surface
CARD_BORDER = "#1f293d"    # Card subtle outline
BORDER_ACTIVE = "#00e5ff"  # Glowing border on focus
ACCENT_CYAN = "#00e5ff"    # Electric neon cyan (headphones & circuit color)
ACCENT_CYAN_HOVER = "#33eeff"
ACCENT_PURPLE = "#d946ef"  # Vibrant neon magenta/purple (planet ring & arch color)
ACCENT_PURPLE_HOVER = "#e879f9"
TEXT = "#f8fafc"           # Crisp bright slate/white
MUTED = "#94a3b8"          # Secondary label slate
DARK_MUTED = "#64748b"     # Deeper muted text
RED = "#ff3366"            # Neon coral/red (danger / virus / error)
RED_BG = "#290a12"         # Red pill background
ORANGE = "#fb923c"         # Neon amber / warning
GREEN = "#00f59b"          # Neon emerald (running / success)
GREEN_BG = "#002919"       # Green pill background
BTN = "#1a2234"            # Sleek dark button
BTN_HOVER = "#25304a"      # Button hover state
BTN_TEXT = "#e2e8f0"

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_S = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def norm(p):
    return os.path.normcase(os.path.abspath(p))


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def new_folder_rule(path, categories=None, date_mode="off", organize_mode="smart_app"):
    return {
        "path": path,
        "categories": copy.deepcopy(categories if categories is not None else DEFAULT_CATEGORIES),
        "date_mode": date_mode if date_mode in DATE_MODES else "off",
        "organize_mode": organize_mode if organize_mode in ORGANIZE_MODES else "smart_app",
    }


def valid_categories(c):
    return (isinstance(c, dict) and c
            and all(isinstance(k, str) and isinstance(v, list) and all(isinstance(e, str) for e in v)
                    for k, v in c.items()))


# ----------------------------------------------------------------------------
# Config Management
# ----------------------------------------------------------------------------
def default_config():
    c = dict(DEFAULT_SETTINGS)
    c["version"] = 4
    c["folders"] = [new_folder_rule(os.path.join(HOME, "Downloads"))]
    return c


def load_config():
    global CONFIG_LOAD_ERROR
    c = default_config()
    if not os.path.exists(CONFIG_FILE):
        return c
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_SETTINGS.items():
            if k in data and isinstance(data[k], type(v)):
                c[k] = data[k]
        if isinstance(data.get("folders"), list):
            folders = []
            for f in data["folders"]:
                if isinstance(f, dict) and isinstance(f.get("path"), str):
                    cats = f.get("categories") if valid_categories(f.get("categories")) else DEFAULT_CATEGORIES
                    date_mode = f.get("date_mode", "off")
                    org_mode = f.get("organize_mode", "smart_app")
                    folders.append(new_folder_rule(f["path"], cats, date_mode, org_mode))
            c["folders"] = folders
        else:
            paths = data.get("watch_paths")
            if not isinstance(paths, list) and isinstance(data.get("watch_path"), str):
                paths = [data["watch_path"]]
            if isinstance(paths, list) and paths:
                cats = data.get("categories") if valid_categories(data.get("categories")) else DEFAULT_CATEGORIES
                c["folders"] = [new_folder_rule(p, cats) for p in paths if isinstance(p, str)]
    except Exception as e:
        CONFIG_LOAD_ERROR = f"Could not read the settings file, using defaults. ({e})"
    return c


def save_config():
    try:
        write_json(CONFIG_FILE, cfg)
        return True, ""
    except Exception as e:
        return False, str(e)


cfg = load_config()


# ----------------------------------------------------------------------------
# UI Queue for Background -> Main Thread Communication
# ----------------------------------------------------------------------------
ui_queue = queue.Queue()


_stats = {"moved": 0, "dupes": 0, "infected": 0, "errors": 0, "bytes_moved": 0, "bytes_dupes": 0}
_observer = None
_watches = {}
_is_watching = False
_tray = None
_active_app = None
_gui_cmd_queue = queue.Queue()
_main_running = True


def log(text, level="info"):
    ui_queue.put(("log", text, level))


def stat(key, amount=1):
    _stats[key] = _stats.get(key, 0) + amount
    ui_queue.put(("stat", key, amount))


# ----------------------------------------------------------------------------
# History & Undo Engine
# ----------------------------------------------------------------------------
_history = []
_pinned = set()
_hist_lock = threading.Lock()


def save_history():
    try:
        write_json(HISTORY_FILE, {"moves": _history, "pinned": sorted(_pinned)})
    except Exception:
        pass


def load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            need = {"id", "time", "src", "dst", "kind"}
            moves = [m for m in data.get("moves", []) if isinstance(m, dict) and need <= set(m)]
            _history[:] = moves[-HISTORY_LIMIT:]
            _pinned.update(p for p in data.get("pinned", []) if isinstance(p, str) and os.path.exists(p))
    except Exception:
        pass


def record_move(src, dst, kind, origin=None):
    with _hist_lock:
        _history.append({
            "id": time.time_ns(),
            "time": datetime.now().isoformat(timespec="seconds"),
            "src": src,
            "dst": dst,
            "kind": kind,
            "origin": origin or "General"
        })
        del _history[:-HISTORY_LIMIT]
        save_history()
    ui_queue.put(("history",))


def is_pinned(path):
    return norm(path) in _pinned


def forget_pins():
    with _hist_lock:
        _pinned.clear()
        save_history()


def unique_numbered(dest_dir, filename):
    base, ext = os.path.splitext(filename)
    dest = os.path.join(dest_dir, filename)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, f"{base} ({n}){ext}")
        n += 1
    return dest


def undo_move(entry_id):
    """Restores moved file and gracefully prunes empty parent folders."""
    with _hist_lock:
        entry = next((e for e in _history if e["id"] == entry_id), None)
    if entry is None:
        return False, "That move is not in the history any more."
    src, dst = entry["src"], entry["dst"]
    name = os.path.basename(src)
    if not os.path.exists(dst):
        return False, f"'{name}' is no longer at:\n{dst}\n\nIt was moved or deleted."
    target_dir = os.path.dirname(src)
    if not os.path.isdir(target_dir):
        return False, f"The original folder no longer exists:\n{target_dir}"
    target = src if not os.path.exists(src) else unique_numbered(target_dir, name)
    with _hist_lock:
        _pinned.add(norm(target))
    try:
        shutil.move(dst, target)
    except Exception as e:
        with _hist_lock:
            _pinned.discard(norm(target))
        return False, f"Could not undo '{name}': {e}"

    with _hist_lock:
        _history[:] = [e for e in _history if e["id"] != entry_id]
        save_history()

    # Recursively clean up empty subfolders up to the root watch folder
    curr_dir = os.path.dirname(dst)
    try:
        while norm(curr_dir) != norm(target_dir) and os.path.isdir(curr_dir):
            if not os.listdir(curr_dir):
                os.rmdir(curr_dir)
                curr_dir = os.path.dirname(curr_dir)
            else:
                break
    except OSError:
        pass

    ui_queue.put(("history",))
    return True, f"Restored '{name}' to {target_dir}"


load_history()


# ----------------------------------------------------------------------------
# Windows Defender Integration
# ----------------------------------------------------------------------------
def find_defender():
    candidates = [
        r"C:\Program Files\Windows Defender\MpCmdRun.exe",
        r"C:\Program Files (x86)\Windows Defender\MpCmdRun.exe",
    ]
    candidates += sorted(glob(r"C:\ProgramData\Microsoft\Windows Defender\Platform\*\MpCmdRun.exe"), reverse=True)
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


DEFENDER_PATH = find_defender()
_warned_defender = False
_scan_sem = threading.Semaphore(1)


def scan_for_malware(file_path):
    global _warned_defender
    if not DEFENDER_PATH:
        if not _warned_defender:
            _warned_defender = True
            log("Windows Defender was not found - virus scan is skipped.", "warning")
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (0x00004000 if IS_WIN else 0)
    try:
        with _scan_sem:
            proc = subprocess.Popen(
                [DEFENDER_PATH, "-Scan", "-ScanType", "3", "-File", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags
            )
            stdout, stderr = proc.communicate(timeout=180)
            return proc.returncode == 2
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        log(f"Virus scan timed out: {os.path.basename(file_path)}", "warning")
    except Exception as e:
        log(f"Virus scan failed for {os.path.basename(file_path)}: {e}", "warning")
    return False


# ----------------------------------------------------------------------------
# Core Organizer Engine
# ----------------------------------------------------------------------------
_lock = threading.Lock()
_busy = set()
_organizing = threading.Event()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="organizer")
SELF_PATHS = {norm(sys.argv[0]), norm(sys.executable)}


def rule_for(path):
    parent = norm(os.path.dirname(os.path.abspath(path)))
    for r in cfg["folders"]:
        if norm(r["path"]) == parent:
            return r
    return None


def managed_names(rule):
    """All names protected from being moved into 'Folders'."""
    cats = list(rule["categories"].keys())
    return {n.lower() for n in cats + SPECIAL + KNOWN_APP_FOLDERS}


def is_ignored(path):
    name = os.path.basename(path).lower()
    return name in IGNORED_NAMES or name.endswith(TEMP_EXT) or norm(path) in SELF_PATHS


def check_watch_path(p):
    if not p or not os.path.isdir(p):
        return False, f"This folder does not exist:\n{p}\n\nPlease choose another folder."
    if os.path.dirname(os.path.abspath(p)) == os.path.abspath(p):
        return False, "Please do not choose a whole drive (like C:\\). Choose a normal folder."
    if not os.access(p, os.W_OK):
        return False, f"No permission to change files in:\n{p}\n\nChoose another folder or run as administrator."
    return True, ""


def folder_conflict(path):
    b = norm(path)
    for r in cfg["folders"]:
        a = norm(r["path"])
        if a == b:
            return f"This folder is already in the list:\n{path}"
        if b.startswith(a + os.sep) or a.startswith(b + os.sep):
            return (f"This folder is inside (or contains) another folder in the list:\n{r['path']}\n\n"
                    "Choose a folder that is separate from the others.")
    return None


def create_category_folders(rule):
    created = 0
    for name in list(rule["categories"].keys()) + SPECIAL:
        p = os.path.join(rule["path"], name)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            created += 1
    return created


def find_category(rule, ext):
    for folder, exts in rule["categories"].items():
        if ext in exts:
            return folder
    return None


def date_subfolder(dt, mode):
    month = f"{dt.year}-{dt.month:02d}-{MONTHS[dt.month - 1]}"
    if mode == "month":
        return month
    for i, row in enumerate(calendar.monthcalendar(dt.year, dt.month), 1):
        if dt.day in row:
            return f"{month}-Week{i}"
    return month


def quick_hash(path):
    h = hashlib.sha256()
    try:
        size = os.path.getsize(path)
        h.update(str(size).encode())
        with open(path, "rb") as f:
            # Read first 64KB
            chunk = f.read(65536)
            if chunk:
                h.update(chunk)
            # Read last 64KB for large files
            if size > 131072:
                f.seek(-65536, os.SEEK_END)
                chunk = f.read(65536)
                if chunk:
                    h.update(chunk)
    except OSError:
        pass
    return h.hexdigest()


def find_duplicate(src, search_dir):
    """Fast two-stage duplicate finder (size + quick_hash + full cmp)."""
    try:
        size = os.path.getsize(src)
    except OSError:
        return None
    if size == 0 or not os.path.isdir(search_dir):
        return None
    me = norm(src)
    src_hash = None

    for root, _dirs, files in os.walk(search_dir):
        for f in files:
            p = os.path.join(root, f)
            try:
                if norm(p) != me and os.path.getsize(p) == size:
                    if src_hash is None:
                        src_hash = quick_hash(src)
                    if quick_hash(p) == src_hash:
                        if filecmp.cmp(src, p, shallow=False):
                            return p
            except OSError:
                continue
    return None


def clash_path(src, dest_dir, name, is_dir=False):
    base, ext = os.path.splitext(name)
    tag = datetime.now().strftime("%Y%m%d")
    if not is_dir:
        tag += "_" + quick_hash(src)[:6]
    cand = os.path.join(dest_dir, f"{base}_{tag}{ext}")
    n = 1
    while os.path.exists(cand):
        cand = os.path.join(dest_dir, f"{base}_{tag} ({n}){ext}")
        n += 1
    return cand


def wait_until_ready(path, timeout=600):
    try:
        if time.time() - os.path.getmtime(path) > 10:
            return True
    except OSError:
        return False
    last_size = -1
    start = time.time()
    while time.time() - start < timeout:
        if not os.path.exists(path):
            return False
        try:
            size = os.path.getsize(path)
            with open(path, "rb"):
                pass
            if size == last_size:
                return True
            last_size = size
        except OSError:
            pass
        time.sleep(1.5)
    return False


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def wait_dir_ready(path, timeout=120):
    try:
        if time.time() - os.path.getmtime(path) > 10:
            return True
    except OSError:
        return False
    last = -1
    start = time.time()
    while time.time() - start < timeout:
        if not os.path.exists(path):
            return False
        size = dir_size(path)
        if size == last:
            return True
        last = size
        time.sleep(1.5)
    return False


def determine_destination(path, rule):
    """Calculates destination folder & subfolder without moving the file."""
    name = os.path.basename(path)
    is_dir = os.path.isdir(path)
    if is_dir:
        return "Folders", None, "Subfolder"

    origin = None
    if cfg["detect_apps"] or cfg["detect_metadata"]:
        origin = md.detect_file_origin(path)

    ext = os.path.splitext(name)[1].lower()
    base_cat = find_category(rule, ext) or "Others"

    file_dt = md.get_smart_file_date(path, origin)
    date_sub = None
    if rule.get("date_mode", "off") != "off" and base_cat.lower() not in NO_DATE_FOLDERS:
        date_sub = date_subfolder(file_dt, rule["date_mode"])

    org_mode = rule.get("organize_mode", "smart_app")
    folder = base_cat
    sub = date_sub
    origin_label = origin.app_name if origin else "General"

    if origin and org_mode != "category_only":
        sub_name = origin.subfolder

        if org_mode == "smart_app":
            folder = base_cat
            sub = os.path.join(sub_name, date_sub) if date_sub else sub_name
        elif org_mode == "app_first":
            folder = sub_name
            sub = os.path.join(base_cat, date_sub) if date_sub else base_cat
        elif org_mode == "direct_app":
            folder = sub_name
            sub = date_sub

    return folder, sub, origin_label


def move_item(src, rule, folder, sub=None, kind="move", check_dupes=False, origin_tag=None):
    name = os.path.basename(src)
    watch = rule["path"]
    is_dir = os.path.isdir(src)
    try:
        size = os.path.getsize(src) if not is_dir else dir_size(src)
        if check_dupes and cfg["check_duplicates"] and not is_dir:
            twin = find_duplicate(src, os.path.join(watch, folder))
            if twin:
                log(f"Duplicate: '{name}' matches '{os.path.relpath(twin, watch)}'", "warning")
                stat("dupes")
                stat("bytes_dupes", size)
                folder, sub, kind = "Duplicates", None, "duplicate"

        dest_dir = os.path.join(watch, folder, sub) if sub else os.path.join(watch, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            dest = clash_path(src, dest_dir, name, is_dir)
            log(f"Same name, different file: '{name}' saved as '{os.path.basename(dest)}'", "info")

        shutil.move(src, dest)
        record_move(src, dest, kind, origin=origin_tag)
        stat("moved")
        stat("bytes_moved", size)

        sub_display = f"{folder}\\{sub}" if sub else folder
        origin_text = f"  [{origin_tag}]" if origin_tag else ""
        log(f"{name}  →  {sub_display}{origin_text}", "success")
        return True
    except PermissionError:
        stat("errors")
        log(f"Cannot move '{name}' - access is denied or file is open in another app.", "error")
    except Exception as e:
        stat("errors")
        log(f"Cannot move '{name}': {e}", "error")
    return False


def process_item(path, scan=True):
    path = os.path.abspath(path)
    rule = rule_for(path)
    if rule is None:
        return
    name = os.path.basename(path)
    if name.lower() in managed_names(rule) or is_ignored(path) or is_pinned(path):
        return

    with _lock:
        if path in _busy:
            return
        _busy.add(path)
    try:
        if not os.path.exists(path):
            return

        if os.path.isdir(path):
            if not wait_dir_ready(path):
                log(f"Skipped folder (still changing): {name}", "warning")
                return
            move_item(path, rule, "Folders", origin_tag="Subfolder")
            return

        if not wait_until_ready(path):
            log(f"Skipped (still downloading / in use): {name}", "warning")
            return

        if scan and cfg["scan_virus"] and scan_for_malware(path):
            stat("infected")
            log(f"VIRUS DETECTED: {name} → Infected_Malware", "error")
            ui_queue.put(("notify", "Virus detected", f"{name} was moved to Infected_Malware"))
            move_item(path, rule, "Infected_Malware", kind="virus", origin_tag="Malware")
            return

        folder, sub, origin_label = determine_destination(path, rule)
        move_item(path, rule, folder, sub, check_dupes=True, origin_tag=origin_label)

    except Exception as e:
        stat("errors")
        log(f"Unexpected error with '{name}': {e}", "error")
    finally:
        with _lock:
            _busy.discard(path)


def organize_existing():
    if _organizing.is_set():
        log("Sorting is already running...", "warning")
        return
    _organizing.set()

    def run():
        try:
            todo = []
            for rule in list(cfg["folders"]):
                try:
                    items = sorted(os.listdir(rule["path"]))
                except Exception as e:
                    ui_queue.put(("popup", "Cannot read folder", f"{rule['path']}\n\n{e}"))
                    continue
                names = managed_names(rule)
                todo += [os.path.join(rule["path"], i) for i in items
                         if i.lower() not in names and not is_ignored(os.path.join(rule["path"], i))]
            total = len(todo)
            if total == 0:
                log("Nothing to sort - the watched folder(s) are already organized.", "info")
            ui_queue.put(("progress", 0, total))
            for i, p in enumerate(todo, 1):
                process_item(p, scan=cfg["scan_existing"])
                ui_queue.put(("progress", i, total))
            if total:
                log(f"Successfully organized {total} item(s).", "success")
        finally:
            _organizing.clear()
            ui_queue.put(("done",))
            trim_working_set()

    threading.Thread(target=run, daemon=True).start()


class OrganizerHandler(FileSystemEventHandler):
    """Debounced filesystem event handler.

    Events are accumulated in a queue.  A background worker waits for 1.5 s of
    silence (no further events on the same path) before dispatching each file to
    ``process_item``, avoiding redundant work for rapid-fire events.
    """

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._pending = {}          # path -> last_event_time
        self._pending_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # -- public ----------------------------------------------------------
    def stop(self):
        """Signal the debounce worker to exit."""
        self._stop_event.set()

    # -- watchdog callbacks ------------------------------------------------
    def on_created(self, event):
        self._enqueue(event.src_path)

    def on_moved(self, event):
        self._enqueue(event.dest_path)

    # -- internals ---------------------------------------------------------
    def _enqueue(self, path):
        now = time.monotonic()
        with self._pending_lock:
            self._pending[path] = now
        self._queue.put(path)

    def _run(self):
        debounce_seconds = 1.5
        while not self._stop_event.is_set():
            try:
                # Block until an event arrives or timeout (keeps CPU at 0 %)
                self._queue.get(timeout=2.0)
            except queue.Empty:
                continue
            # Drain any burst that arrived at the same instant
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            # Wait for silence, then dispatch mature paths
            time.sleep(debounce_seconds)
            with self._pending_lock:
                now = time.monotonic()
                ready = [p for p, t in self._pending.items()
                         if now - t >= debounce_seconds]
                for p in ready:
                    del self._pending[p]
            for p in ready:
                try:
                    _executor.submit(process_item, p, True)
                except RuntimeError:
                    pass


# ----------------------------------------------------------------------------
# Windows Autostart, Priority, Single Instance, Explorer Menu, Tray
# ----------------------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}" --minimized'


def set_autostart(enable):
    if not IS_WIN:
        raise RuntimeError("Start with Windows only works on Windows.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def set_explorer_context_menu(enable):
    """Registers / unregisters 'Organize with LellaVerse' in Windows Explorer right click menu."""
    if not IS_WIN:
        return
    import winreg
    keys = [
        r"Software\Classes\Directory\shell\LellaVerseOrganizer",
        r"Software\Classes\Directory\Background\shell\LellaVerseOrganizer"
    ]
    if enable:
        exe = sys.executable
        if getattr(sys, "frozen", False):
            cmd = f'"{exe}" --sort "%V"'
        else:
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            runner = pyw if os.path.exists(pyw) else exe
            cmd = f'"{runner}" "{os.path.abspath(sys.argv[0])}" --sort "%V"'

        ico_path = os.path.join(ASSETS_DIR, "app_icon.ico")
        for k_path in keys:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, k_path) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Organize with LellaVerse")
                if os.path.exists(ico_path):
                    winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, ico_path)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, k_path + r"\command") as k_cmd:
                winreg.SetValueEx(k_cmd, "", 0, winreg.REG_SZ, cmd)
    else:
        for k_path in keys:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k_path + r"\command")
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k_path)
            except FileNotFoundError:
                pass


def lower_priority():
    if IS_WIN:
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
        except Exception:
            pass


def trim_working_set():
    """Release unused physical RAM back to the OS (Windows only)."""
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            k.GetCurrentProcess.restype = wintypes.HANDLE
            k.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
            k.SetProcessWorkingSetSize.restype = wintypes.BOOL
            h = k.GetCurrentProcess()
            k.SetProcessWorkingSetSize(h, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
        except Exception:
            pass


_instance_sock = None


def acquire_single_instance():
    global _instance_sock
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        _instance_sock = s
        return True
    except OSError:
        return False


class Tray:
    """System tray icon with official LellaVerse gamer logo."""

    def __init__(self):
        self.icon = None

    @property
    def running(self):
        return self.icon is not None

    def start(self):
        try:
            import pystray
        except Exception:
            return False

        try:
            tray_path = os.path.join(ASSETS_DIR, "tray_icon.png")
            if os.path.exists(tray_path) and PIL_AVAILABLE:
                img = Image.open(tray_path)
            else:
                img = Image.new("RGBA", (64, 64), (8, 11, 17, 255))
                d = ImageDraw.Draw(img)
                d.ellipse((6, 6, 58, 58), outline=(0, 229, 255, 255), width=3)
                d.text((20, 22), "LV", fill=(217, 70, 239, 255))

            def cmd(name):
                return lambda icon, item: _gui_cmd_queue.put((name, None))

            menu = pystray.Menu(
                pystray.MenuItem("Open LellaVerse", cmd("open"), default=True),
                pystray.MenuItem("Sort Now", cmd("sort")),
                pystray.MenuItem("Pause / Resume Watching", cmd("toggle")),
                pystray.MenuItem("Quit", cmd("quit")),
            )
            self.icon = pystray.Icon("LellaVerseOrganizer", img, APP_NAME, menu)
            self.icon.run_detached()
            return True
        except Exception:
            self.icon = None
            return False

    def set_title(self, text):
        try:
            if self.icon:
                self.icon.title = text
        except Exception:
            pass

    def notify(self, title, msg):
        try:
            if self.icon:
                self.icon.notify(msg, title)
        except Exception:
            pass

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.icon = None


# ----------------------------------------------------------------------------
# Category Validation
# ----------------------------------------------------------------------------
def validate_category(name, ext_text, cats, editing=None):
    name = name.strip()
    if not name:
        return False, "Please enter a folder name."
    if len(name) > 60:
        return False, "Folder name is too long (max 60 characters)."
    if any(c in INVALID_CHARS for c in name):
        return False, 'A folder name cannot contain  \\ / : * ? " < > |'
    if name.endswith("."):
        return False, "A folder name cannot end with a dot."
    if name.lower() in {s.lower() for s in SPECIAL}:
        return False, f'"{name}" is reserved by the organizer.'
    for existing in cats:
        if existing.lower() == name.lower() and existing != editing:
            return False, f'A folder called "{existing}" already exists.'

    raw = [e.strip().lower() for e in re.split(r"[,\s;]+", ext_text) if e.strip()]
    if not raw:
        return False, "Please enter at least one file extension (e.g. .py, .heic)."
    exts = []
    for e in raw:
        e = e.lstrip("*")
        if not e.startswith("."):
            e = "." + e
        if not EXT_RE.match(e):
            return False, f'"{e}" is not a valid extension.'
        if e not in exts:
            exts.append(e)
    for cat, lst in cats.items():
        if cat == editing:
            continue
        clash = [e for e in exts if e in lst]
        if clash:
            return False, f'{", ".join(clash)} already belongs to "{cat}".'
    return True, (name, exts)


# ----------------------------------------------------------------------------
# Custom Cyberpunk UI Widgets & Dialogs
# ----------------------------------------------------------------------------
class FlatButton(tk.Button):
    def __init__(self, parent, text, command, color=BTN, hover=BTN_HOVER, fg=TEXT, border_color=None, **kw):
        bd_width = 1 if border_color else 0
        super().__init__(
            parent, text=text, command=command, bg=color, fg=fg,
            activebackground=hover, activeforeground=fg, bd=bd_width, relief="flat",
            padx=14, pady=7, font=FONT_B, cursor="hand2", highlightthickness=0,
            disabledforeground="#475569", **kw)
        self.color, self.hover = color, hover
        self.bind("<Enter>", lambda e: self["state"] == "normal" and self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self["state"] == "normal" and self.config(bg=self.color))

    def set_enabled(self, enabled):
        if enabled:
            self.config(state="normal", bg=self.color, cursor="hand2")
        else:
            self.config(state="disabled", bg="#141a26", cursor="arrow")


def card(parent, title, subtitle=None):
    frame = tk.Frame(parent, bg=CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=CARD_BORDER)
    head = tk.Frame(frame, bg=CARD)
    head.pack(fill="x")
    tk.Label(head, text=title, font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
    if subtitle:
        tk.Label(head, text=subtitle, font=FONT_S, bg=CARD, fg=MUTED).pack(side="left", padx=10)
    return frame


def dark_entry(parent, var, width=42):
    return tk.Entry(parent, textvariable=var, width=width, bg=CARD2, fg=TEXT, insertbackground=ACCENT_CYAN,
                    bd=0, font=FONT, highlightthickness=1, highlightbackground=CARD_BORDER, highlightcolor=ACCENT_CYAN)


class PreviewDialog(tk.Toplevel):
    """Dry Run / Preview Window showing proposed moves before execution."""

    def __init__(self, parent, items, on_confirm):
        super().__init__(parent)
        self.title("Sort Preview - Proposed File Relocations")
        self.geometry("900x560")
        self.minsize(760, 420)
        self.configure(bg=CARD, padx=18, pady=16)
        self.on_confirm = on_confirm

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="🔍  Sort Preview", font=FONT_TITLE, bg=CARD, fg=ACCENT_CYAN).pack(side="left")
        total_size = sum(item["size"] for item in items)
        tk.Label(head, text=f"{len(items)} file(s) found ({format_size(total_size)})",
                 font=FONT_B, bg=CARD, fg=ACCENT_PURPLE).pack(side="right")

        tk.Label(self, text="Review proposed destinations before files are moved. None of your files have been touched.",
                 font=FONT_S, bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 8))

        wrap = tk.Frame(self, bg=CARD)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=("file", "origin", "dest", "size"), show="headings", height=12)
        tree.heading("file", text="File Name")
        tree.heading("origin", text="Detected App / Origin")
        tree.heading("dest", text="Destination Subfolder")
        tree.heading("size", text="Size")
        tree.column("file", width=250, anchor="w")
        tree.column("origin", width=180, anchor="w")
        tree.column("dest", width=290, anchor="w")
        tree.column("size", width=90, anchor="e")

        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        for item in items:
            tree.insert("", "end", values=(item["name"], item["origin"], item["dest"], format_size(item["size"])))

        btns = tk.Frame(self, bg=CARD)
        btns.pack(fill="x", pady=(14, 0))
        FlatButton(btns, "Cancel", self.destroy).pack(side="left")
        FlatButton(btns, "🚀  Proceed & Sort All Now", self.confirm, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(side="right")

        self.transient(parent)
        self.grab_set()

    def confirm(self):
        self.destroy()
        if self.on_confirm:
            self.on_confirm()


class CategoryDialog(tk.Toplevel):
    def __init__(self, parent, title, cats, name="", exts="", editing=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=CARD, padx=22, pady=18)
        self.resizable(False, False)
        self.cats, self.editing, self.result = cats, editing, None

        tk.Label(self, text=title, font=FONT_H, bg=CARD, fg=ACCENT_CYAN).grid(row=0, column=0, sticky="w", pady=(0, 12))
        tk.Label(self, text="Folder name", font=FONT, bg=CARD, fg=TEXT).grid(row=1, column=0, sticky="w")
        self.name_var = tk.StringVar(value=name)
        e1 = dark_entry(self, self.name_var)
        e1.grid(row=2, column=0, ipady=6, pady=(2, 10), sticky="we")
        tk.Label(self, text="File extensions (separated by commas)", font=FONT, bg=CARD, fg=TEXT).grid(row=3, column=0, sticky="w")
        self.ext_var = tk.StringVar(value=exts)
        dark_entry(self, self.ext_var).grid(row=4, column=0, ipady=6, pady=(2, 2), sticky="we")
        tk.Label(self, text="Example:  .jpg, .png, .heic, .webp", font=FONT_S, bg=CARD, fg=MUTED).grid(row=5, column=0, sticky="w")
        self.err = tk.Label(self, text="", font=FONT_B, bg=CARD, fg=RED, wraplength=340, justify="left")
        self.err.grid(row=6, column=0, sticky="w", pady=(8, 0))
        btns = tk.Frame(self, bg=CARD)
        btns.grid(row=7, column=0, sticky="e", pady=(14, 0))
        FlatButton(btns, "Cancel", self.destroy).pack(side="left", padx=6)
        FlatButton(btns, "Save", self.save, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(side="left")
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(parent)
        self.grab_set()
        e1.focus_set()

    def save(self):
        ok, res = validate_category(self.name_var.get(), self.ext_var.get(), self.cats, self.editing)
        if not ok:
            self.err.config(text="✖  " + res)
            return
        self.result = res
        self.destroy()


class NewFolderDialog(tk.Toplevel):
    def __init__(self, parent, path, rules):
        super().__init__(parent)
        self.title("Folder Organization Rules")
        self.configure(bg=CARD, padx=22, pady=18)
        self.resizable(False, False)
        self.rules, self.result = rules, None

        tk.Label(self, text="Add New Folder to Organize", font=FONT_H, bg=CARD, fg=ACCENT_CYAN).pack(anchor="w")
        tk.Label(self, text=path, font=FONT_MONO, bg=CARD, fg=TEXT, wraplength=520, justify="left").pack(anchor="w", pady=(4, 12))

        # Organization mode
        tk.Label(self, text="App & Origin Sorting Mode", font=FONT_B, bg=CARD, fg=ACCENT_PURPLE).pack(anchor="w")
        self.org_combo = ttk.Combobox(self, values=ORGANIZE_LABELS, state="readonly", style="Dark.TCombobox", width=62)
        self.org_combo.current(0)
        self.org_combo.pack(anchor="w", pady=(2, 10))

        # Categories
        tk.Label(self, text="File Types & Category Sets", font=FONT_B, bg=CARD, fg=TEXT).pack(anchor="w")
        self.mode = tk.StringVar(value="default")
        rb = dict(bg=CARD, fg=TEXT, selectcolor=CARD2, activebackground=CARD, activeforeground=ACCENT_CYAN,
                  font=FONT, bd=0, highlightthickness=0, anchor="w")
        tk.Radiobutton(self, text="Default set (Images, Documents, Media, Software, Compressed)",
                       variable=self.mode, value="default", **rb).pack(anchor="w", pady=(2, 0))
        if rules:
            tk.Radiobutton(self, text="Copy rules from existing folder:", variable=self.mode, value="copy", **rb).pack(anchor="w")
            self.copy_var = tk.StringVar(value=rules[0]["path"])
            ttk.Combobox(self, textvariable=self.copy_var, values=[r["path"] for r in rules],
                         state="readonly", style="Dark.TCombobox", width=62).pack(anchor="w", padx=(22, 0), pady=(2, 0))

        # Date subfolders
        tk.Label(self, text="Date Folders inside Category", font=FONT_B, bg=CARD, fg=TEXT).pack(anchor="w", pady=(12, 2))
        self.date_combo = ttk.Combobox(self, values=DATE_LABELS, state="readonly", style="Dark.TCombobox", width=62)
        self.date_combo.current(0)
        self.date_combo.pack(anchor="w")

        btns = tk.Frame(self, bg=CARD)
        btns.pack(anchor="e", pady=(16, 0))
        FlatButton(btns, "Cancel", self.destroy).pack(side="left", padx=6)
        FlatButton(btns, "Add folder", self.ok, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self.transient(parent)
        self.grab_set()

    def ok(self):
        cats = DEFAULT_CATEGORIES
        if self.mode.get() == "copy":
            src = next((r for r in self.rules if r["path"] == self.copy_var.get()), None)
            if src:
                cats = src["categories"]
        org_mode = ORGANIZE_MODES[self.org_combo.current()]
        date_mode = DATE_MODES[self.date_combo.current()]
        self.result = (copy.deepcopy(cats), date_mode, org_mode)
        self.destroy()


# ----------------------------------------------------------------------------
# Main Application Class
# ----------------------------------------------------------------------------
class OrganizerApp:
    _tray_hint_shown = False

    def __init__(self, root, initial_folder=None):
        self.root = root
        self.stats = dict(_stats)
        self.logo_header_img = None
        self.logo_about_img = None
        self.tk_icon = None
        self._poll_job = None

        self.setup_window_icons()

        root.title(f"{APP_NAME} Pro")
        root.geometry("1060x860")
        root.minsize(940, 740)
        root.configure(bg=BG)

        self.setup_styles()
        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.refresh_folders(select=0)
        self.refresh_history()
        self.set_running_ui(_is_watching)
        self.poll_queue()

        self.root.update_idletasks()
        trim_working_set()

        self.log("Ready. Smart metadata & app origin detector loaded.", "info")
        if CONFIG_LOAD_ERROR:
            self.log(CONFIG_LOAD_ERROR, "warning")
        if not (_tray and _tray.running):
            self.log("Tray icon off. To enable: pip install pystray pillow", "info")

        # Handle initial folder from context menu or command line
        if initial_folder:
            norm_init = norm(initial_folder)
            match = next((r for r in cfg["folders"] if norm(r["path"]) == norm_init), None)
            if not match:
                cfg["folders"].append(new_folder_rule(initial_folder))
                self.save()
                self.refresh_folders(select=len(cfg["folders"]) - 1)
            self.root.after(300, lambda: self.sort_now(silent=False))

    def setup_window_icons(self):
        ico_path = os.path.join(ASSETS_DIR, "app_icon.ico")
        png_path = os.path.join(ASSETS_DIR, "logo_square.png")
        if IS_WIN and os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass
        if PIL_AVAILABLE and os.path.exists(png_path):
            try:
                im = Image.open(png_path)
                self.tk_icon = ImageTk.PhotoImage(im)
                self.root.iconphoto(True, self.tk_icon)
            except Exception:
                pass

    # ---------- window / tray lifecycle ----------
    def cleanup(self):
        if self._poll_job:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        self.logo_header_img = None
        self.logo_about_img = None
        self.tk_icon = None

    def hide_window(self):
        """Unload and destroy GUI window completely to release all RAM and GPU resources."""
        self.cleanup()
        try:
            self.root.destroy()
        except Exception:
            pass

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def on_close(self):
        if cfg["close_to_tray"] and _tray and _tray.running:
            self.hide_window()
            if not OrganizerApp._tray_hint_shown:
                OrganizerApp._tray_hint_shown = True
                _tray.notify(APP_NAME, "Running in system tray. Right-click icon to quit.")
            return
        if _is_watching and not messagebox.askyesno("Quit", "The organizer is actively running.\nStop watching and quit?", parent=self.root):
            return
        self.quit_app()

    def quit_app(self):
        global _main_running
        _main_running = False
        _gui_cmd_queue.put(("quit", None))
        self.cleanup()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- ttk styles ----------
    def setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        # Treeview
        s.configure("Treeview", background=CARD2, fieldbackground=CARD2, foreground=TEXT,
                    rowheight=30, borderwidth=0, font=FONT)
        s.configure("Treeview.Heading", background=BTN, foreground=ACCENT_CYAN, relief="flat", font=FONT_B)
        s.map("Treeview", background=[("selected", "#094067")], foreground=[("selected", "#ffffff")])
        s.map("Treeview.Heading", background=[("active", BTN_HOVER)])

        # Progressbar
        s.configure("Accent.Horizontal.TProgressbar", troughcolor=CARD2, background=ACCENT_CYAN,
                    bordercolor=CARD_BORDER, lightcolor=ACCENT_CYAN, darkcolor=ACCENT_CYAN, thickness=10)

        # Checkbutton
        s.configure("Dark.TCheckbutton", background=CARD, foreground=TEXT, font=FONT)
        s.map("Dark.TCheckbutton", background=[("active", CARD)], foreground=[("active", ACCENT_CYAN)])

        # Scrollbar
        s.configure("Vertical.TScrollbar", background=BTN, troughcolor=CARD2, bordercolor=CARD2,
                    lightcolor=BTN, darkcolor=BTN, arrowcolor=TEXT, relief="flat")
        s.map("Vertical.TScrollbar", background=[("active", BTN_HOVER)], lightcolor=[("active", BTN_HOVER)],
              darkcolor=[("active", BTN_HOVER)])

        # Notebook
        s.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG, lightcolor=BG,
                    darkcolor=BG, tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(18, 9), font=FONT_B,
                    borderwidth=0, bordercolor=BG, lightcolor=CARD, darkcolor=CARD)
        s.map("TNotebook.Tab",
              background=[("selected", CARD2)],
              foreground=[("selected", ACCENT_CYAN)],
              lightcolor=[("selected", CARD2)],
              darkcolor=[("selected", CARD2)])

        # Combobox
        s.configure("Dark.TCombobox", fieldbackground=CARD2, background=BTN, foreground=TEXT,
                    arrowcolor=ACCENT_CYAN, bordercolor=CARD_BORDER, lightcolor=CARD_BORDER, darkcolor=CARD_BORDER, padding=5)
        s.map("Dark.TCombobox", fieldbackground=[("readonly", CARD2)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", CARD2)], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", CARD2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#094067")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", FONT)

    # ---------- UI Layout ----------
    def build_ui(self):
        outer = tk.Frame(self.root, bg=BG, padx=22, pady=14)
        outer.pack(fill="both", expand=True)

        # Header with Logo
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 10))

        head_left = tk.Frame(header, bg=BG)
        head_left.pack(side="left", fill="y")

        # Load logo header thumbnail
        logo_h_path = os.path.join(ASSETS_DIR, "logo_header.png")
        if PIL_AVAILABLE and os.path.exists(logo_h_path):
            try:
                im = Image.open(logo_h_path)
                self.logo_header_img = ImageTk.PhotoImage(im)
                logo_lbl = tk.Label(head_left, image=self.logo_header_img, bg=BG)
                logo_lbl.pack(side="left", padx=(0, 14))
            except Exception:
                pass

        titles = tk.Frame(head_left, bg=BG)
        titles.pack(side="left", fill="y")

        t_row = tk.Frame(titles, bg=BG)
        t_row.pack(anchor="w")
        tk.Label(t_row, text="LELLA", font=FONT_TITLE, bg=BG, fg="#ffffff").pack(side="left")
        tk.Label(t_row, text="VERSE", font=FONT_TITLE, bg=BG, fg=ACCENT_CYAN).pack(side="left")
        tk.Label(t_row, text="SMART ORGANIZER", font=("Segoe UI", 11, "bold"), bg=BG, fg=ACCENT_PURPLE).pack(side="left", padx=(10, 0), pady=(4, 0))

        tk.Label(titles, text="Smart Metadata & App Origin Sorter  ·  Defender Virus Protection  ·  Duplicate Guard  ·  Instant Undo",
                 font=FONT_S, bg=BG, fg=MUTED).pack(anchor="w", pady=(2, 0))

        # Status Pill
        self.status_pill = tk.Label(header, text="●  STOPPED", font=FONT_B, bg=RED_BG, fg=RED, padx=16, pady=7,
                                    highlightthickness=1, highlightbackground=RED)
        self.status_pill.pack(side="right")

        # Action Buttons Row
        ctrl = tk.Frame(outer, bg=BG)
        ctrl.pack(fill="x", pady=(0, 6))
        self.start_btn = FlatButton(ctrl, "▶  START WATCHING", self.start_organizer, color="#059669", hover="#10b981", fg="#ffffff")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = FlatButton(ctrl, "⏹  STOP", self.stop_organizer, color="#be123c", hover="#e11d48", fg="#ffffff")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.stop_btn.set_enabled(False)
        self.preview_btn = FlatButton(ctrl, "🔍  Preview sort", self.preview_sort, color=BTN, hover=BTN_HOVER, fg=ACCENT_PURPLE)
        self.preview_btn.pack(side="left", padx=(0, 8))
        self.now_btn = FlatButton(ctrl, "⚡  Sort now", self.sort_now, color=BTN, hover=BTN_HOVER, fg=ACCENT_CYAN)
        self.now_btn.pack(side="left", padx=(0, 8))
        self.undo_btn = FlatButton(ctrl, "↩  Undo last", self.undo_last)
        self.undo_btn.pack(side="left")

        self.stats_label = tk.Label(ctrl, text="", font=FONT_B, bg=BG, fg=MUTED)
        self.stats_label.pack(side="right")
        self.update_stats()

        # Progress bar
        prog = tk.Frame(outer, bg=BG)
        prog.pack(fill="x", pady=(2, 8))
        self.progress = ttk.Progressbar(prog, style="Accent.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = tk.Label(prog, text="", font=FONT_S, bg=BG, fg=MUTED, width=18, anchor="e")
        self.progress_label.pack(side="left", padx=(8, 0))

        # Notebook tabs
        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True)
        self.tab_rules = tk.Frame(self.nb, bg=BG, pady=8)
        self.tab_log = tk.Frame(self.nb, bg=BG, pady=8)
        self.tab_hist = tk.Frame(self.nb, bg=BG, pady=8)
        self.tab_set = tk.Frame(self.nb, bg=BG, pady=8)
        self.tab_about = tk.Frame(self.nb, bg=BG, pady=8)

        self.nb.add(self.tab_rules, text="📁  Folders & rules")
        self.nb.add(self.tab_log, text="📜  Activity")
        self.nb.add(self.tab_hist, text="↩  History / Undo")
        self.nb.add(self.tab_set, text="⚙  Settings")
        self.nb.add(self.tab_about, text="ℹ  About")

        self.build_rules_tab()
        self.build_log_tab()
        self.build_history_tab()
        self.build_settings_tab()
        self.build_about_tab()

        self.last_label = tk.Label(outer, text="", font=FONT_S, bg=BG, fg=MUTED, anchor="w")
        self.last_label.pack(fill="x", pady=(6, 0))

    def build_rules_tab(self):
        c1 = card(self.tab_rules, "Folders to organize", "Each folder has customized sorting rules")
        c1.pack(fill="x")
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        wrap = tk.Frame(row, bg=CARD)
        wrap.pack(side="left", fill="x", expand=True)

        self.folder_tree = ttk.Treeview(wrap, columns=("path", "orgmode", "dates", "cats"), show="headings", height=4, selectmode="browse")
        self.folder_tree.heading("path", text="Folder")
        self.folder_tree.heading("orgmode", text="App Origin Mode")
        self.folder_tree.heading("dates", text="Date folders")
        self.folder_tree.heading("cats", text="Categories")
        self.folder_tree.column("path", width=380, anchor="w")
        self.folder_tree.column("orgmode", width=140, anchor="center")
        self.folder_tree.column("dates", width=90, anchor="center")
        self.folder_tree.column("cats", width=80, anchor="center")
        self.folder_tree.pack(side="left", fill="x", expand=True)
        self.folder_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh_rules())

        side = tk.Frame(row, bg=CARD)
        side.pack(side="left", padx=(12, 0), anchor="n")
        FlatButton(side, "＋  Add folder", self.add_folder, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(fill="x", pady=1)
        self.remove_btn = FlatButton(side, "Remove", self.remove_folder)
        self.remove_btn.pack(fill="x", pady=1)
        FlatButton(side, "Open in Explorer", self.open_folder).pack(fill="x", pady=1)

        c2 = card(self.tab_rules, "Rules for selected folder")
        c2.pack(fill="both", expand=True, pady=(8, 0))
        self.rules_title = tk.Label(c2, text="", font=FONT_MONO, bg=CARD, fg=ACCENT_CYAN, anchor="w")
        self.rules_title.pack(fill="x", pady=(4, 6))

        # Organization mode selector row
        org_row = tk.Frame(c2, bg=CARD)
        org_row.pack(fill="x", pady=(0, 8))
        tk.Label(org_row, text="App & Origin Sorting Mode:", font=FONT_B, bg=CARD, fg=ACCENT_PURPLE).pack(side="left")
        self.org_combo = ttk.Combobox(org_row, values=ORGANIZE_LABELS, state="readonly", style="Dark.TCombobox", width=58)
        self.org_combo.pack(side="left", padx=10)
        self.org_combo.bind("<<ComboboxSelected>>", self.on_org_mode)

        body = tk.Frame(c2, bg=CARD)
        body.pack(fill="both", expand=True)
        tw = tk.Frame(body, bg=CARD)
        tw.pack(side="left", fill="both", expand=True)
        self.cat_tree = ttk.Treeview(tw, columns=("folder", "ext"), show="headings", height=5, selectmode="browse")
        self.cat_tree.heading("folder", text="Category Folder")
        self.cat_tree.heading("ext", text="File Extensions")
        self.cat_tree.column("folder", width=160, anchor="w")
        self.cat_tree.column("ext", width=420, anchor="w")
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.cat_tree.yview)
        self.cat_tree.configure(yscrollcommand=sb.set)
        self.cat_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.cat_tree.bind("<Double-1>", lambda e: self.edit_category())

        cside = tk.Frame(body, bg=CARD)
        cside.pack(side="left", padx=(12, 0), anchor="n")
        FlatButton(cside, "＋  Add folder type", self.add_category, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(fill="x", pady=2)
        FlatButton(cside, "✎  Edit", self.edit_category).pack(fill="x", pady=2)
        FlatButton(cside, "🗑  Delete", self.delete_category).pack(fill="x", pady=2)
        FlatButton(cside, "↺  Reset defaults", self.reset_categories).pack(fill="x", pady=2)

        drow = tk.Frame(c2, bg=CARD)
        drow.pack(fill="x", pady=(10, 0))
        tk.Label(drow, text="Date folders inside category:", font=FONT_B, bg=CARD, fg=TEXT).pack(side="left")
        self.date_combo = ttk.Combobox(drow, values=DATE_LABELS, state="readonly", style="Dark.TCombobox", width=50)
        self.date_combo.pack(side="left", padx=10)
        self.date_combo.bind("<<ComboboxSelected>>", self.on_date_mode)

        tk.Label(c2, text="Automatic folders: Folders = sub-folders  ·  Others = unknown types  ·  Duplicates = identical files  ·  Infected_Malware = quarantined",
                 font=FONT_S, bg=CARD, fg=MUTED).pack(anchor="w", pady=(8, 0))

    def build_log_tab(self):
        c = card(self.tab_log, "Live activity log")
        c.pack(fill="both", expand=True)
        FlatButton(c.winfo_children()[0], "Clear Log", self.clear_log).pack(side="right")
        wrap = tk.Frame(c, bg=CARD)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.log_box = tk.Text(wrap, bg="#05080e", fg=MUTED, font=FONT_MONO, bd=0, padx=12, pady=10, state="disabled", wrap="word")
        lsb = ttk.Scrollbar(wrap, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=lsb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        lsb.pack(side="left", fill="y")
        for tag, color in (
            ("info", ACCENT_CYAN),
            ("success", GREEN),
            ("warning", ORANGE),
            ("error", RED),
            ("time", DARK_MUTED),
            ("purple", ACCENT_PURPLE)
        ):
            self.log_box.tag_config(tag, foreground=color)

    def build_history_tab(self):
        c = card(self.tab_hist, "Organizer Move History", "Select moves and click Undo to restore files")
        c.pack(fill="both", expand=True)
        wrap = tk.Frame(c, bg=CARD)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.hist_tree = ttk.Treeview(wrap, columns=("time", "file", "origin", "to", "kind"), show="headings", selectmode="extended")
        for col, text, w in (
            ("time", "Timestamp", 100),
            ("file", "File Name", 210),
            ("origin", "Detected App / Source", 160),
            ("to", "Destination Subfolder", 260),
            ("kind", "Status", 80)
        ):
            self.hist_tree.heading(col, text=text)
            self.hist_tree.column(col, width=w, anchor="w")
        hsb = ttk.Scrollbar(wrap, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=hsb.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        hsb.pack(side="left", fill="y")

        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        FlatButton(row, "↩  Undo Selected", self.undo_selected, color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(side="left")
        FlatButton(row, "Allow re-sorting undone files", self.forget_undone).pack(side="left", padx=8)
        tk.Label(row, text="Undone files are pinned in place until you allow re-sorting.",
                 font=FONT_S, bg=CARD, fg=MUTED).pack(side="left", padx=6)

    def build_settings_tab(self):
        c = card(self.tab_set, "Settings & Preferences")
        c.pack(fill="x")
        self.setting_vars = {}

        def group(title):
            tk.Label(c, text=title, font=FONT_B, bg=CARD, fg=ACCENT_CYAN).pack(anchor="w", pady=(12, 2))

        def check(key, text):
            var = tk.BooleanVar(value=cfg.get(key, DEFAULT_SETTINGS.get(key, False)))
            self.setting_vars[key] = var
            ttk.Checkbutton(c, text=text, variable=var, style="Dark.TCheckbutton",
                            command=lambda k=key: self.on_setting(k)).pack(anchor="w", pady=2)

        group("Smart Metadata & App Origin Detection")
        check("detect_metadata", "Inspect file metadata (EXIF camera model, app encoders, PDF & Office creators)")
        check("detect_apps", "Auto-detect social & messaging apps (WhatsApp, Telegram, Instagram, TikTok, Snapchat, Facebook)")
        check("separate_screenshots", "Detect and separate Screenshots into dedicated folder")
        check("separate_recordings", "Detect and separate Screen Recordings (OBS, Bandicam, Zoom) into dedicated folder")

        group("File Organizing")
        check("sort_existing", "Sort existing files & folders inside watched directories when START is clicked")
        check("check_duplicates", 'Identify identical duplicate files (content hash) and move to "Duplicates"')

        group("Windows Explorer Integration")
        check("explorer_context_menu", "Add 'Organize with LellaVerse' to Windows right-click folder menu")

        group("Antivirus & Security")
        check("scan_virus", "Scan new downloads with Windows Defender before sorting")
        check("scan_existing", "Also scan older files during initial sort (slower)")

        group("Background & System")
        check("auto_start_watching", "Automatically start organizer when app launches")
        check("close_to_tray", "Closing the window minimizes to system tray (keeps watching)")
        check("start_with_windows", "Start with Windows  (hidden in tray, 20s boot delay, low priority)")

        tray_text = ("Tray icon: Active & running." if self.tray_ok else "Tray icon: Not installed.  Run: pip install pystray pillow")
        tk.Label(c, text=tray_text, font=FONT_S, bg=CARD, fg=GREEN if self.tray_ok else ORANGE).pack(anchor="w", pady=(10, 0))

    def build_about_tab(self):
        c = card(self.tab_about, f"{APP_NAME}", f"Version {APP_VERSION}")
        c.pack(fill="both", expand=True)

        logo_ab_path = os.path.join(ASSETS_DIR, "logo_about.png")
        if PIL_AVAILABLE and os.path.exists(logo_ab_path):
            try:
                im = Image.open(logo_ab_path)
                self.logo_about_img = ImageTk.PhotoImage(im)
                logo_banner = tk.Label(c, image=self.logo_about_img, bg=CARD)
                logo_banner.pack(anchor="center", pady=(0, 10))
            except Exception:
                pass

        def heading(text):
            tk.Label(c, text=text, font=FONT_B, bg=CARD, fg=ACCENT_CYAN).pack(anchor="w", pady=(8, 2))

        def line(text, color=TEXT):
            tk.Label(c, text=text, font=FONT, bg=CARD, fg=color, justify="left", wraplength=880, anchor="w").pack(anchor="w")

        line("LellaVerse Smart Organizer is an intelligent Windows file organizer. It reads metadata, "
             "detects the origin application of mixed file dumps (WhatsApp, Telegram, Instagram, TikTok, Snapchat, "
             "Screenshots, Camera Photos), and automatically sorts them without ever overwriting anything.")

        heading("Key Capabilities")
        line("•  Metadata & App Recognition: EXIF camera info, app signatures, encoders, PDF/Office creators")
        line("•  Preview Sort (Dry Run): Inspect proposed file movements before any files are touched")
        line("•  Windows Explorer Context Menu: Right-click any folder in Windows and select 'Organize with LellaVerse'")
        line("•  Smart Subfolders: Organizes files into clean subfolders like Images\\WhatsApp, Images\\Screenshots, Media\\TikTok")
        line("•  Chronological Sorting: Uses real EXIF capture timestamp or arrival date (Weekly / Monthly)")
        line("•  Safe Quarantine: Automatic Windows Defender scan; infected files go to Infected_Malware")
        line("•  Duplicate Protection: Identical files go to Duplicates; same-name clashes get safe timestamped names")
        line("•  Instant Undo: One-click restore of any move directly from the History tab")

        heading("Privacy & Open Source")
        line("100% Local & Private. No data is ever uploaded or transmitted online. Virus scans use the Windows Defender engine already installed on your PC.")

        heading("Links & Author")
        row = tk.Frame(c, bg=CARD)
        row.pack(anchor="w", pady=(4, 0))
        FlatButton(row, "🌐  GitHub Project", lambda: webbrowser.open(GITHUB_URL), color=ACCENT_CYAN, hover=ACCENT_CYAN_HOVER, fg="#04151f").pack(side="left", padx=(0, 8))
        FlatButton(row, "🐞  Report an Issue", lambda: webbrowser.open(GITHUB_URL + "/issues")).pack(side="left", padx=(0, 8))
        FlatButton(row, "📂  Open Settings Folder", self.open_settings_folder).pack(side="left")

        tk.Label(c, text=f"Designed & Built by {AUTHOR}  ·  MIT License  ·  Powered by Python, watchdog, pystray & Pillow",
                 font=FONT_S, bg=CARD, fg=MUTED).pack(side="bottom", anchor="w", pady=(12, 0))

    def open_settings_folder(self):
        try:
            os.startfile(HOME)
        except AttributeError:
            messagebox.showinfo("Settings Folder", HOME, parent=self.root)
        except Exception as e:
            messagebox.showerror("Cannot open folder", str(e), parent=self.root)

    # ---------- logging / stats ----------
    def log(self, text, level="info"):
        icon = {"info": "•", "success": "✔", "warning": "⚠", "error": "✖"}.get(level, "•")
        self.log_box.config(state="normal")
        self.log_box.insert("end", datetime.now().strftime("[%H:%M:%S] "), "time")
        self.log_box.insert("end", f"{icon} {text}\n", level)
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        color = {"success": GREEN, "warning": ORANGE, "error": RED}.get(level, ACCENT_CYAN)
        self.last_label.config(text=f"{icon} {text}", fg=color)

    def clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def update_stats(self):
        s = self.stats
        size_str = f" ({format_size(s['bytes_moved'])})" if s["bytes_moved"] > 0 else ""
        dupe_str = f" ({format_size(s['bytes_dupes'])} saved)" if s["bytes_dupes"] > 0 else ""
        self.stats_label.config(
            text=f"Sorted: {s['moved']}{size_str}  ·  Duplicates: {s['dupes']}{dupe_str}  ·  Quarantined: {s['infected']}  ·  Errors: {s['errors']}",
            fg=RED if s["errors"] or s["infected"] else MUTED)

    def poll_queue(self):
        try:
            while True:
                item = ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log(item[1], item[2])
                elif kind == "stat":
                    key = item[1]
                    amount = item[2] if len(item) > 2 else 1
                    self.stats[key] = self.stats.get(key, 0) + amount
                    self.update_stats()
                elif kind == "progress":
                    done, total = item[1], item[2]
                    self.progress.config(maximum=max(total, 1), value=done)
                    self.progress_label.config(text=f"Organizing {done} / {total}" if total else "")
                    self.now_btn.set_enabled(False)
                    self.preview_btn.set_enabled(False)
                elif kind == "done":
                    self.now_btn.set_enabled(True)
                    self.preview_btn.set_enabled(True)
                    self.progress_label.config(text="Done ✔")
                elif kind == "history":
                    self.refresh_history()
                elif kind == "notify":
                    if _tray:
                        _tray.notify(item[1], item[2])
                elif kind == "popup":
                    self.log(f"{item[1]}: {item[2]}", "error")
                    messagebox.showerror(item[1], item[2], parent=self.root)
        except queue.Empty:
            pass
        try:
            if self.root.winfo_exists():
                self._poll_job = self.root.after(200, self.poll_queue)
        except Exception:
            pass

    # ---------- settings ----------
    def save(self):
        ok, err = save_config()
        if not ok:
            self.log(f"Could not save settings: {err}", "error")
            messagebox.showerror("Cannot save settings", err, parent=self.root)
        return ok

    def on_setting(self, key):
        var = self.setting_vars[key]
        value = var.get()
        if key == "start_with_windows":
            try:
                set_autostart(value)
            except Exception as e:
                var.set(not value)
                messagebox.showerror("Cannot change start-up setting", str(e), parent=self.root)
                self.log(f"Start-up setting failed: {e}", "error")
                return
            self.log("LellaVerse will start with Windows." if value else "Will not start with Windows.", "info")
        elif key == "explorer_context_menu":
            try:
                set_explorer_context_menu(value)
            except Exception as e:
                var.set(not value)
                messagebox.showerror("Explorer Context Menu", str(e), parent=self.root)
                self.log(f"Explorer context menu failed: {e}", "error")
                return
            self.log("Added 'Organize with LellaVerse' to Explorer menu." if value else "Removed from Explorer menu.", "info")

        cfg[key] = value
        self.save()

    # ---------- preview sort (dry run) ----------
    def preview_sort(self):
        """Scans watched folders and opens the Preview Sort simulation dialog."""
        if not cfg["folders"]:
            messagebox.showinfo("Preview Sort", "Please add at least one folder first.", parent=self.root)
            return

        preview_items = []
        for rule in cfg["folders"]:
            if not os.path.isdir(rule["path"]):
                continue
            try:
                names = managed_names(rule)
                for item in sorted(os.listdir(rule["path"])):
                    p = os.path.join(rule["path"], item)
                    if item.lower() not in names and not is_ignored(p) and not is_pinned(p):
                        try:
                            f_size = os.path.getsize(p) if os.path.isfile(p) else dir_size(p)
                        except OSError:
                            f_size = 0
                        folder, sub, origin_label = determine_destination(p, rule)
                        dest_display = f"{folder}\\{sub}" if sub else folder
                        preview_items.append({
                            "name": item,
                            "path": p,
                            "origin": origin_label,
                            "dest": dest_display,
                            "size": f_size
                        })
            except Exception as e:
                self.log(f"Error reading folder for preview: {e}", "warning")

        if not preview_items:
            messagebox.showinfo("Preview Sort", "All watched folders are already organized! No files to sort.", parent=self.root)
            return

        PreviewDialog(self.root, preview_items, on_confirm=lambda: self.sort_now(silent=False))

    # ---------- folders ----------
    def current_index(self):
        sel = self.folder_tree.selection()
        if sel:
            idx = int(sel[0])
            if 0 <= idx < len(cfg["folders"]):
                return idx
        return None

    def current_rule(self):
        idx = self.current_index()
        return cfg["folders"][idx] if idx is not None else None

    def refresh_folders(self, select=None):
        if select is None:
            select = self.current_index()
        self.folder_tree.delete(*self.folder_tree.get_children())
        for i, r in enumerate(cfg["folders"]):
            org_short = ORGANIZE_SHORT.get(r.get("organize_mode", "smart_app"), "Smart App")
            self.folder_tree.insert(
                "", "end", iid=str(i),
                values=(r["path"], org_short, DATE_SHORT.get(r.get("date_mode", "off"), "Off"), len(r["categories"]))
            )
        if cfg["folders"]:
            select = min(select if select is not None else 0, len(cfg["folders"]) - 1)
            self.folder_tree.selection_set(str(select))
        self.refresh_rules()

    def refresh_rules(self):
        rule = self.current_rule()
        self.cat_tree.delete(*self.cat_tree.get_children())
        if rule is None:
            self.rules_title.config(text="No folder selected - press  ＋ Add folder  above.")
            self.date_combo.set("")
            self.org_combo.set("")
            return
        self.rules_title.config(text=rule["path"])
        for name, exts in rule["categories"].items():
            self.cat_tree.insert("", "end", iid=name, values=(name, ", ".join(exts)))
        self.date_combo.current(DATE_MODES.index(rule.get("date_mode", "off")))
        org_mode = rule.get("organize_mode", "smart_app")
        if org_mode in ORGANIZE_MODES:
            self.org_combo.current(ORGANIZE_MODES.index(org_mode))

    def on_date_mode(self, _event=None):
        rule = self.current_rule()
        if rule is None:
            return
        rule["date_mode"] = DATE_MODES[self.date_combo.current()]
        self.save()
        self.refresh_folders()
        self.log(f"Date folders for {rule['path']}: {DATE_SHORT[rule['date_mode']]}", "info")

    def on_org_mode(self, _event=None):
        rule = self.current_rule()
        if rule is None:
            return
        rule["organize_mode"] = ORGANIZE_MODES[self.org_combo.current()]
        self.save()
        self.refresh_folders()
        self.log(f"Sorting mode for {rule['path']}: {ORGANIZE_SHORT[rule['organize_mode']]}", "info")

    def add_folder(self):
        start = cfg["folders"][-1]["path"] if cfg["folders"] else HOME
        path = filedialog.askdirectory(initialdir=start, title="Choose a folder to organize", parent=self.root)
        if not path:
            return
        path = os.path.normpath(path)
        ok, err = check_watch_path(path)
        if not ok:
            messagebox.showerror("Cannot use this folder", err, parent=self.root)
            self.log(f"Folder rejected: {path}", "error")
            return
        conflict = folder_conflict(path)
        if conflict:
            messagebox.showerror("Cannot use this folder", conflict, parent=self.root)
            return
        dlg = NewFolderDialog(self.root, path, cfg["folders"])
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        cats, date_mode, org_mode = dlg.result
        rule = new_folder_rule(path, cats, date_mode, org_mode)
        cfg["folders"].append(rule)
        self.save()
        self.refresh_folders(select=len(cfg["folders"]) - 1)
        self.log(f"Added folder: {path}", "success")
        if _is_watching:
            self.attach_watch(rule)
            if cfg["sort_existing"]:
                self.log("Organizing existing files and folders...", "info")
                organize_existing()

    def remove_folder(self):
        global _observer, _watches
        idx = self.current_index()
        if idx is None:
            messagebox.showinfo("Remove folder", "Please click a folder in the list first.", parent=self.root)
            return
        rule = cfg["folders"][idx]
        if not messagebox.askyesno("Remove folder",
                                   f"Stop organizing this folder?\n\n{rule['path']}\n\nYour files remain untouched.",
                                   parent=self.root):
            return
        del cfg["folders"][idx]
        key = norm(rule["path"])
        if _observer and key in _watches:
            try:
                _observer.unschedule(_watches.pop(key))
            except Exception as e:
                self.log(f"Could not stop watching '{rule['path']}': {e}", "warning")
        self.save()
        self.refresh_folders(select=max(idx - 1, 0))
        self.log(f"Removed folder: {rule['path']}", "info")

    def open_folder(self):
        rule = self.current_rule()
        if rule is None:
            messagebox.showinfo("Open folder", "Add a folder first.", parent=self.root)
            return
        try:
            os.startfile(rule["path"])
        except AttributeError:
            messagebox.showinfo("Folder", rule["path"], parent=self.root)
        except Exception as e:
            messagebox.showerror("Cannot open folder", str(e), parent=self.root)

    def attach_watch(self, rule):
        global _observer, _watches
        try:
            create_category_folders(rule)
            if _is_watching and _observer:
                _watches[norm(rule["path"])] = _observer.schedule(OrganizerHandler(), rule["path"], recursive=False)
            self.log(f"Watching: {rule['path']}", "info")
        except Exception as e:
            self.log(f"Could not watch '{rule['path']}': {e}", "error")
            messagebox.showerror("Cannot watch folder", f"{rule['path']}\n\n{e}", parent=self.root)

    # ---------- categories ----------
    def need_rule(self):
        rule = self.current_rule()
        if rule is None:
            messagebox.showinfo("Folder rules", "Add a folder first, then select it in the list.", parent=self.root)
        return rule

    def selected_category(self):
        sel = self.cat_tree.selection()
        return sel[0] if sel else None

    def make_folder_now(self, rule, name):
        if check_watch_path(rule["path"])[0]:
            try:
                os.makedirs(os.path.join(rule["path"], name), exist_ok=True)
            except Exception as e:
                self.log(f"Could not create '{name}': {e}", "error")
                messagebox.showerror("Cannot create folder", f"{name}\n\n{e}", parent=self.root)

    def add_category(self):
        rule = self.need_rule()
        if rule is None:
            return
        dlg = CategoryDialog(self.root, "Add New Folder Type", rule["categories"])
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        name, exts = dlg.result
        rule["categories"][name] = exts
        if self.save():
            self.make_folder_now(rule, name)
            self.refresh_folders()
            self.log(f"Added category '{name}' ({', '.join(exts)})", "success")

    def edit_category(self):
        rule = self.need_rule()
        if rule is None:
            return
        old = self.selected_category()
        if not old:
            messagebox.showinfo("Edit", "Please select a category in the list first.", parent=self.root)
            return
        dlg = CategoryDialog(self.root, "Edit Folder Type", rule["categories"], old, ", ".join(rule["categories"][old]), editing=old)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        name, exts = dlg.result
        rule["categories"] = {(name if k == old else k): (exts if k == old else v) for k, v in rule["categories"].items()}
        if name != old:
            src, dst = os.path.join(rule["path"], old), os.path.join(rule["path"], name)
            if os.path.isdir(src) and not os.path.exists(dst):
                try:
                    os.rename(src, dst)
                    self.log(f"Renamed category '{old}' → '{name}'", "info")
                except Exception as e:
                    self.log(f"Could not rename folder on disk: {e}", "error")
        if self.save():
            self.make_folder_now(rule, name)
            self.refresh_folders()
            self.log(f"Updated category '{name}' ({', '.join(exts)})", "success")

    def delete_category(self):
        rule = self.need_rule()
        if rule is None:
            return
        name = self.selected_category()
        if not name:
            messagebox.showinfo("Delete", "Please select a category in the list first.", parent=self.root)
            return
        if messagebox.askyesno("Delete Category",
                               f'Remove "{name}" from this folder\'s rules?\n\nFiles already on disk are NOT deleted.',
                               parent=self.root):
            del rule["categories"][name]
            if self.save():
                self.refresh_folders()
                self.log(f"Removed category '{name}'", "info")

    def reset_categories(self):
        rule = self.need_rule()
        if rule is None:
            return
        if messagebox.askyesno("Reset", "Reset to default categories for this folder?", parent=self.root):
            rule["categories"] = copy.deepcopy(DEFAULT_CATEGORIES)
            if self.save():
                self.refresh_folders()
                self.log("Categories reset to default.", "info")

    # ---------- history / undo ----------
    def refresh_history(self):
        self.hist_tree.delete(*self.hist_tree.get_children())
        with _hist_lock:
            entries = list(_history)
        for e in reversed(entries):
            try:
                rel = os.path.relpath(e["dst"], os.path.dirname(e["src"]))
            except ValueError:
                rel = e["dst"]
            when = e["time"][5:16].replace("T", "  ")
            origin = e.get("origin", "General")
            self.hist_tree.insert(
                "", "end", iid=str(e["id"]),
                values=(when, os.path.basename(e["src"]), origin, rel, KIND_LABELS.get(e["kind"], e["kind"]))
            )
        self.undo_btn.set_enabled(bool(entries))

    def do_undo(self, ids):
        with _hist_lock:
            kinds = {e["id"]: e["kind"] for e in _history}
        if any(kinds.get(i) == "virus" for i in ids):
            if not messagebox.askyesno("Restore infected file?",
                                       "At least one of these files was quarantined as a VIRUS.\n\nRestore it anyway?",
                                       icon="warning", parent=self.root):
                return
        done = 0
        for i in ids:
            ok, msg = undo_move(i)
            if ok:
                done += 1
                self.log(msg, "success")
            else:
                self.log(msg.replace("\n\n", " ").replace("\n", " "), "error")
                messagebox.showerror("Cannot undo", msg, parent=self.root)
        if done:
            self.log(f"Undo complete: {done} file(s) restored.", "success")
        self.refresh_history()

    def undo_selected(self):
        ids = [int(i) for i in self.hist_tree.selection()]
        if not ids:
            messagebox.showinfo("Undo", "Select one or more items in the history first.", parent=self.root)
            return
        self.do_undo(ids)

    def undo_last(self):
        with _hist_lock:
            last = _history[-1]["id"] if _history else None
        if last is None:
            messagebox.showinfo("Undo", "There is nothing to undo yet.", parent=self.root)
            return
        self.do_undo([last])

    def forget_undone(self):
        forget_pins()
        self.log("Undone files can now be re-organized (click Sort now).", "info")

    # ---------- run ----------
    def start_organizer(self, silent=False):
        start_watching(silent=silent)

    def stop_organizer(self):
        stop_watching()

    def sort_now(self, silent=False):
        sort_now(silent=silent)

    def set_running_ui(self, running):
        self.start_btn.set_enabled(not running)
        self.stop_btn.set_enabled(running)
        if running:
            self.status_pill.config(text="●  RUNNING", fg=GREEN, bg=GREEN_BG, highlightbackground=GREEN)
        else:
            self.status_pill.config(text="●  STOPPED", fg=RED, bg=RED_BG, highlightbackground=RED)


def prepare_folders(silent=False):
    if not cfg["folders"]:
        msg = "Please add at least one folder first (＋ Add folder)."
        log(msg, "warning")
        if not silent and _active_app:
            messagebox.showinfo("Cannot start", msg, parent=_active_app.root)
        return False
    bad = [check_watch_path(r["path"])[1] for r in cfg["folders"] if not check_watch_path(r["path"])[0]]
    if bad:
        msg = "\n\n".join(bad)
        log(msg, "error")
        if not silent and _active_app:
            messagebox.showerror("Cannot start", msg, parent=_active_app.root)
        return False
    for r in cfg["folders"]:
        try:
            create_category_folders(r)
        except Exception as e:
            log(f"Cannot create folders in {r['path']}: {e}", "error")
            return False
    return True


def start_watching(silent=False):
    global _observer, _watches, _is_watching
    if _is_watching:
        return True
    if not prepare_folders(silent=silent):
        return False
    if cfg["scan_virus"] and not DEFENDER_PATH:
        log("Windows Defender not found - virus scan will be skipped.", "warning")

    try:
        _observer = Observer()
        _watches = {}
        handler = OrganizerHandler()
        for r in cfg["folders"]:
            _watches[norm(r["path"])] = _observer.schedule(handler, r["path"], recursive=False)
        _observer.start()
        _is_watching = True
        log("Active watcher started.", "info")
        for r in cfg["folders"]:
            log(f"Active watcher started: {r['path']}", "info")
        n = len(cfg["folders"])
        if _tray:
            _tray.set_title(f"{APP_NAME} - running ({n} folder{'s' if n != 1 else ''})")
        if _active_app:
            _active_app.set_running_ui(True)
        if cfg["sort_existing"]:
            log("Organizing existing files...", "info")
            organize_existing()
        return True
    except Exception as e:
        _observer, _watches = None, {}
        _is_watching = False
        log(f"Cannot start watching: {e}", "error")
        if not silent and _active_app:
            messagebox.showerror("Cannot start watching", str(e), parent=_active_app.root)
        return False


def stop_watching():
    global _observer, _watches, _is_watching
    if _is_watching and _observer:
        try:
            _observer.stop()
            _observer.join(timeout=3)
        except Exception:
            pass
        _observer = None
        _watches = {}
    _is_watching = False
    log("Organizer stopped.", "info")
    if _tray:
        _tray.set_title(f"{APP_NAME} - stopped")
    if _active_app:
        _active_app.set_running_ui(False)


def sort_now(silent=False):
    if prepare_folders(silent=silent):
        log("Organizing existing files...", "info")
        organize_existing()


def run_gui_window(initial_folder=None):
    global _active_app
    if _active_app is not None:
        try:
            _active_app.root.deiconify()
            _active_app.root.lift()
            _active_app.root.focus_force()
        except Exception:
            pass
        return

    root = tk.Tk()
    app = OrganizerApp(root, initial_folder=initial_folder)
    _active_app = app
    app.show_window()
    try:
        root.mainloop()
    except Exception:
        pass
    finally:
        _active_app = None
        try:
            root.destroy()
        except Exception:
            pass
        del app
        del root
        import gc
        gc.collect()
        trim_working_set()


def main():
    global _main_running, _tray
    minimized = "--minimized" in sys.argv

    # Check for context menu sort argument: python lellaverse_organizer.py --sort "C:\path"
    initial_folder = None
    if "--sort" in sys.argv:
        try:
            idx = sys.argv.index("--sort")
            if idx + 1 < len(sys.argv):
                candidate = sys.argv[idx + 1]
                if os.path.isdir(candidate):
                    initial_folder = os.path.normpath(candidate)
        except Exception:
            pass

    if not acquire_single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "The organizer is already running.\nCheck your system tray (near the clock).")
        root.destroy()
        return

    lower_priority()

    # Start system tray icon
    _tray = Tray()
    _tray.start()

    # Auto start watching if configured or if launched minimized
    if cfg.get("auto_start_watching", False) or minimized:
        start_watching(silent=True)

    if not minimized or initial_folder:
        _gui_cmd_queue.put(("open", initial_folder))
    else:
        trim_working_set()

    # Main thread event dispatch loop
    while _main_running:
        try:
            cmd, arg = _gui_cmd_queue.get(timeout=0.25)
            if cmd == "open" and _main_running:
                run_gui_window(initial_folder=arg)
            elif cmd == "sort":
                sort_now(silent=True)
            elif cmd == "toggle":
                if _is_watching:
                    stop_watching()
                else:
                    start_watching(silent=True)
            elif cmd == "quit":
                break
        except queue.Empty:
            continue
        except Exception:
            pass

    # Clean shutdown
    stop_watching()
    if _tray:
        _tray.stop()
    _executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
