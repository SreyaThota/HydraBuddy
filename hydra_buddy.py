"""
HydraBuddy - your offline eye & body break buddy.

Every 20 minutes (you can change this) a friendly pop-up appears in the middle
of your screen and reminds you to:
    1. Drink water
    2. Look far away for 20 seconds
    3. Stand up, stretch, and sit back comfortably

How to run (in PowerShell, inside this folder):
    py hydra_buddy.py              normal mode
    py hydra_buddy.py --test       test mode (a reminder every 30 seconds)

Personalise it with the controls in the main window, or by editing
settings.json (see README.md).

Everything works offline and uses only Python's built-in libraries.
The system-tray icon is optional: it appears only if "pystray" and "Pillow"
are installed (py -m pip install -r requirements-optional.txt).
"""

import argparse
import array
import copy
import faulthandler
import ctypes
import io
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import wave
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, ttk

# ---------------------------------------------------------------------------
# Files and fixed values
# ---------------------------------------------------------------------------
APP_NAME = "HydraBuddy"
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"        # your personal settings
LOG_FILE = APP_DIR / "hydra_buddy.log"           # errors are written here
CUSTOM_SOUND_FILE = APP_DIR / "reminder.wav"     # optional: your own sound
STARTUP_SHORTCUT_NAME = "HydraBuddy.lnk"         # old start-up method (removed when upgrading)
TASK_NAME = "HydraBuddy"                         # Task Scheduler: starts it when you sign in
KEEPALIVE_SUFFIX = "-KeepAlive"                  # Task Scheduler: restarts it on unlock / every 15 min
KEEPALIVE_MINUTES = 15
EXIT_FLAG_FILE = APP_DIR / ".exited-by-user"     # remembers that you clicked Exit (until next sign-in)
HANG_SECONDS = 60                                # frozen this long = restart automatically

TEST_INTERVAL_SECONDS = 30     # interval used with --test
TEST_SNOOZE_SECONDS = 10       # snooze used with --test
TOAST_SECONDS = 4              # how long the small corner message stays
SLEEP_GAP_SECONDS = 60         # a pause this long in the timer loop means the laptop slept
MAX_LOG_BYTES = 200_000        # the log file is restarted when it gets bigger than this
INTERVAL_CHOICES = [10, 15, 20, 30, 45, 60]      # minutes offered in the main window

# This exact colour is made see-through, which gives the pop-up round corners.
TRANSPARENT_KEY = "#ff00fe"

# ---------------------------------------------------------------------------
# Default settings. settings.json only needs the values you want to change.
# "{seconds}" in a reminder is replaced with eye_break_seconds.
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "interval_minutes": 20,
    "snooze_enabled": True,
    "snooze_minutes": 5,
    "eye_break_seconds": 20,
    "sound_enabled": True,
    "sound_volume": 0.6,
    "theme": "cute",
    "show_mascot": True,
    "mascot_image": "",
    "heading": "Hey! Time for a little self-care",
    "subheading": "Take care of your eyes & body",
    "closing_message": "Your eyes and body deserve a break!",
    "reminders": {
        "water": {
            "enabled": True,
            "title": "Drink Water",
            "text": "Take a few sips of water. Stay hydrated.",
        },
        "look_far": {
            "enabled": True,
            "title": "Look Far — {seconds} Seconds",
            "text": "Look at something about 20 feet (6 metres) away. Relax your eyes and blink normally.",
        },
        "move": {
            "enabled": True,
            "title": "Stand & Sit",
            "text": "Stand up, stretch gently and move a little. Sit back comfortably when you are ready.",
        },
    },
    "colors": {},
}

# Allowed ranges for number settings: (smallest, largest)
NUMBER_LIMITS = {
    "interval_minutes": (1, 240),
    "snooze_minutes": (1, 60),
    "eye_break_seconds": (5, 120),
    "sound_volume": (0.0, 1.0),
}

REMINDER_ORDER = ["water", "look_far", "move"]

# ---------------------------------------------------------------------------
# Themes. Any colour can be overridden with "colors" in settings.json.
# ---------------------------------------------------------------------------
THEMES = {
    "cute": {
        "bg": "#fffaf3", "border": "#f2d4b8", "ink": "#2f2a3b", "ink_soft": "#5f566e",
        "pill": "#ffe58a", "pill_text": "#2f2a3b", "heart": "#f0648c",
        "heading_font": "Segoe Print", "body_font": "Segoe UI",
        "primary": "#7c5ce0", "primary_hover": "#6a49d1", "primary_text": "#ffffff",
        "secondary": "#ebe7f2", "secondary_hover": "#ddd6ea", "secondary_text": "#2f2a3b",
        "eye": "#2fb36b", "eye_hover": "#279a5b", "eye_text": "#ffffff",
        "status_bg": "#efe8fb", "status_text": "#4b3399", "close_bg": "#f3ece4",
        "water_bg": "#dff0ff", "water_icon": "#3aa0f0", "water_title": "#1d5f9e",
        "look_far_bg": "#ddf5e6", "look_far_icon": "#2fb36b", "look_far_title": "#1b6e42",
        "move_bg": "#ece3fb", "move_icon": "#8a5cd6", "move_title": "#56339e",
    },
    "minimal": {
        "bg": "#ffffff", "border": "#e3e3e3", "ink": "#1f1f1f", "ink_soft": "#666666",
        "pill": "#f2f2f2", "pill_text": "#1f1f1f", "heart": "#1f1f1f",
        "heading_font": "Segoe UI Semibold", "body_font": "Segoe UI",
        "primary": "#1f1f1f", "primary_hover": "#3a3a3a", "primary_text": "#ffffff",
        "secondary": "#f0f0f0", "secondary_hover": "#e2e2e2", "secondary_text": "#1f1f1f",
        "eye": "#555555", "eye_hover": "#444444", "eye_text": "#ffffff",
        "status_bg": "#f4f4f4", "status_text": "#1f1f1f", "close_bg": "#f0f0f0",
        "water_bg": "#f6f6f6", "water_icon": "#3d3d3d", "water_title": "#1f1f1f",
        "look_far_bg": "#f6f6f6", "look_far_icon": "#3d3d3d", "look_far_title": "#1f1f1f",
        "move_bg": "#f6f6f6", "move_icon": "#3d3d3d", "move_title": "#1f1f1f",
    },
    "dark": {
        "bg": "#1e2130", "border": "#33384d", "ink": "#eef0f7", "ink_soft": "#a9aec4",
        "pill": "#ffd166", "pill_text": "#1e2130", "heart": "#ff7aa2",
        "heading_font": "Segoe UI Semibold", "body_font": "Segoe UI",
        "primary": "#8b6cf0", "primary_hover": "#9d83f3", "primary_text": "#ffffff",
        "secondary": "#2c3044", "secondary_hover": "#373c54", "secondary_text": "#eef0f7",
        "eye": "#2a9d63", "eye_hover": "#31b070", "eye_text": "#ffffff",
        "status_bg": "#2a2e42", "status_text": "#cdb8ff", "close_bg": "#2c3044",
        "water_bg": "#1f3550", "water_icon": "#3aa0f0", "water_title": "#9fd2ff",
        "look_far_bg": "#1d3b2e", "look_far_icon": "#2fb36b", "look_far_title": "#9ee6bf",
        "move_bg": "#30284a", "move_icon": "#8a5cd6", "move_title": "#cdb8ff",
    },
    "productivity": {
        "bg": "#f7f9fc", "border": "#d8e1ef", "ink": "#0f172a", "ink_soft": "#475569",
        "pill": "#dbeafe", "pill_text": "#1e3a8a", "heart": "#2563eb",
        "heading_font": "Segoe UI Semibold", "body_font": "Segoe UI",
        "primary": "#2563eb", "primary_hover": "#1d4ed8", "primary_text": "#ffffff",
        "secondary": "#e2e8f0", "secondary_hover": "#cbd5e1", "secondary_text": "#0f172a",
        "eye": "#0d9488", "eye_hover": "#0f766e", "eye_text": "#ffffff",
        "status_bg": "#e8eef8", "status_text": "#1e3a8a", "close_bg": "#e2e8f0",
        "water_bg": "#e0efff", "water_icon": "#2563eb", "water_title": "#1e40af",
        "look_far_bg": "#dcf5ef", "look_far_icon": "#0d9488", "look_far_title": "#115e59",
        "move_bg": "#ece9fe", "move_icon": "#6d28d9", "move_title": "#4c1d95",
    },
}
COLOR_KEYS = set(THEMES["cute"]) - {"heading_font", "body_font"}

