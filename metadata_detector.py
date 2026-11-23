"""
LellaVerse Smart Organizer - Metadata & Source App Detector
Accurately identifies origin applications, cameras, recorders, and creative tools
from filenames, EXIF metadata, container headers, and document properties.
"""

import os
import re
import io
import struct
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, Tuple, NamedTuple

try:
    from PIL import Image, ExifTags
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class OriginInfo(NamedTuple):
    app_name: str           # e.g., "WhatsApp", "Instagram", "Screenshots", "Camera (Apple iPhone)"
    category_hint: str      # e.g., "Images", "Media", "Documents"
    subfolder: str          # e.g., "WhatsApp", "Instagram", "Screenshots", "Camera Photos"
    capture_date: Optional[datetime]
    details: str            # e.g., "WhatsApp media pattern", "EXIF: Apple iPhone 14 Pro"


# ----------------------------------------------------------------------------
# Known Regex Patterns
# ----------------------------------------------------------------------------
RE_WHATSAPP_MEDIA = re.compile(r"^(?:img|vid|aud|ptt|stk|doc)[-_](\d{8})[-_]wa\d+", re.IGNORECASE)
RE_WHATSAPP_VERBAL = re.compile(r"^whatsapp\s+(?:image|video|audio|document|voice\s*note|sticker)\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
RE_TELEGRAM_MEDIA = re.compile(r"^(?:photo|video|audio|file)[-_](\d{4}-\d{2}-\d{2})", re.IGNORECASE)
RE_TELEGRAM_CLOUD = re.compile(r"^telegram[-_]cloud", re.IGNORECASE)
RE_INSTAGRAM_CDN = re.compile(r"^\d{7,12}_\d{14,20}_\d+_n\.", re.IGNORECASE)
RE_INSTAGRAM_PREFIX = re.compile(r"^(?:instagram|instasave|ig|reels?|story)[-_]", re.IGNORECASE)
RE_TIKTOK_PREFIX = re.compile(r"^(?:tiktok|snaptik|ssstik|musically|tt)[-_]", re.IGNORECASE)
RE_TIKTOK_CDN = re.compile(r"^v\d{4,}[a-z0-9_]{6,}\.mp4$", re.IGNORECASE)
RE_SNAPCHAT = re.compile(r"^snapchat[-_]", re.IGNORECASE)
RE_FACEBOOK_IMG = re.compile(r"^fb_img_(\d+)", re.IGNORECASE)
RE_MESSENGER_CREATION = re.compile(r"^messenger_creation_(\d+)", re.IGNORECASE)
RE_RECEIVED_FILE = re.compile(r"^received_\d+", re.IGNORECASE)
RE_TWITTER_X = re.compile(r"^(?:twitter|tweet|x)[-_]\d+", re.IGNORECASE)

# Screenshots
RE_SCREENSHOT_GENERIC = re.compile(
    r"^(?:screenshot|screen\s*shot|capture|captures|screen_?recording|screen_?shot|quickmemo|screencast)[-_ ]",
    re.IGNORECASE
)
RE_SCREENSHOT_WIN = re.compile(r"^screenshot\s*\(\d+\)\.png$", re.IGNORECASE)
RE_SCREENSHOT_ANDROID = re.compile(r"^screenshot_(\d{8})[-_](\d{6})", re.IGNORECASE)
RE_SCREENSHOT_MACOS = re.compile(r"^screen\s*shot\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

# Screen Recorders
RE_OBS_RECORDING = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}-\d{2}-\d{2})\.mp4$", re.IGNORECASE)
RE_SHADOWPLAY = re.compile(r"^desktop\s*(\d{4}\.\d{2}\.\d{2})", re.IGNORECASE)
RE_BANDICAM = re.compile(r"^bandicam\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
RE_ZOOM = re.compile(r"^zoom_\d+\.mp4$", re.IGNORECASE)
RE_LOOM = re.compile(r"^loom\s*recording", re.IGNORECASE)
RE_MEET = re.compile(r"^meet\s*-\s*", re.IGNORECASE)

# Camera filename patterns
RE_PIXEL_CAMERA = re.compile(r"^pxl_(\d{8})_(\d{6})", re.IGNORECASE)
RE_SAMSUNG_CAMERA = re.compile(r"^(\d{8})_(\d{6})\.(?:jpg|jpeg|mp4)$", re.IGNORECASE)
RE_APPLE_CAMERA = re.compile(r"^img_\d{4}\.(?:jpg|jpeg|heic|mov|dng)$", re.IGNORECASE)
RE_SONY_NIKON = re.compile(r"^(?:dsc[0-9_]|dscn\d+)", re.IGNORECASE)
RE_GOPRO = re.compile(r"^(?:gopr|gp\d+)\d+", re.IGNORECASE)
RE_DJI = re.compile(r"^dji[-_]\d+", re.IGNORECASE)
RE_PANO = re.compile(r"^pano_(\d{8})", re.IGNORECASE)
RE_MVIMG = re.compile(r"^mvimg_(\d{8})", re.IGNORECASE)


def parse_date_str(s: str) -> Optional[datetime]:
    """Tries parsing various date strings like 20231015, 2023-10-15."""
    clean = re.sub(r"[^0-9]", "", s)
    if len(clean) >= 8:
        try:
            return datetime.strptime(clean[:8], "%Y%m%d")
        except ValueError:
            pass
    return None


# ----------------------------------------------------------------------------
# EXIF Reader for Images
# ----------------------------------------------------------------------------
def inspect_image_metadata(file_path: str) -> Tuple[Optional[str], Optional[str], Optional[datetime], str]:
    """
    Inspects image EXIF & metadata via Pillow.
    Returns: (camera_app_origin, software_tool, capture_date, details)
    """
    if not PIL_AVAILABLE:
        return None, None, None, ""

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".heic"}:
        return None, None, None, ""

    try:
        with Image.open(file_path) as im:
            # Check PNG textual chunks
            if ext == ".png":
                text = getattr(im, "text", {}) or {}
                for k, v in text.items():
                    val = str(v).lower()
                    if "canva" in val:
                        return None, "Canva", None, "PNG text: Canva"
                    if "figma" in val:
                        return None, "Figma", None, "PNG text: Figma"
                    if "photoshop" in val:
                        return None, "Adobe Photoshop", None, "PNG text: Photoshop"
                    if "screenshot" in val:
                        return "Screenshots", None, None, "PNG text: Screenshot"

            # Check EXIF
            exif_raw = im.getexif()
            if not exif_raw:
                return None, None, None, ""

            # Map tag names
            exif = {}
            for tag_id, val in exif_raw.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                exif[tag_name] = str(val).strip()

            make = exif.get("Make", "")
            model = exif.get("Model", "")
            software = exif.get("Software", "")
            dt_str = exif.get("DateTimeOriginal") or exif.get("DateTime")

            capture_date = None
            if dt_str:
                try:
                    # Standard EXIF format: 'YYYY:MM:DD HH:MM:SS'
                    parts = dt_str.split(" ")[0].replace("-", ":").split(":")
                    if len(parts) >= 3:
                        capture_date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                except Exception:
                    pass

            # Detect Software
            software_app = None
            sw_lower = software.lower()
            if "photoshop" in sw_lower:
                software_app = "Adobe Photoshop"
            elif "lightroom" in sw_lower:
                software_app = "Adobe Lightroom"
            elif "canva" in sw_lower:
                software_app = "Canva"
            elif "snapseed" in sw_lower:
                software_app = "Snapseed"
            elif "vsco" in sw_lower:
                software_app = "VSCO"
            elif "gimp" in sw_lower:
                software_app = "GIMP"
            elif "procreate" in sw_lower:
                software_app = "Procreate"
            elif "capcut" in sw_lower:
                software_app = "CapCut"
            elif "inshot" in sw_lower:
                software_app = "InShot"
            elif "whatsapp" in sw_lower:
                software_app = "WhatsApp"

            # Detect Camera Make & Model
            camera_origin = None
            comb = f"{make} {model}".strip()
            comb_lower = comb.lower()
            if "apple" in comb_lower or "iphone" in comb_lower:
                camera_origin = "Camera (Apple iPhone)"
            elif "samsung" in comb_lower:
                camera_origin = "Camera (Samsung Galaxy)"
            elif "pixel" in comb_lower or "google" in comb_lower:
                camera_origin = "Camera (Google Pixel)"
            elif any(b in comb_lower for b in ["xiaomi", "redmi", "poco"]):
                camera_origin = "Camera (Xiaomi)"
            elif "sony" in comb_lower:
                camera_origin = "Camera (Sony)"
            elif "canon" in comb_lower:
                camera_origin = "Camera (Canon)"
            elif "nikon" in comb_lower:
                camera_origin = "Camera (Nikon)"
            elif "dji" in comb_lower:
                camera_origin = "Camera (DJI Drone)"
            elif "gopro" in comb_lower:
                camera_origin = "Camera (GoPro)"
            elif make or model:
                camera_origin = f"Camera ({comb[:24]})"

            details = []
            if camera_origin:
                details.append(f"EXIF: {comb}")
            if software_app:
                details.append(f"Tool: {software_app}")

            return camera_origin, software_app, capture_date, "; ".join(details)
    except Exception:
        return None, None, None, ""


