"""User settings and the folder where the app keeps its data (scan history, .env, settings.json).

A one-file PyInstaller exe unpacks itself into a temp folder on every start, so data must not live next to the
code: on Windows it goes to %LOCALAPPDATA%\\DustyAi (override with the DUSTYAI_DATA environment variable)."""
import json
import os
import threading

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    custom = os.environ.get("DUSTYAI_DATA")
    if custom:
        return custom
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "DustyAi")
    return APP_DIR  # development on Linux/macOS: keep everything in the project folder


DATA_DIR = _data_dir()
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULTS = {
    "theme": "system",       # system | light | dark
    "zoom": 100,             # interface scale, percent
    "native_frame": False,   # use the system title bar instead of the custom one (needs a restart)
    "scan_deep": True,       # defaults of the checkboxes on the home page
    "scan_profile": True,
    "scan_dups": True,
    "history_keep": 20,      # how many scans to keep
}
ZOOM_STEPS = [70, 80, 90, 100, 110, 125, 150, 175, 200]
HISTORY_CHOICES = [5, 10, 20, 50]

_lock = threading.Lock()


def _clean(key, value):
    """Validated value, or None if it is not acceptable for this key."""
    if key == "theme":
        return value if value in ("system", "light", "dark") else None
    if key == "zoom":
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and int(value) in ZOOM_STEPS else None
    if key == "history_keep":
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and int(value) in HISTORY_CHOICES else None
    if key in ("native_frame", "scan_deep", "scan_profile", "scan_dups"):
        return value if isinstance(value, bool) else None
    return None


def load():
    out = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        for k in DEFAULTS:
            v = _clean(k, raw.get(k)) if isinstance(raw, dict) else None
            if v is not None:
                out[k] = v
    except (OSError, ValueError):
        pass
    return out


def update(changes):
    """Merges the valid part of `changes` into the stored settings; returns (settings, rejected_keys)."""
    with _lock:
        cur = load()
        rejected = []
        for k, v in (changes or {}).items():
            c = _clean(k, v) if k in DEFAULTS else None
            if c is None:
                rejected.append(k)
            else:
                cur[k] = c
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2)
        except OSError:
            rejected.append("(could not save)")
        return cur, rejected