# The tray icon needs two optional packages. If they are missing, the app
# still works - it just minimises to the taskbar instead of the tray.
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Settings: load, check and save settings.json
# ---------------------------------------------------------------------------
def validate_settings(raw, problems):
    """Combine the user's values with the defaults.

    Every value is checked. Anything wrong is replaced by its default, and a
    plain-English explanation is added to `problems`, so a typo never stops
    the app from starting.
    """
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in raw.items():
        if key.startswith("_"):
            continue                                  # "_comment" keys are allowed
        if key not in DEFAULT_SETTINGS:
            problems.append(f'Unknown setting "{key}" was ignored.')
            continue
        default = DEFAULT_SETTINGS[key]
        if key == "reminders":
            _validate_reminders(value, settings, problems)
        elif key == "colors":
            if isinstance(value, dict):
                for name, color in value.items():
                    if name in COLOR_KEYS and isinstance(color, str):
                        settings["colors"][name] = color
                    else:
                        problems.append(f'Unknown colour "{name}" was ignored.')
            else:
                problems.append('"colors" must look like {"primary": "#ff6699"}.')
        elif isinstance(default, bool):
            if isinstance(value, bool):
                settings[key] = value
            else:
                problems.append(f'"{key}" must be true or false.')
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                low, high = NUMBER_LIMITS[key]
                fixed = min(high, max(low, value))
                if fixed != value:
                    problems.append(f'"{key}" must be between {low} and {high}; using {fixed}.')
                settings[key] = int(round(fixed)) if isinstance(default, int) else float(fixed)
            else:
                problems.append(f'"{key}" must be a number.')
        elif isinstance(value, str):
            settings[key] = value
        else:
            problems.append(f'"{key}" must be text in "quotes".')

    if settings["theme"] not in THEMES:
        problems.append(f'Theme "{settings["theme"]}" does not exist. '
                        f'Choose one of: {", ".join(THEMES)}.')
        settings["theme"] = DEFAULT_SETTINGS["theme"]
    if not any(r["enabled"] for r in settings["reminders"].values()):
        problems.append("All reminders were switched off, so all three were switched back on.")
        for r in settings["reminders"].values():
            r["enabled"] = True
    return settings


def _validate_reminders(value, settings, problems):
    if not isinstance(value, dict):
        problems.append('"reminders" has the wrong format; using the default reminders.')
        return
    for rid, fields in value.items():
        if rid not in settings["reminders"]:
            problems.append(f'Unknown reminder "{rid}" was ignored (use water, look_far or move).')
            continue
        if not isinstance(fields, dict):
            problems.append(f'Reminder "{rid}" has the wrong format.')
            continue
        target = settings["reminders"][rid]
        for field, v in fields.items():
            if field == "enabled" and isinstance(v, bool):
                target["enabled"] = v
            elif field in ("title", "text") and isinstance(v, str):
                target[field] = v
            else:
                problems.append(f'Reminder "{rid}": "{field}" was ignored (wrong name or type).')


def load_settings(path=None):
    """Read settings.json. Returns (settings, problems)."""
    path = Path(path) if path else SETTINGS_FILE
    problems = []
    raw = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("the file must contain one { ... } block")
        except (OSError, ValueError) as exc:
            problems.append(f"Could not read {path.name} ({exc}). Using default settings.")
            raw = {}
    return validate_settings(raw, problems), problems


