"""
Capture the README screenshots from the real running app.

    py tools/capture_screenshots.py

Needs Pillow (py -m pip install pillow). Images are saved in docs/images/.
A plain coloured backdrop is placed behind each window, so nothing else on
your screen ends up in the pictures. Your own settings.json is not used
or changed: the screenshots always show the default settings.
"""

import copy
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import hydra_buddy as hb  # noqa: E402

OUT = ROOT / "docs" / "images"
BACKDROP = "#e9e4f5"
MARGIN = 28


def settle(root, seconds=0.5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


def grab_window(root, win, name):
    """Screenshot `win` on a plain backdrop and save it as docs/images/<name>.png."""
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    m = int(MARGIN * root.winfo_fpixels("1i") / 96)
    backdrop = tk.Toplevel(root)
    backdrop.overrideredirect(True)
    backdrop.attributes("-topmost", True)
    backdrop.configure(bg=BACKDROP)
    backdrop.geometry(f"{w + 2 * m}x{h + 2 * m}+{x - m}+{y - m}")
    settle(root, 0.2)
    win.attributes("-topmost", True)
    win.lift()
    settle(root, 0.5)
    image = ImageGrab.grab(bbox=(x - m, y - m, x + w + m, y + h + m), all_screens=True)
    backdrop.destroy()
    path = OUT / f"{name}.png"
    image.save(path)
    print("saved", path.relative_to(ROOT))
    return image


def make_app(root, settings, folder):
    return hb.HydraBuddyApp(root, settings, use_tray=False, auto_tick=False,
                            lock_check=lambda: False, settings_path=Path(folder) / "settings.json",
                            startup_folder_path=folder)


def make_banner(popup_image):
    """1280x640 banner (GitHub social preview size) built from a real screenshot."""
    banner = Image.new("RGB", (1280, 640), BACKDROP)     # same colour as the screenshot backdrop
    draw = ImageDraw.Draw(banner)
    fonts = Path("C:/Windows/Fonts")
    title = ImageFont.truetype(str(fonts / "segoeuib.ttf"), 72)
    text = ImageFont.truetype(str(fonts / "segoeui.ttf"), 28)
    small = ImageFont.truetype(str(fonts / "segoeui.ttf"), 22)
    draw.text((64, 180), "HydraBuddy", font=title, fill="#4b3399")
    draw.text((68, 280), "A tiny offline break reminder", font=text, fill="#2f2a3b")
    draw.text((68, 322), "Drink water \u00b7 Look far \u00b7 Stand & sit", font=text, fill="#5f566e")
    draw.text((68, 400), "Python + Tkinter \u00b7 Windows", font=small, fill="#6a6078")
    draw.text((68, 432), "Works offline", font=small, fill="#6a6078")
    shot = popup_image.copy()
    shot.thumbnail((700, 600))
    banner.paste(shot, (1280 - shot.width - 20, (640 - shot.height) // 2))
    banner.save(OUT / "banner.png")
    print("saved", (OUT / "banner.png").relative_to(ROOT))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hb.enable_dpi_awareness()
    hb.play_reminder_sound = lambda volume=0.6: None       # no sound while capturing
    folder = tempfile.mkdtemp()
    root = tk.Tk()
    settings = copy.deepcopy(hb.DEFAULT_SETTINGS)
    app = make_app(root, settings, folder)

    # Main window
    settle(root)
    grab_window(root, root, "main-window")
    root.withdraw()

    # The pop-up in every theme (+ an animated GIF that cycles through them)
    frames = []
    for theme in hb.THEMES:
        settings["theme"] = theme
        app.apply_settings(settings)
        app.show_reminder()
        settle(root)
        image = grab_window(root, app.popup.win, f"popup-{theme}")
        frames.append(image)
        if theme == "cute":
            cute = image
        app.dismiss_reminder()
        settle(root, 0.2)

    size = frames[0].size
    gif_frames = [f.resize(size).convert("P", palette=Image.ADAPTIVE) for f in frames]
    gif_frames[0].save(OUT / "themes.gif", save_all=True, append_images=gif_frames[1:],
                       duration=1800, loop=0)
    print("saved", (OUT / "themes.gif").relative_to(ROOT))

    # Eye-break countdown running
    settings["theme"] = "cute"
    app.apply_settings(settings)
    app.show_reminder()
    app.popup._start_eye_timer()
    settle(root, 2.2)
    grab_window(root, app.popup.win, "eye-countdown")
    app.dismiss_reminder()

    # The corner message shown after "Done"
    settle(root, 0.3)
    grab_window(root, app.toast.win, "toast")
    app.toast.close()

    # A personalised example: own texts, own colours, two reminders, no snooze
    custom = hb.validate_settings({
        "theme": "productivity",
        "heading": "Quick reset before the next task",
        "subheading": "Two small things",
        "closing_message": "Back to it in a minute!",
        "snooze_enabled": False,
        "reminders": {"look_far": {"enabled": False},
                      "water": {"title": "Refill your bottle", "text": "Walk to the kitchen and refill it."}},
        "colors": {"primary": "#e11d48", "primary_hover": "#be123c", "pill": "#ffe4e6", "pill_text": "#9f1239"},
    }, [])
    app.apply_settings(custom)
    app.show_reminder()
    settle(root)
    grab_window(root, app.popup.win, "popup-personalised")
    app.dismiss_reminder()

    make_banner(cute)
    app.exit_app()


if __name__ == "__main__":
    main()