# ----------------------------------------------------------------------------
# Container / Header Reader for Videos (MP4 / MOV / MKV)
# ----------------------------------------------------------------------------
def inspect_video_headers(file_path: str) -> Tuple[Optional[str], str]:
    """Fast streaming scan of initial and trailing 64KB chunks for encoder signatures (ftyp/moov/udta atoms)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
        return None, ""

    try:
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            chunk = f.read(65536)
            # If large file, also read the tail where moov/udta atoms often live
            if size > 131072:
                f.seek(-65536, os.SEEK_END)
                chunk += b" " + f.read(65536)

            if not chunk:
                return None, ""

            chunk_lower = chunk.lower()
            if b"capcut" in chunk_lower:
                return "CapCut", "Video tag: CapCut"
            if b"inshot" in chunk_lower:
                return "InShot", "Video tag: InShot"
            if b"premiere" in chunk_lower or b"adobe" in chunk_lower:
                return "Adobe Premiere", "Video tag: Adobe Premiere"
            if b"handbrake" in chunk_lower:
                return "HandBrake", "Video tag: HandBrake"
            if b"obs" in chunk_lower or b"open broadcaster" in chunk_lower:
                return "OBS Studio", "Video tag: OBS Studio"
            if b"quicktime" in chunk_lower and (b"apple" in chunk_lower or b"iphone" in chunk_lower):
                return "Apple iPhone", "Video tag: Apple QuickTime"
            if b"tiktok" in chunk_lower or b"bytedance" in chunk_lower or b"musical.ly" in chunk_lower:
                return "TikTok", "Video tag: ByteDance/TikTok"
            if b"whatsapp" in chunk_lower:
                return "WhatsApp", "Video tag: WhatsApp"
    except Exception:
        pass
    return None, ""


# ----------------------------------------------------------------------------
# Document Metadata Reader (PDF & Office)
# ----------------------------------------------------------------------------
def inspect_document_metadata(file_path: str) -> Tuple[Optional[str], str]:
    """Streaming inspection of documents (reads only 64KB chunks; never buffers full files)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            size = os.path.getsize(file_path)
            with open(file_path, "rb") as f:
                chunk = f.read(65536)
                if size > 131072:
                    f.seek(-65536, os.SEEK_END)
                    chunk += b" " + f.read(65536)
                chunk_str = chunk.decode("latin1", errors="ignore")
                for marker in ["/Producer", "/Creator"]:
                    idx = chunk_str.find(marker)
                    if idx != -1:
                        val = chunk_str[idx:idx+120].lower()
                        if "canva" in val:
                            return "Canva", "PDF Creator: Canva"
                        if "figma" in val:
                            return "Figma", "PDF Creator: Figma"
                        if "word" in val:
                            return "Microsoft Word", "PDF Creator: Microsoft Word"
                        if "google docs" in val or "skia/pdf" in val:
                            return "Google Docs", "PDF Creator: Google Docs"
                        if "adobe" in val or "acrobat" in val or "indesign" in val:
                            return "Adobe Creative", "PDF Creator: Adobe"
        except Exception:
            pass

    elif ext in {".docx", ".xlsx", ".pptx"}:
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                if "docProps/app.xml" in z.namelist():
                    data = z.read("docProps/app.xml")
                    root = ET.fromstring(data)
                    for elem in root.iter():
                        if elem.tag.endswith("Application") and elem.text:
                            app_str = elem.text.lower()
                            if "word" in app_str:
                                return "Microsoft Word", f"Office App: {elem.text}"
                            if "excel" in app_str:
                                return "Microsoft Excel", f"Office App: {elem.text}"
                            if "powerpoint" in app_str:
                                return "Microsoft PowerPoint", f"Office App: {elem.text}"
                            if "google" in app_str:
                                return "Google Docs", f"Office App: {elem.text}"
                            return elem.text.strip(), f"Office App: {elem.text}"
        except Exception:
            pass

    return None, ""