def save_settings(settings, path=None):
    """Write settings.json safely (to a temporary file first, then swap)."""
    path = Path(path) if path else SETTINGS_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def reminder_text(settings, rid, field):
    """A reminder's title or text, with {seconds} filled in."""
    return settings["reminders"][rid][field].replace("{seconds}", str(settings["eye_break_seconds"]))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def log_error(text):
    """Write errors to hydra_buddy.log (useful when running without a console)."""
    try:
        mode = "a"
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            mode = "w"                                # start a fresh log
        with open(LOG_FILE, mode, encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass
    if sys.stderr:
        print(text, file=sys.stderr)


def nice_duration(seconds, short=False):
    """Turn 1200 into '20 minutes' (or '20 min' when short=True)."""
    seconds = int(round(seconds))
    if seconds >= 60 and seconds % 60 == 0:
        n = seconds // 60
        unit = "min" if short else ("minute" if n == 1 else "minutes")
    else:
        n = seconds
        unit = "sec" if short else ("second" if n == 1 else "seconds")
    return f"{n} {unit}"


def format_countdown(seconds):
    """Turn 75.2 seconds into '01:16' (rounded up, so it never shows 00:00 early)."""
    total = int(math.ceil(max(0.0, seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def enable_dpi_awareness():
    """Make text sharp on high-resolution (scaled) Windows displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def get_work_area(root):
    """Screen area without the taskbar, as (left, top, right, bottom)."""
    try:
        rect = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def is_screen_locked():
    """Return True while the Windows lock screen is showing.

    When the laptop is locked, Windows doesn't let apps open the input
    desktop, so a failed OpenInputDesktop call means "locked".
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        DESKTOP_SWITCHDESKTOP = 0x0100
        handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not handle:
            return True
        user32.CloseDesktop(handle)
        return False
    except Exception:
        return False


def make_chime_wav(volume=0.6):
    """Create a gentle "ding-ding-ding" chime and return it as .wav file bytes.

    Three soft bell notes going up (C, E, G). The sound is calculated with
    maths, so no sound file or internet is needed.
    """
    rate = 22050                                               # samples per second
    notes = [(1046.5, 0.00), (1318.5, 0.16), (1568.0, 0.32)]   # (pitch in Hz, start time)
    samples = [0.0] * int(rate * 1.5)
    for freq, start in notes:
        first = int(start * rate)
        for i in range(len(samples) - first):
            t = i / rate
            fade = min(1.0, t / 0.01) * math.exp(-4.5 * t)    # quick start, slow fade out
            bell = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(2 * math.pi * 2 * freq * t)
            samples[first + i] += fade * bell
    peak = max(abs(x) for x in samples) or 1.0
    volume = max(0.0, min(1.0, volume))
    pcm = array.array("h", (int(x / peak * volume * 32767) for x in samples))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


_chime_cache = {}    # volume -> wav bytes, so the chime is only calculated once


def play_reminder_sound(volume=0.6):
    """Play the reminder sound without freezing the window.

    Windows also applies your laptop's volume, so muting the laptop
    silences the chime.
    """
    try:
        import winsound
    except ImportError:
        return                                                 # not on Windows
    try:
        if CUSTOM_SOUND_FILE.exists():
            winsound.PlaySound(str(CUSTOM_SOUND_FILE), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        if volume not in _chime_cache:
            _chime_cache[volume] = make_chime_wav(volume)
        chime = _chime_cache[volume]

        def play():
            try:
                winsound.PlaySound(chime, winsound.SND_MEMORY)
            except Exception as exc:
                log_error(f"Could not play sound: {exc}")

        # Sounds held in memory can't play "async", so play it on a helper thread.
        threading.Thread(target=play, daemon=True).start()
    except Exception as exc:
        log_error(f"Could not play sound: {exc}")


# Keeps the single-instance lock alive while the app runs.
_instance_mutex = None


def acquire_single_instance():
    """Return True if this is the only HydraBuddy running, False otherwise.

    Uses a named Windows "mutex": the second copy of the app sees that the
    name is already taken and knows another HydraBuddy is open.
    """
    global _instance_mutex
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, "Local\\HydraBuddy_SingleInstance")
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _instance_mutex = handle
    return True


# ---------------------------------------------------------------------------
# Drawing helpers (everything is drawn with Tkinter - no image files needed)
# ---------------------------------------------------------------------------
def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Draw a rectangle with rounded corners on a Tkinter canvas."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2,
        x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_drop(canvas, cx, cy, r, fill):
    """A water-drop shape centred on (cx, cy)."""
    cy += 0.2 * r
    tip = (cx, cy - 1.5 * r)
    points = [*tip, *tip,
              cx + r, cy + 0.1 * r, cx + 0.75 * r, cy + 0.85 * r,
              cx, cy + 1.1 * r,
              cx - 0.75 * r, cy + 0.85 * r, cx - r, cy + 0.1 * r]
    canvas.create_polygon(points, smooth=True, fill=fill, outline="")


def draw_eye_icon(canvas, cx, cy, r, iris="#1d7a49"):
    points = [cx - r, cy, cx - r, cy, cx, cy - 0.95 * r,
              cx + r, cy, cx + r, cy, cx, cy + 0.95 * r]
    canvas.create_polygon(points, smooth=True, fill="white", outline="")
    canvas.create_oval(cx - 0.4 * r, cy - 0.4 * r, cx + 0.4 * r, cy + 0.4 * r, fill=iris, outline="")
    canvas.create_oval(cx - 0.18 * r, cy - 0.18 * r, cx + 0.18 * r, cy + 0.18 * r, fill="#10202a", outline="")
    canvas.create_oval(cx + 0.05 * r, cy - 0.28 * r, cx + 0.2 * r, cy - 0.13 * r, fill="white", outline="")


def draw_person_icon(canvas, cx, cy, r):
    w = max(2, 0.2 * r)
    style = dict(fill="white", width=w, capstyle="round", joinstyle="round")
    canvas.create_oval(cx - 0.22 * r, cy - 0.85 * r, cx + 0.22 * r, cy - 0.41 * r, fill="white", outline="")
    canvas.create_line(cx, cy - 0.3 * r, cx, cy + 0.25 * r, **style)
    canvas.create_line(cx - 0.5 * r, cy + 0.05 * r, cx, cy - 0.2 * r, cx + 0.5 * r, cy + 0.05 * r, **style)
    canvas.create_line(cx - 0.32 * r, cy + 0.8 * r, cx, cy + 0.25 * r, cx + 0.32 * r, cy + 0.8 * r, **style)


def draw_clock_icon(canvas, cx, cy, r, color="white"):
    w = max(2, 0.16 * r)
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=w)
    canvas.create_line(cx, cy, cx, cy - 0.6 * r, fill=color, width=w, capstyle="round")
    canvas.create_line(cx, cy, cx + 0.45 * r, cy + 0.3 * r, fill=color, width=w, capstyle="round")


def draw_mascot(canvas, ox, oy, scale=1.0):
    """Draw the cute mascot: a girl in a purple hoodie holding a water bottle.

    (ox, oy) is the top-left corner. At scale=1 she is about 230 x 300 pixels.
    """
    def P(*values):
        # Convert "design" coordinates into real canvas coordinates.
        return [(ox if i % 2 == 0 else oy) + v * scale for i, v in enumerate(values)]

    hair, skin = "#3b2a26", "#ffe1cf"
    hoodie, hoodie_dark, hood = "#b9a3e8", "#9a82d6", "#cbbaf3"
    line_w = max(1, 2 * scale)

    # Hoodie (body) and hood behind the head
    canvas.create_polygon(P(36, 302, 44, 238, 80, 206, 150, 206, 186, 238, 194, 302),
                          smooth=True, fill=hoodie, outline=hoodie_dark, width=line_w)
    canvas.create_oval(P(34, 150, 196, 230), fill=hood, outline=hoodie_dark, width=line_w)
    # Hair (back), bun and a pink scrunchie
    canvas.create_oval(P(38, 40, 192, 198), fill=hair, outline="")
    canvas.create_oval(P(92, 2, 138, 48), fill=hair, outline="")
    canvas.create_oval(P(98, 38, 132, 54), fill="#f59ab9", outline="")
    # Face
    canvas.create_oval(P(52, 58, 178, 188), fill=skin, outline="")
    # Fringe (bangs)
    canvas.create_polygon(P(50, 122, 52, 76, 86, 48, 144, 48, 178, 76, 180, 122,
                            168, 98, 148, 86, 128, 94, 116, 76, 102, 92, 80, 88, 62, 100),
                          smooth=True, fill=hair, outline="")
    # Big shiny eyes
    canvas.create_oval(P(76, 114, 102, 144), fill="#2b1d19", outline="")
    canvas.create_oval(P(128, 114, 154, 144), fill="#2b1d19", outline="")
    canvas.create_oval(P(83, 119, 93, 129), fill="white", outline="")
    canvas.create_oval(P(135, 119, 145, 129), fill="white", outline="")
    canvas.create_oval(P(94, 134, 98, 138), fill="white", outline="")
    canvas.create_oval(P(146, 134, 150, 138), fill="white", outline="")
    # Rosy cheeks and a smile
    canvas.create_oval(P(62, 146, 84, 158), fill="#ffb0b0", outline="")
    canvas.create_oval(P(146, 146, 168, 158), fill="#ffb0b0", outline="")
    canvas.create_arc(P(104, 144, 126, 166), start=200, extent=140, style="arc",
                      outline="#8a4b3c", width=max(1, 3 * scale))
    # Hoodie strings
    canvas.create_line(P(102, 210, 99, 240), fill="white", width=max(1, 3 * scale), capstyle="round")
    canvas.create_line(P(126, 210, 129, 240), fill="white", width=max(1, 3 * scale), capstyle="round")
    # Water bottle with a drop on it
    bx1, by1, bx2, by2 = P(122, 214, 166, 292)
    rounded_rect(canvas, bx1, by1, bx2, by2, 12 * scale, fill="#82b8ff", outline="#4a86e8", width=line_w)
    cx1, cy1, cx2, cy2 = P(130, 200, 158, 218)
    rounded_rect(canvas, cx1, cy1, cx2, cy2, 6 * scale, fill="#3d73d6", outline="")
    draw_drop(canvas, ox + 144 * scale, oy + 254 * scale, 9 * scale, "white")
    # Hands holding the bottle
    canvas.create_oval(P(108, 238, 134, 262), fill=skin, outline="#e9b9a0", width=max(1, scale))
    canvas.create_oval(P(154, 254, 180, 278), fill=skin, outline="#e9b9a0", width=max(1, scale))
    # Little "sparkle" lines next to her head
    for coords in ((198, 74, 214, 62), (202, 98, 222, 96), (198, 122, 213, 134)):
        canvas.create_line(P(*coords), fill="#f6c343", width=max(2, 4 * scale), capstyle="round")


def load_mascot_image(path_text, max_w, max_h):
    """Load your own mascot picture (PNG or GIF) and shrink it to fit.

    Relative paths are looked up in the HydraBuddy folder.
    Raises tk.TclError / OSError if the file can't be used.
    """
    path = Path(path_text)
    if not path.is_absolute():
        path = APP_DIR / path
    if not path.exists():
        raise OSError(f"file not found: {path}")
    image = tk.PhotoImage(file=str(path))
    factor = max(1, math.ceil(max(image.width() / max_w, image.height() / max_h)))
    return image.subsample(factor) if factor > 1 else image


class CanvasButton:
    """A rounded, colourful button drawn on a canvas (prettier than tk.Button)."""

    def __init__(self, canvas, box, text, command, bg, fg, hover_bg, font):
        self.canvas = canvas
        self.bg, self.hover_bg = bg, hover_bg
        x1, y1, x2, y2 = box
        tag = f"button{id(self)}"
        self.rect = rounded_rect(canvas, x1, y1, x2, y2, (y2 - y1) / 2, fill=bg, outline="", tags=tag)
        self.label = canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=text, fill=fg,
                                        font=font, tags=tag)
        canvas.tag_bind(tag, "<Enter>", self._on_enter)
        canvas.tag_bind(tag, "<Leave>", self._on_leave)
        canvas.tag_bind(tag, "<Button-1>", lambda event: command())

    def _on_enter(self, _event):
        self.canvas.itemconfigure(self.rect, fill=self.hover_bg)
        self.canvas.configure(cursor="hand2")

    def _on_leave(self, _event):
        self.canvas.itemconfigure(self.rect, fill=self.bg)
        self.canvas.configure(cursor="")

    def set_text(self, text):
        self.canvas.itemconfigure(self.label, text=text)

    def text(self):
        return self.canvas.itemcget(self.label, "text")


# ---------------------------------------------------------------------------
# The timer (no GUI code here, so it is easy to understand and test)
# ---------------------------------------------------------------------------
class ReminderTimer:
    """Counts down to the next reminder.

    States:
        running - counting down
        paused  - frozen; remembers how much time was left
        waiting - the reminder pop-up is on screen; waits for you to respond
    """

    RUNNING, PAUSED, WAITING = "running", "paused", "waiting"

    def __init__(self, interval_seconds, clock=time.monotonic):
        self.interval = interval_seconds
        self.clock = clock                    # a function that returns "now" in seconds
        self.state = self.PAUSED
        self._deadline = None
        self._paused_remaining = interval_seconds

    def start(self, seconds=None):
        """(Re)start the countdown. Default: one full interval."""
        seconds = self.interval if seconds is None else seconds
        self._deadline = self.clock() + seconds
        self.state = self.RUNNING

    def pause(self):
        if self.state == self.RUNNING:
            self._paused_remaining = self.remaining()
        elif self.state == self.WAITING:
            self._paused_remaining = self.interval
        self.state = self.PAUSED

    def resume(self):
        if self.state == self.PAUSED:
            self.start(self._paused_remaining)

    def mark_waiting(self):
        """Called when the pop-up is shown: the countdown stops until you respond."""
        self.state = self.WAITING

    def remaining(self):
        if self.state == self.RUNNING:
            return max(0.0, self._deadline - self.clock())
        if self.state == self.PAUSED:
            return self._paused_remaining
        return 0.0

    def check_due(self):
        """Return True exactly once when the countdown reaches zero."""
        if self.state == self.RUNNING and self.clock() >= self._deadline:
            self.state = self.WAITING
            return True
        return False


# ---------------------------------------------------------------------------
# The big reminder pop-up
# ---------------------------------------------------------------------------
class ReminderPopup:
    """The friendly reminder window shown in the centre of the screen.

    The layout is calculated from your settings: switched-off reminders are
    left out, and cards grow when you write longer messages.
    """

    WIDTH = 760    # design width in pixels (scaled up on high-DPI screens)

    def __init__(self, app):
        self.app = app
        self.theme = app.theme
        self.settings = app.settings
        self.alive = True
        self._after_ids = []
        self._eye_seconds_left = 0
        self._mascot_photo = None
        self.eye_button = None
        self.buttons = []
        self.cards = []

        self.win = win = tk.Toplevel(app.root)
        win.withdraw()
        win.title("HydraBuddy reminder")
        win.overrideredirect(True)            # no grey title bar
        win.attributes("-topmost", True)      # stay above other windows
        win.configure(bg=TRANSPARENT_KEY)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(win, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.canvas.pack()

        # Draw, then shrink if the pop-up would not fit on the screen.
        left, top, right, bottom = get_work_area(app.root)
        s = app.s
        for _attempt in range(3):
            height = self._draw(s)
            fit = min(1.0, 0.95 * (right - left) / (self.WIDTH * s), 0.95 * (bottom - top) / (height * s))
            if fit >= 0.99:
                break
            s *= fit
        w, h = int(self.WIDTH * s), int(height * s)
        self.canvas.configure(width=w, height=h)
        x = left + (right - left - w) // 2
        y = top + (bottom - top - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

        win.bind("<Escape>", lambda event: app.dismiss_reminder())
        win.bind("<Return>", lambda event: app.dismiss_reminder())
        win.deiconify()
        win.lift()
        self._later(500, self._keep_on_top)

    # -- layout --------------------------------------------------------------
    def font(self, family, points, weight="normal"):
        """A font sized in pixels, so text shrinks together with the pop-up."""
        return (family, -max(8, round(points * 4 / 3 * self.s)), weight)

    def _draw(self, s):
        """Draw everything at scale s. Returns the design height."""
        self.s = s
        c, t, st = self.canvas, self.theme, self.settings
        c.delete("all")
        self.buttons, self.cards, self.eye_button = [], [], None

        def S(*values):
            return [v * s for v in values]

        show_mascot = st["show_mascot"]
        x_left = 270 if show_mascot else 36
        x_right = 724

        # Heading (shrinks to fit long custom headings)
        pill = rounded_rect(c, *S(x_left, 30, 690, 92), 30 * s, fill=t["pill"], outline="")
        heading = c.create_text(*S((x_left + 690) / 2, 61), text=st["heading"], fill=t["pill_text"],
                                justify="center")
        max_w = (690 - x_left - 30) * s
        for size in (15, 14, 13, 12, 11, 10):
            c.itemconfigure(heading, font=self.font(t["heading_font"], size, "bold"))
            x1, _, x2, _ = c.bbox(heading)
            if x2 - x1 <= max_w:
                break
        else:
            c.itemconfigure(heading, width=max_w)
        c.tag_raise(heading, pill)

        if st["subheading"]:
            sub = c.create_text(*S((x_left + 690) / 2 - 10, 114), text=st["subheading"],
                                font=self.font(t["heading_font"], 11), fill=t["ink_soft"])
            c.create_text(c.bbox(sub)[2] + 6 * s, 114 * s, text="♥", anchor="w",
                          font=self.font("Segoe UI Symbol", 13), fill=t["heart"])

        # Close button (X)
        c.create_oval(*S(706, 26, 740, 60), fill=t["close_bg"], outline="", tags="close")
        c.create_text(*S(723, 43), text="✕", font=self.font("Segoe UI Symbol", 12, "bold"),
                      fill=t["ink"], tags="close")
        c.tag_bind("close", "<Button-1>", lambda event: self.app.dismiss_reminder())
        c.tag_bind("close", "<Enter>", lambda event: c.configure(cursor="hand2"))
        c.tag_bind("close", "<Leave>", lambda event: c.configure(cursor=""))

        # Reminder cards (only the switched-on ones)
        y = 140
        for rid in REMINDER_ORDER:
            if st["reminders"][rid]["enabled"]:
                y += self._card(rid, x_left, x_right, y) + 12
        y -= 12

        # Closing message
        if st["closing_message"]:
            c.create_text(*S((x_left + x_right) / 2 if not show_mascot else 480, y + 32),
                          text=st["closing_message"] + "  ☺", font=self.font(t["heading_font"], 12),
                          fill=t["ink"], width=(x_right - x_left) * s, justify="center")
            buttons_top = y + 66
        else:
            buttons_top = y + 30

        # Buttons, spread evenly across the bottom
        app = self.app
        specs = []
        if st["reminders"]["look_far"]["enabled"]:
            specs.append(("eye", f"Look far: start {st['eye_break_seconds']}s", self._start_eye_timer,
                          t["eye"], t["eye_text"], t["eye_hover"]))
        specs.append(("done", f"Done! Next in {nice_duration(app.interval, short=True)}",
                      app.dismiss_reminder, t["primary"], t["primary_text"], t["primary_hover"]))
        if st["snooze_enabled"]:
            specs.append(("snooze", f"Snooze {nice_duration(app.snooze_seconds, short=True)}",
                          app.snooze_reminder, t["secondary"], t["secondary_text"], t["secondary_hover"]))
        gap = 14
        width = (724 - 36 - gap * (len(specs) - 1)) / len(specs)
        for i, (name, text, command, bg, fg, hover) in enumerate(specs):
            x1 = 36 + i * (width + gap)
            button = CanvasButton(c, S(x1, buttons_top, x1 + width, buttons_top + 48), text, command,
                                  bg, fg, hover, self.font(t["body_font"], 11, "bold"))
            button.name = name
            self.buttons.append(button)
            if name == "eye":
                self.eye_button = button
        height = buttons_top + 48 + 30

        # Mascot (drawn girl, or your own picture), sized to the space left
        if show_mascot:
            self._draw_mascot(22, 96, 230, buttons_top - 20 - 96)

        # Background card, drawn last and pushed behind everything
        bg = rounded_rect(c, *S(8, 8, self.WIDTH - 8, height - 8), 36 * s, fill=t["bg"],
                          outline=t["border"], width=max(2, int(3 * s)), tags="drag")
        c.tag_lower(bg)
        c.tag_bind("drag", "<ButtonPress-1>", self._drag_start)
        c.tag_bind("drag", "<B1-Motion>", self._drag_move)
        return height

    def _draw_mascot(self, x, y, box_w, box_h):
        c, s = self.canvas, self.s
        if self.settings["mascot_image"]:
            try:
                self._mascot_photo = load_mascot_image(self.settings["mascot_image"], box_w * s, box_h * s)
                c.create_image((x + box_w / 2) * s, (y + box_h / 2) * s, image=self._mascot_photo)
                return
            except (tk.TclError, OSError) as exc:
                self.app.report_problem(f"Could not load your mascot image ({exc}). Using the default mascot.")
        scale = min(1.0, box_h / 300)
        draw_mascot(c, (x + (230 - 230 * scale) / 2) * s, y * s, scale * s)

    def _card(self, rid, x1, x2, y):
        """Draw one reminder card. Returns its height."""
        c, t, s = self.canvas, self.theme, self.s
        text_x, text_w = x1 + 88, x2 - x1 - 104
        title = c.create_text(text_x * s, (y + 12) * s, text=reminder_text(self.settings, rid, "title"),
                              anchor="nw", width=text_w * s,
                              font=self.font(t["body_font"], 14, "bold"), fill=t[f"{rid}_title"])
        desc_y = c.bbox(title)[3] + 2 * s
        desc = c.create_text(text_x * s, desc_y, text=reminder_text(self.settings, rid, "text"),
                             anchor="nw", width=text_w * s,
                             font=self.font(t["body_font"], 10), fill=t["ink_soft"])
        h = max(84, c.bbox(desc)[3] / s - y + 12)
        rect = rounded_rect(c, x1 * s, y * s, x2 * s, (y + h) * s, 28 * s, fill=t[f"{rid}_bg"], outline="")
        c.tag_lower(rect, title)
        cx, cy, r = (x1 + 44) * s, (y + h / 2) * s, 29 * s
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=t[f"{rid}_icon"], outline="white",
                      width=max(2, int(3 * s)))
        if rid == "water":
            draw_drop(c, cx, cy, r * 0.48, "white")
        elif rid == "look_far":
            draw_eye_icon(c, cx, cy, r * 0.72, iris=t["look_far_icon"])
        else:
            draw_person_icon(c, cx, cy, r * 0.75)
        self.cards.append(rid)
        return h

    # -- behaviour -----------------------------------------------------------
    def _later(self, ms, func):
        """Like win.after(), but remembers the id so it can be cancelled on close."""
        self._after_ids.append(self.win.after(ms, func))

    def _keep_on_top(self):
        # Re-assert "always on top" every few seconds (without stealing focus).
        if not self.alive:
            return
        self.win.attributes("-topmost", True)
        self.win.lift()
        self._later(5000, self._keep_on_top)

    def _start_eye_timer(self):
        if self._eye_seconds_left > 0:
            return                        # already counting down
        self._eye_seconds_left = self.settings["eye_break_seconds"]
        self._eye_step()

    def _eye_step(self):
        if not self.alive or self.eye_button is None:
            return
        if self._eye_seconds_left > 0:
            self.eye_button.set_text(f"Look far...  {self._eye_seconds_left}s")
            self._eye_seconds_left -= 1
            self._later(1000, self._eye_step)
        else:
            self.eye_button.set_text("Eyes relaxed  ✓")

    def _drag_start(self, event):
        self._drag_dx = event.x_root - self.win.winfo_x()
        self._drag_dy = event.y_root - self.win.winfo_y()

    def _drag_move(self, event):
        self.win.geometry(f"+{event.x_root - self._drag_dx}+{event.y_root - self._drag_dy}")

    def close(self):
        if not self.alive:
            return
        self.alive = False
        for after_id in self._after_ids:
            try:
                self.win.after_cancel(after_id)
            except tk.TclError:
                pass
        self._after_ids.clear()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Small message in the bottom-right corner ("Next reminder in 20 minutes")
# ---------------------------------------------------------------------------
class Toast:
    def __init__(self, app, text, seconds=TOAST_SECONDS):
        s = app.s
        self.alive = True
        self.text = text
        self.win = win = tk.Toplevel(app.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=TRANSPARENT_KEY)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass
        c = tk.Canvas(win, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        c.pack()
        # Size the toast to fit the message (long messages wrap onto more lines).
        label = c.create_text(56 * s, 14 * s, text=text, anchor="nw", fill="white",
                              font=("Segoe UI", 11), width=440 * s)
        x1, y1, x2, y2 = c.bbox(label)
        w, h = int(x2 + 22 * s), int(max(58 * s, y2 + 14 * s))
        c.configure(width=w, height=h)
        c.coords(label, 56 * s, (h - (y2 - y1)) / 2)
        c.tag_lower(rounded_rect(c, 0, 0, w, h, 18 * s, fill="#262b36", outline=""))
        draw_clock_icon(c, 30 * s, h / 2, 11 * s)
        c.bind("<Button-1>", lambda event: self.close())
        left, top, right, bottom = get_work_area(app.root)
        win.geometry(f"{w}x{h}+{right - w - int(16 * s)}+{bottom - h - int(16 * s)}")
        win.deiconify()
        self._after_id = win.after(int(seconds * 1000), self.close)

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.win.after_cancel(self._after_id)
            self.win.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Optional system-tray icon (needs: py -m pip install pystray pillow)
# ---------------------------------------------------------------------------
class TrayIcon:
    """Tray icon with a right-click menu. Runs in its own thread.

    Tkinter is not thread-safe, so menu clicks are passed to the main window
    through app.post(), which runs them safely on the Tkinter thread.
    """

    def __init__(self, app):
        self.app = app
        self._last_title = ""
        menu = pystray.Menu(
            pystray.MenuItem("Open HydraBuddy", lambda: app.post(app.show_main_window), default=True),
            pystray.MenuItem("Remind me now", lambda: app.post(app.show_reminder)),
            pystray.MenuItem(
                lambda item: "Resume reminders" if app.timer.state == ReminderTimer.PAUSED else "Pause reminders",
                lambda: app.post(app.toggle_pause)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit HydraBuddy", lambda: app.post(app.user_exit)),
        )
        self.icon = pystray.Icon(APP_NAME, self._make_image(), APP_NAME, menu)
        self.thread = threading.Thread(target=self.icon.run, daemon=True)
        self.thread.start()

    @staticmethod
    def _make_image():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, 62, 62), fill=(124, 92, 224, 255))
        d.ellipse((20, 28, 44, 52), fill="white")
        d.polygon([(32, 9), (21, 36), (43, 36)], fill="white")
        return img

    def set_title(self, text):
        if text != self._last_title:
            self._last_title = text
            try:
                self.icon.title = text
            except Exception:
                pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# The main application
# ---------------------------------------------------------------------------
class HydraBuddyApp:
    TICK_MS = 500   # how often we check the timer (twice a second - very cheap)

    def __init__(self, root, settings=None, interval_seconds=None, snooze_seconds=None,
                 use_tray=True, start_minimized=False, clock=time.monotonic, auto_tick=True,
                 lock_check=None, settings_path=None, startup_task_prefix=TASK_NAME,
                 exit_flag_path=None):
        self.root = root
        self.settings_path = Path(settings_path) if settings_path else SETTINGS_FILE
        self.startup_task_prefix = startup_task_prefix
        self.exit_flag_path = exit_flag_path      # only set by main(); tests leave it off
        self.watchdog = None                      # started by main()
        self.settings = settings if settings is not None else validate_settings({}, [])
        # --test or --interval-seconds fix the interval (the menu is then disabled).
        self.fixed_interval = interval_seconds
        self.fixed_snooze = snooze_seconds
        self.interval = interval_seconds or self.settings["interval_minutes"] * 60
        self.snooze_seconds = snooze_seconds or self.settings["snooze_minutes"] * 60

        # A function that says whether the screen is locked (replaceable in tests).
        self.is_locked = lock_check or is_screen_locked
        self._was_locked = False
        self._last_loop_time = time.monotonic()
        self._last_loop_wall = time.time()
        self.timer = ReminderTimer(self.interval, clock)
        self.popup = None
        self.toast = None
        self.tray = None
        self.closed = False
        self.problems = []                   # settings problems shown to the user
        self.main_frame = None
        self._placed = False
        self._tick_id = None
        self._queue_id = None
        self._calls = queue.Queue()          # jobs sent from the tray thread
        self._told_about_background = False

        # Scale factor for high-DPI screens (1.0 on a normal 100% display)
        self.s = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.report_callback_exception = self._report_error
        root.title("HydraBuddy")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_background)
        # Windows is shutting down or signing out: close straight away so we never hold it up.
        root.protocol("WM_SAVE_YOURSELF", lambda: self.exit_app(reason="Windows is shutting down / signing out"))

        self.state_text = tk.StringVar()
        self.countdown_text = tk.StringVar()
        self.tray_note = tk.StringVar()
        self.theme = self._make_theme()
        self._build_main_window()

        if use_tray and TRAY_AVAILABLE:
            try:
                self.tray = TrayIcon(self)
            except Exception as exc:
                log_error(f"Tray icon could not start: {exc}")
                self.tray = None
        self.tray_note.set("Tray icon: on (bottom-right of the taskbar)" if self.tray
                           else "Tray icon: off  (optional: py -m pip install pystray pillow)")

        # The first reminder comes one full interval after starting.
        self.timer.start()
        self.refresh_status()

        if start_minimized:
            self.hide_to_background(show_message=False)

        if auto_tick:
            self._tick_id = root.after(self.TICK_MS, self._tick_loop)
            self._queue_id = root.after(200, self._process_calls)

    # -- settings ------------------------------------------------------------
    def _make_theme(self):
        """The chosen theme plus your own colour overrides (invalid colours are skipped)."""
        theme = dict(THEMES[self.settings["theme"]])
        for name, color in self.settings["colors"].items():
            try:
                self.root.winfo_rgb(color)          # raises TclError if not a real colour
                theme[name] = color
            except tk.TclError:
                self.report_problem(f'"{color}" is not a valid colour for "{name}".')
        return theme

    def report_problem(self, text):
        """Log a settings problem and show it in the corner (once)."""
        if text in self.problems:
            return
        self.problems.append(text)
        log_error(f"Settings: {text}")
        self.show_toast(text, seconds=8)

    def save(self):
        try:
            save_settings(self.settings, self.settings_path)
        except OSError as exc:
            self.report_problem(f"Could not save settings ({exc}).")

    def apply_settings(self, settings):
        """Use new settings straight away (theme, interval, texts, ...)."""
        old_interval = self.interval
        self.settings = settings
        self.interval = self.fixed_interval or settings["interval_minutes"] * 60
        self.snooze_seconds = self.fixed_snooze or settings["snooze_minutes"] * 60
        self.timer.interval = self.interval
        self.theme = self._make_theme()
        if self.popup_is_open():
            self._close_popup()
            self.timer.start()
        self._build_main_window()
        if self.interval != old_interval and self.timer.state != ReminderTimer.PAUSED:
            self.timer.start()
        self.refresh_status()

    def set_interval_minutes(self, minutes):
        self.settings["interval_minutes"] = minutes
        self.save()
        self.apply_settings(self.settings)
        self.show_toast(f"Reminders every {nice_duration(self.interval)}. "
                        f"Next one in {nice_duration(self.interval)}.")

    def set_theme(self, name):
        self.settings["theme"] = name
        self.save()
        self.apply_settings(self.settings)

    def set_sound(self, enabled):
        self.settings["sound_enabled"] = enabled
        self.save()
        if enabled:
            play_reminder_sound(self.settings["sound_volume"])   # a quick preview

    def set_startup(self, enabled):
        try:
            if enabled:
                install_startup(self.startup_task_prefix)
                self.show_toast("HydraBuddy will now start when you sign in.")
            else:
                remove_startup(self.startup_task_prefix)
                self.show_toast("HydraBuddy will no longer start with Windows.")
        except (OSError, subprocess.CalledProcessError) as exc:
            self.report_problem(f"Could not change the startup setting ({exc}).")
        if self.main_frame is not None:
            self.startup_var.set(is_startup_installed(self.startup_task_prefix))

    def edit_settings_file(self):
        if not self.settings_path.exists():
            self.save()
        try:
            subprocess.Popen(["notepad.exe", str(self.settings_path)])
            self.show_toast("Edit, save the file, then click 'Reload settings'.")
        except OSError as exc:
            self.report_problem(f"Could not open Notepad ({exc}). The file is {self.settings_path}")

    def reload_settings(self):
        settings, problems = load_settings(self.settings_path)
        self.problems.clear()
        self.apply_settings(settings)
        for problem in problems:
            self.report_problem(problem)
        if not problems:
            self.show_toast("Settings reloaded.")

    # -- main window ---------------------------------------------------------
    def _build_main_window(self):
        """(Re)build the main window in the current theme."""
        r, s, t = self.root, self.s, self.theme
        if self.main_frame is not None:
            self.main_frame.destroy()
        r.configure(bg=t["bg"])
        f = self.main_frame = tk.Frame(r, bg=t["bg"])
        f.pack(fill="both", expand=True)
        body = (t["body_font"], 10)

        header = tk.Frame(f, bg=t["bg"])
        header.pack(fill="x", padx=18, pady=(14, 4))
        mascot = tk.Canvas(header, width=int(104 * s), height=int(130 * s), bg=t["bg"], highlightthickness=0)
        mascot.pack(side="left")
        self._draw_small_mascot(mascot, 104 * s, 130 * s)
        titles = tk.Frame(header, bg=t["bg"])
        titles.pack(side="left", padx=10)
        tk.Label(titles, text="HydraBuddy", font=(t["body_font"], 20, "bold"), fg=t["status_text"],
                 bg=t["bg"]).pack(anchor="w")
        tk.Label(titles, text="Your eye & body break buddy", font=body, fg=t["ink_soft"],
                 bg=t["bg"]).pack(anchor="w")
        enabled = [reminder_text(self.settings, rid, "title").split(" — ")[0]
                   for rid in REMINDER_ORDER if self.settings["reminders"][rid]["enabled"]]
        tk.Label(titles, text="  •  ".join(enabled), font=(t["body_font"], 9), fg=t["ink_soft"],
                 bg=t["bg"]).pack(anchor="w", pady=(4, 0))

        status = tk.Frame(f, bg=t["status_bg"])
        status.pack(fill="x", padx=18, pady=8)
        tk.Label(status, textvariable=self.state_text, font=(t["body_font"], 10, "bold"),
                 fg=t["status_text"], bg=t["status_bg"]).pack(pady=(10, 0))
        tk.Label(status, textvariable=self.countdown_text, font=(t["body_font"], 28, "bold"),
                 fg=t["ink"], bg=t["status_bg"]).pack()
        tk.Label(status, text=f"A reminder every {nice_duration(self.interval)}", font=(t["body_font"], 9),
                 fg=t["ink_soft"], bg=t["status_bg"]).pack(pady=(0, 10))

        row1 = tk.Frame(f, bg=t["bg"])
        row1.pack(padx=14, pady=(4, 4))
        self._button(row1, "Start / Restart", self.start_interval, "primary")
        self.pause_button = self._button(row1, "Pause", self.pause, "secondary")
        self.resume_button = self._button(row1, "Resume", self.resume, "secondary")

        row2 = tk.Frame(f, bg=t["bg"])
        row2.pack(padx=14, pady=4)
        self._button(row2, "Remind me now", self.show_reminder, "secondary")
        self._button(row2, "Run in background", self.hide_to_background, "secondary")
        self._button(row2, "Exit", self.user_exit, "secondary")

        # Personalise section
        box = tk.Frame(f, bg=t["status_bg"])
        box.pack(fill="x", padx=18, pady=(10, 4))
        tk.Label(box, text="Personalise", font=(t["body_font"], 10, "bold"), fg=t["status_text"],
                 bg=t["status_bg"]).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))

        tk.Label(box, text="Remind me every", font=body, fg=t["ink"], bg=t["status_bg"]).grid(
            row=1, column=0, sticky="w", padx=(10, 4))
        if self.fixed_interval:
            values, current = [f"{nice_duration(self.interval, short=True)} (test)"], 0
        else:
            minutes = sorted(set(INTERVAL_CHOICES + [self.settings["interval_minutes"]]))
            values = [f"{m} min" for m in minutes]
            current = minutes.index(self.settings["interval_minutes"])
        self.interval_box = ttk.Combobox(box, values=values, state="readonly", width=12, font=body)
        self.interval_box.current(current)
        if self.fixed_interval:
            self.interval_box.configure(state="disabled")
        self.interval_box.bind("<<ComboboxSelected>>", lambda e: self.set_interval_minutes(
            int(self.interval_box.get().split()[0])))
        self.interval_box.grid(row=1, column=1, sticky="w")

        tk.Label(box, text="Theme", font=body, fg=t["ink"], bg=t["status_bg"]).grid(
            row=1, column=2, sticky="w", padx=(14, 4))
        self.theme_box = ttk.Combobox(box, values=list(THEMES), state="readonly", width=12, font=body)
        self.theme_box.set(self.settings["theme"])
        self.theme_box.bind("<<ComboboxSelected>>", lambda e: self.set_theme(self.theme_box.get()))
        self.theme_box.grid(row=1, column=3, sticky="w", padx=(0, 10))

        check = dict(font=body, fg=t["ink"], bg=t["status_bg"], activebackground=t["status_bg"],
                     activeforeground=t["ink"], selectcolor=t["bg"], highlightthickness=0)
        self.sound_var = tk.BooleanVar(value=self.settings["sound_enabled"])
        tk.Checkbutton(box, text="Sound", variable=self.sound_var,
                       command=lambda: self.set_sound(self.sound_var.get()), **check).grid(
            row=2, column=0, sticky="w", padx=6, pady=4)
        self.startup_var = tk.BooleanVar(value=is_startup_installed(self.startup_task_prefix))
        tk.Checkbutton(box, text="Start with Windows", variable=self.startup_var,
                       command=lambda: self.set_startup(self.startup_var.get()), **check).grid(
            row=2, column=1, columnspan=3, sticky="w", pady=4)

        files = tk.Frame(box, bg=t["status_bg"])
        files.grid(row=3, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 10))
        self._button(files, "Edit settings file", self.edit_settings_file, "secondary", small=True)
        self._button(files, "Reload settings", self.reload_settings, "secondary", small=True)

        tk.Label(f, textvariable=self.tray_note, font=(t["body_font"], 8), fg=t["ink_soft"],
                 bg=t["bg"]).pack(pady=(6, 12))

        # Place the main window near the centre of the screen (first time only)
        if not self._placed:
            self._placed = True
            r.update_idletasks()
            w, h = r.winfo_reqwidth(), r.winfo_reqheight()
            r.geometry(f"+{(r.winfo_screenwidth() - w) // 2}+{max(0, (r.winfo_screenheight() - h) // 3)}")

    def _draw_small_mascot(self, canvas, max_w, max_h):
        if not self.settings["show_mascot"]:
            canvas.configure(width=1)
            return
        if self.settings["mascot_image"]:
            try:
                self._small_mascot_photo = load_mascot_image(self.settings["mascot_image"], max_w, max_h)
                canvas.create_image(max_w / 2, max_h / 2, image=self._small_mascot_photo)
                return
            except (tk.TclError, OSError) as exc:
                self.report_problem(f"Could not load your mascot image ({exc}). Using the default mascot.")
        draw_mascot(canvas, 2 * self.s, 2 * self.s, 0.42 * self.s)

    def _button(self, parent, text, command, style, small=False):
        t = self.theme
        b = tk.Button(parent, text=text, command=command, bg=t[style], fg=t[f"{style}_text"],
                      activebackground=t[f"{style}_hover"], activeforeground=t[f"{style}_text"],
                      disabledforeground=t["ink_soft"], relief="flat", bd=0,
                      padx=10 if small else 14, pady=4 if small else 7,
                      font=(t["body_font"], 9 if small else 10, "bold"), cursor="hand2")
        b.pack(side="left", padx=5 if not small else 4)
        return b

    def refresh_status(self):
        """Update the countdown text, buttons and tray tooltip."""
        state = self.timer.state
        if state == ReminderTimer.RUNNING:
            self.state_text.set("Next reminder in")
            self.countdown_text.set(format_countdown(self.timer.remaining()))
        elif state == ReminderTimer.PAUSED:
            self.state_text.set("Paused — press Resume to continue")
            self.countdown_text.set(format_countdown(self.timer.remaining()))
        else:
            self.state_text.set("Break time!")
            self.countdown_text.set("Now")
        self.pause_button.configure(state="normal" if state != ReminderTimer.PAUSED else "disabled")
        self.resume_button.configure(state="normal" if state == ReminderTimer.PAUSED else "disabled")
        if self.tray:
            if state == ReminderTimer.RUNNING:
                minutes = int(math.ceil(self.timer.remaining() / 60))
                self.tray.set_title(f"HydraBuddy - next reminder in about {minutes} min")
            elif state == ReminderTimer.PAUSED:
                self.tray.set_title("HydraBuddy - paused")
            else:
                self.tray.set_title("HydraBuddy - break time!")

    # -- the timer loop ------------------------------------------------------
    def tick(self):
        """One check of the timer: show the pop-up if it is time."""
        if self.is_locked():
            # You are away from the laptop: never pop up on the lock screen.
            self._was_locked = True
            return
        if self._was_locked:
            # You just unlocked the laptop: start counting from now.
            self._was_locked = False
            self.welcome_back()
        if self.timer.check_due():
            self.show_reminder()
        self.refresh_status()

    def welcome_back(self):
        """Called after unlocking or waking the laptop: restart the countdown."""
        if self.timer.state == ReminderTimer.PAUSED:
            return                      # you paused it on purpose - leave it paused
        self._close_popup()
        self.timer.start()
        self.show_toast(f"Welcome back! Next break in {nice_duration(self.interval)}")
        self.refresh_status()

    def _tick_loop(self):
        self._tick_id = None
        if self.closed:
            return
        now, wall = time.monotonic(), time.time()
        # The loop runs twice a second, so a long gap means the laptop was asleep.
        # Both clocks are checked: on some PCs the monotonic clock pauses during sleep.
        gap = max(now - self._last_loop_time, wall - self._last_loop_wall)
        if gap > SLEEP_GAP_SECONDS:
            self.welcome_back()
        self._last_loop_time, self._last_loop_wall = now, wall
        if self.watchdog is not None:
            self.watchdog.beat()
        self.tick()
        self._tick_id = self.root.after(self.TICK_MS, self._tick_loop)

    def post(self, func):
        """Ask the Tkinter thread to run func (safe to call from any thread)."""
        self._calls.put(func)

    def _process_calls(self):
        self._queue_id = None
        if self.closed:
            return
        while True:
            try:
                func = self._calls.get_nowait()
            except queue.Empty:
                break
            func()
            if self.closed:
                return
        self._queue_id = self.root.after(200, self._process_calls)

    # -- actions -------------------------------------------------------------
    def popup_is_open(self):
        return self.popup is not None and self.popup.alive

    def show_reminder(self):
        """Show the reminder pop-up (never more than one at a time)."""
        if self.closed:
            return
        if self.popup_is_open():
            self.popup.win.lift()
            return
        self.timer.mark_waiting()
        self.popup = ReminderPopup(self)
        if self.settings["sound_enabled"]:
            play_reminder_sound(self.settings["sound_volume"])
        self.refresh_status()

    def _close_popup(self):
        if self.popup is not None:
            self.popup.close()
            self.popup = None

    def show_toast(self, text, seconds=TOAST_SECONDS):
        if self.closed:
            return
        if self.toast is not None:
            self.toast.close()
        self.toast = Toast(self, text, seconds)

    def dismiss_reminder(self):
        """'Done' or X: close the pop-up and start the next full interval."""
        self._close_popup()
        self.timer.start()
        self.show_toast(f"Next reminder in {nice_duration(self.interval)}")
        self.refresh_status()

    def snooze_reminder(self):
        self._close_popup()
        self.timer.start(self.snooze_seconds)
        self.show_toast(f"Snoozed — back in {nice_duration(self.snooze_seconds)}")
        self.refresh_status()

    def start_interval(self):
        """Start (or restart) a fresh full interval."""
        self._close_popup()
        self.timer.start()
        self.show_toast(f"Started! Next reminder in {nice_duration(self.interval)}")
        self.refresh_status()

    def pause(self):
        self._close_popup()
        self.timer.pause()
        self.refresh_status()

    def resume(self):
        self.timer.resume()
        self.refresh_status()

    def toggle_pause(self):
        if self.timer.state == ReminderTimer.PAUSED:
            self.resume()
        else:
            self.pause()

    def show_main_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_to_background(self, show_message=True):
        """Hide the main window; the timer keeps running."""
        if self.tray:
            self.root.withdraw()
            where = "Right-click the tray icon for options"
        else:
            self.root.iconify()
            where = "It is minimised on the taskbar"
        if show_message and not self._told_about_background:
            self._told_about_background = True
            self.show_toast(f"Still running! {where}.")

    def user_exit(self):
        """The Exit button / tray menu: quit, and stay closed until the next sign-in."""
        if self.exit_flag_path is not None:
            try:
                Path(self.exit_flag_path).write_text("Exit was clicked. Deleted at the next sign-in.\n")
            except OSError:
                pass
        self.exit_app(reason="Exit clicked")

    def exit_app(self, reason="closed"):
        """Stop everything cleanly: timers, pop-ups, tray icon, window."""
        if self.closed:
            return
        self.closed = True
        if self.watchdog is not None:
            log_error(f"HydraBuddy stopped ({reason}).")
        for after_id in (self._tick_id, self._queue_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._tick_id = self._queue_id = None
        self._close_popup()
        if self.toast is not None:
            self.toast.close()
        if self.tray is not None:
            self.tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _report_error(self, exc_type, exc_value, exc_tb):
        log_error("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


# ---------------------------------------------------------------------------
# Watchdog: if the window ever freezes, record why and restart automatically
# ---------------------------------------------------------------------------
class Watchdog:
    """Runs in a background thread and checks that the timer loop is still alive.

    The timer loop calls beat() twice a second. If no beat arrives for
    HANG_SECONDS while the laptop is awake, the app is frozen: the watchdog
    writes what every thread was doing into hydra_buddy.log, starts a fresh
    copy of HydraBuddy, and ends the frozen one.
    """

    CHECK_EVERY = 5   # seconds between checks

    def __init__(self, hang_seconds=HANG_SECONDS, on_hang=None,
                 mono=time.monotonic, wall=time.time):
        self.hang_seconds = hang_seconds
        self.on_hang = on_hang or self._restart
        self.mono, self.wall = mono, wall
        self.heartbeat = mono()
        self.awake_since = mono()
        self._last_mono, self._last_wall = mono(), wall()
        self.stopped = False

    def beat(self):
        self.heartbeat = self.mono()

    def check(self):
        """One check. Returns True (and calls on_hang) if the app is frozen."""
        now, wall = self.mono(), self.wall()
        gap = max(now - self._last_mono, wall - self._last_wall)
        self._last_mono, self._last_wall = now, wall
        if gap > self.CHECK_EVERY * 4:
            # The laptop was asleep: give the app time to wake up before judging it.
            self.awake_since = now
            self.heartbeat = now
            return False
        frozen_for = now - self.heartbeat
        if frozen_for > self.hang_seconds and now - self.awake_since > self.hang_seconds:
            self.on_hang(frozen_for)
            return True
        return False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="watchdog").start()

    def _run(self):
        while not self.stopped:
            time.sleep(self.CHECK_EVERY)
            if not self.stopped and self.check():
                return

    @staticmethod
    def _restart(frozen_for):
        log_error(f"HydraBuddy was frozen for {frozen_for:.0f} s. What each part was doing:")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                faulthandler.dump_traceback(file=f, all_threads=True)
        except OSError:
            pass
        try:
            subprocess.Popen([str(pythonw_path()), str(Path(__file__).resolve()), "--minimized", "--restarted"],
                             cwd=str(APP_DIR), close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log_error("Started a fresh copy of HydraBuddy.")
        except OSError as exc:
            log_error(f"Could not restart HydraBuddy ({exc}).")
        os._exit(3)


# ---------------------------------------------------------------------------
# Start with Windows (Task Scheduler)
#
# Two scheduled tasks are created for your Windows user:
#   "HydraBuddy"            - starts it when you sign in
#   "HydraBuddy-KeepAlive"  - starts it again when you unlock the laptop
#                             (also after sleep) and checks every 15 minutes,
#                             in case it was closed by Windows or crashed.
# If HydraBuddy is already running, the extra start just quits quietly.
# If you clicked Exit, it stays closed until your next sign-in.
# ---------------------------------------------------------------------------
def pythonw_path():
    """pythonw.exe runs Python without a black console window."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def _run_powershell(command):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def startup_folder():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def is_startup_installed(prefix=TASK_NAME):
    if os.name != "nt":
        return False
    result = subprocess.run(["schtasks", "/Query", "/TN", prefix], capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode == 0


def install_startup(prefix=TASK_NAME):
    """Create (or update) the two scheduled tasks. Returns their names."""
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ['USERNAME']}".lstrip("\\")
    script = Path(__file__).resolve()
    q = _ps_quote
    argument = q(f'"{script}" --minimized ')
    command = f"""
$ErrorActionPreference = 'Stop'
$user = {q(user)}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
function Action($mode) {{
    New-ScheduledTaskAction -Execute {q(pythonw_path())} -WorkingDirectory {q(script.parent)} -Argument ({argument} + $mode)
}}
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
Register-ScheduledTask -TaskName {q(prefix)} -Action (Action '--autostart') -Trigger $atLogon `
    -Settings $settings -Principal $principal -Force `
    -Description 'Starts HydraBuddy (break reminder) when you sign in.' | Out-Null

$unlockClass = Get-CimClass -Namespace ROOT\\Microsoft\\Windows\\TaskScheduler -ClassName MSFT_TaskSessionStateChangeTrigger
$onUnlock = New-CimInstance -CimClass $unlockClass -ClientOnly -Property @{{ StateChange = 8; UserId = $user; Enabled = $true }}
$every = New-ScheduledTaskTrigger -AtLogOn -User $user
$every.Delay = 'PT5M'
$every.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {KEEPALIVE_MINUTES})).Repetition
Register-ScheduledTask -TaskName {q(prefix + KEEPALIVE_SUFFIX)} -Action (Action '--keepalive') `
    -Trigger $onUnlock, $every -Settings $settings -Principal $principal -Force `
    -Description 'Restarts HydraBuddy after unlocking or if it was closed by Windows.' | Out-Null
"""
    result = _run_powershell(command)
    if result.returncode != 0:
        raise OSError(f"Task Scheduler refused: {result.stderr.strip()[:300]}")
    if prefix == TASK_NAME:
        # Upgrade from the old Startup-folder shortcut, so it doesn't start twice.
        try:
            (startup_folder() / STARTUP_SHORTCUT_NAME).unlink(missing_ok=True)
        except (OSError, KeyError):
            pass
    return [prefix, prefix + KEEPALIVE_SUFFIX]


def remove_startup(prefix=TASK_NAME):
    """Delete the scheduled tasks (and any old shortcut). Returns True if something was removed."""
    removed = False
    for name in (prefix, prefix + KEEPALIVE_SUFFIX):
        if is_startup_installed(name):
            _run_powershell(f"Unregister-ScheduledTask -TaskName {_ps_quote(name)} -Confirm:$false")
            removed = True
    if prefix == TASK_NAME:
        try:
            old = startup_folder() / STARTUP_SHORTCUT_NAME
            if old.exists():
                old.unlink()
                removed = True
        except (OSError, KeyError):
            pass
    return removed


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="HydraBuddy - offline eye care & hydration reminder")
    p.add_argument("--test", action="store_true",
                   help=f"test mode: remind every {TEST_INTERVAL_SECONDS} seconds")
    p.add_argument("--interval-seconds", type=int, metavar="N",
                   help="custom interval in seconds for this run only (e.g. 900 = 15 minutes)")
    p.add_argument("--minimized", action="store_true", help="start hidden in the background")
    p.add_argument("--no-tray", action="store_true", help="do not create a tray icon")
    p.add_argument("--install-startup", action="store_true",
                   help="start HydraBuddy when you sign in, and again after unlocking")
    p.add_argument("--remove-startup", action="store_true", help="stop starting HydraBuddy automatically")
    # Used by the scheduled tasks and the watchdog (you don't need these yourself):
    p.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--keepalive", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--restarted", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def should_start(args, exit_flag=EXIT_FLAG_FILE):
    """Decide whether this launch should run, based on why it was started."""
    if args.keepalive:
        return not Path(exit_flag).exists()      # you clicked Exit: respect it until next sign-in
    try:
        Path(exit_flag).unlink(missing_ok=True)  # sign-in or started by hand: forget the old Exit
    except OSError:
        pass
    return True


def main(argv=None):
    args = parse_args(argv)

    if args.install_startup:
        names = install_startup()
        print("Done! HydraBuddy will start when you sign in and come back after you unlock.\n"
              f"Scheduled tasks: {', '.join(names)}")
        return 0
    if args.remove_startup:
        removed = remove_startup()
        print("Automatic start removed." if removed else "Automatic start was not set up.")
        return 0

    if not should_start(args):
        return 0

    interval = snooze = None
    if args.test:
        interval, snooze = TEST_INTERVAL_SECONDS, TEST_SNOOZE_SECONDS
    elif args.interval_seconds:
        interval = max(5, args.interval_seconds)

    enable_dpi_awareness()

    # A restarted copy waits a moment for the frozen one to finish closing.
    deadline = time.monotonic() + (20 if args.restarted else 0)
    while not acquire_single_instance():
        if time.monotonic() < deadline:
            time.sleep(0.5)
            continue
        if args.minimized:
            return 0                              # started automatically: already running, all good
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "HydraBuddy is already running.\n\n"
                                      "Look for its icon in the system tray or on the taskbar.")
        root.destroy()
        return 1

    why = ("sign-in" if args.autostart else "unlock / keep-alive" if args.keepalive
           else "restart after freeze" if args.restarted else "started by hand")
    log_error(f"HydraBuddy started ({why}).")
    settings, problems = load_settings()
    root = tk.Tk()
    try:
        app = HydraBuddyApp(root, settings, interval_seconds=interval, snooze_seconds=snooze,
                            use_tray=not args.no_tray, start_minimized=args.minimized,
                            exit_flag_path=EXIT_FLAG_FILE)
        app.watchdog = Watchdog()
        app.watchdog.start()
        for problem in problems:
            app.report_problem(problem)
        root.mainloop()
        if not app.closed:
            log_error("HydraBuddy stopped (window closed).")
    except Exception:
        log_error(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