# ----------------------------------------------------------------------------
# Master Origin Detector
# ----------------------------------------------------------------------------
def detect_file_origin(file_path: str) -> Optional[OriginInfo]:
    """
    Main entry point: Inspects a file and identifies its origin app / creator.
    Returns OriginInfo or None.
    """
    if not os.path.exists(file_path):
        return None

    filename = os.path.basename(file_path)
    fn_lower = filename.lower()
    ext = os.path.splitext(filename)[1].lower()

    # 1. WhatsApp
    m = RE_WHATSAPP_MEDIA.match(fn_lower)
    if m:
        dt = parse_date_str(m.group(1))
        return OriginInfo("WhatsApp", "Social & Messaging", "WhatsApp", dt, "WhatsApp media signature")
    m2 = RE_WHATSAPP_VERBAL.match(fn_lower)
    if m2:
        dt = parse_date_str(m2.group(1))
        return OriginInfo("WhatsApp", "Social & Messaging", "WhatsApp", dt, "WhatsApp export naming")
    if "whatsapp" in fn_lower:
        return OriginInfo("WhatsApp", "Social & Messaging", "WhatsApp", None, "WhatsApp in filename")

    # 2. Telegram
    m = RE_TELEGRAM_MEDIA.match(fn_lower)
    if m:
        dt = parse_date_str(m.group(1))
        return OriginInfo("Telegram", "Social & Messaging", "Telegram", dt, "Telegram media signature")
    if RE_TELEGRAM_CLOUD.match(fn_lower) or "telegram" in fn_lower:
        return OriginInfo("Telegram", "Social & Messaging", "Telegram", None, "Telegram cloud file")

    # 3. Instagram
    if RE_INSTAGRAM_PREFIX.match(fn_lower) or RE_INSTAGRAM_CDN.match(fn_lower) or "instagram" in fn_lower or "instasave" in fn_lower:
        return OriginInfo("Instagram", "Social & Messaging", "Instagram", None, "Instagram pattern")

    # 4. TikTok
    if RE_TIKTOK_PREFIX.match(fn_lower) or RE_TIKTOK_CDN.match(fn_lower) or any(k in fn_lower for k in ["tiktok", "snaptik", "ssstik", "musically"]):
        return OriginInfo("TikTok", "Social & Messaging", "TikTok", None, "TikTok downloader / signature")

    # 5. Snapchat
    if RE_SNAPCHAT.match(fn_lower) or "snapchat" in fn_lower:
        return OriginInfo("Snapchat", "Social & Messaging", "Snapchat", None, "Snapchat export")

    # 6. Facebook & Messenger
    if RE_FACEBOOK_IMG.match(fn_lower) or RE_MESSENGER_CREATION.match(fn_lower) or "facebook" in fn_lower or "messenger" in fn_lower or RE_RECEIVED_FILE.match(fn_lower):
        return OriginInfo("Facebook & Messenger", "Social & Messaging", "Facebook & Messenger", None, "Facebook/Messenger pattern")

    # 7. Twitter / X
    if RE_TWITTER_X.match(fn_lower) or "twitter" in fn_lower:
        return OriginInfo("Twitter (X)", "Social & Messaging", "Twitter", None, "Twitter export")

    # 8. Screenshots
    if (RE_SCREENSHOT_WIN.match(fn_lower) or RE_SCREENSHOT_GENERIC.match(fn_lower) or
        "screenshot" in fn_lower or "screen shot" in fn_lower or "screen_shot" in fn_lower or
        RE_SCREENSHOT_ANDROID.match(fn_lower) or RE_SCREENSHOT_MACOS.match(fn_lower)):
        dt = None
        m_and = RE_SCREENSHOT_ANDROID.match(fn_lower)
        if m_and:
            dt = parse_date_str(m_and.group(1))
        return OriginInfo("Screenshots", "Screenshots", "Screenshots", dt, "Screenshot pattern")

    # 9. Screen Recordings
    m_obs = RE_OBS_RECORDING.match(filename)
    if m_obs:
        dt = parse_date_str(m_obs.group(1))
        return OriginInfo("Screen Recordings (OBS)", "Media", "Screen Recordings", dt, "OBS Studio recording")
    m_sp = RE_SHADOWPLAY.match(fn_lower)
    if m_sp:
        dt = parse_date_str(m_sp.group(1))
        return OriginInfo("Screen Recordings (ShadowPlay)", "Media", "Screen Recordings", dt, "Nvidia ShadowPlay")
    if RE_BANDICAM.match(fn_lower):
        return OriginInfo("Screen Recordings (Bandicam)", "Media", "Screen Recordings", None, "Bandicam")
    if RE_ZOOM.match(fn_lower) or "zoom_" in fn_lower:
        return OriginInfo("Zoom Recordings", "Media", "Screen Recordings", None, "Zoom meeting recording")
    if RE_LOOM.match(fn_lower):
        return OriginInfo("Loom Recordings", "Media", "Screen Recordings", None, "Loom screen recording")
    if RE_MEET.match(fn_lower):
        return OriginInfo("Google Meet Recordings", "Media", "Screen Recordings", None, "Google Meet recording")

    # 10. Filename-based Camera patterns
    m_pxl = RE_PIXEL_CAMERA.match(fn_lower)
    if m_pxl:
        dt = parse_date_str(m_pxl.group(1))
        return OriginInfo("Camera (Google Pixel)", "Images", "Camera Photos", dt, "Google Pixel camera signature")
    m_sam = RE_SAMSUNG_CAMERA.match(fn_lower)
    if m_sam:
        dt = parse_date_str(m_sam.group(1))
        return OriginInfo("Camera (Samsung)", "Images", "Camera Photos", dt, "Samsung camera signature")
    if RE_APPLE_CAMERA.match(fn_lower):
        return OriginInfo("Camera (Apple iPhone)", "Images", "Camera Photos", None, "Apple camera signature")
    if RE_SONY_NIKON.match(fn_lower):
        return OriginInfo("Camera Photos", "Images", "Camera Photos", None, "Digital camera signature")
    if RE_GOPRO.match(fn_lower):
        return OriginInfo("GoPro Action Camera", "Media", "Camera Photos", None, "GoPro camera signature")
    if RE_DJI.match(fn_lower):
        return OriginInfo("DJI Drone Camera", "Media", "Camera Photos", None, "DJI drone signature")
    if RE_PANO.match(fn_lower) or RE_MVIMG.match(fn_lower):
        return OriginInfo("Camera Photos", "Images", "Camera Photos", None, "Smartphone photo signature")

    # 11. Deep EXIF Inspection for Images
    cam, tool, cap_dt, details = inspect_image_metadata(file_path)
    if tool:
        # Software tool took precedence (e.g. Photoshop, Canva, Snapseed)
        return OriginInfo(tool, "Creative & Design", tool, cap_dt, details)
    if cam:
        return OriginInfo(cam, "Images", "Camera Photos", cap_dt, details)

    # 12. Deep Container Inspection for Videos
    v_tool, v_details = inspect_video_headers(file_path)
    if v_tool:
        cat = "Social & Messaging" if v_tool in {"WhatsApp", "TikTok"} else "Media"
        sub = "TikTok" if v_tool == "TikTok" else ("WhatsApp Videos" if v_tool == "WhatsApp" else v_tool)
        return OriginInfo(v_tool, cat, sub, None, v_details)

    # 13. Deep Document Inspection for PDF / Office
    doc_tool, doc_details = inspect_document_metadata(file_path)
    if doc_tool:
        return OriginInfo(doc_tool, "Documents", doc_tool, None, doc_details)

    # 14. Creative file extensions
    if ext in {".psd", ".psb"}:
        return OriginInfo("Adobe Photoshop", "Creative & Design", "Photoshop", None, "Photoshop document")
    if ext in {".ai", ".eps"}:
        return OriginInfo("Adobe Illustrator", "Creative & Design", "Illustrator", None, "Illustrator vector")
    if ext in {".prproj", ".aep"}:
        return OriginInfo("Adobe Video Project", "Creative & Design", "Video Projects", None, "Adobe project")
    if ext in {".blend", ".blend1"}:
        return OriginInfo("Blender 3D", "Creative & Design", "Blender", None, "Blender 3D scene")

    return None


def get_smart_file_date(file_path: str, origin: Optional[OriginInfo] = None) -> datetime:
    """
    Returns the best possible date for the file:
    1. True capture/creation date from EXIF or filename (if available)
    2. Filesystem creation time (Windows arrival date)
    3. Filesystem modification time
    """
    if origin and origin.capture_date:
        return origin.capture_date

    try:
        st = os.stat(file_path)
        # Windows creation time is st_ctime
        ts = st.st_ctime if os.name == "nt" else getattr(st, "st_birthtime", st.st_mtime)
        return datetime.fromtimestamp(ts)
    except Exception:
        return datetime.now()
