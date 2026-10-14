"""
Automated tests for HydraBuddy.

Run them with:
    py -m unittest -v test_hydra_buddy.py

Most tests use a "fake clock" so 20 minutes can pass instantly.
One test uses the real clock with a 2-second interval.
Tests never touch your real settings.json or Startup folder: they use a
temporary folder that is deleted afterwards.
"""

import array
import copy
import io
import json
import tempfile
import time
import tkinter as tk
import unittest
import wave
from pathlib import Path

import hydra_buddy as hb

hb.play_reminder_sound = lambda volume=0.6: None     # keep the test run quiet
hb.log_error = lambda text: None                     # tests trigger errors on purpose; don't log them


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------
class TimerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.timer = hb.ReminderTimer(1200, self.clock)
        self.timer.start()

    def test_not_due_before_interval(self):
        self.clock.advance(1199)
        self.assertFalse(self.timer.check_due())
        self.assertAlmostEqual(self.timer.remaining(), 1)

    def test_due_exactly_once(self):
        self.clock.advance(1200)
        self.assertTrue(self.timer.check_due())
        self.assertFalse(self.timer.check_due())        # no duplicate reminders
        self.assertEqual(self.timer.state, hb.ReminderTimer.WAITING)

    def test_pause_freezes_remaining_time(self):
        self.clock.advance(200)
        self.timer.pause()
        self.clock.advance(5000)                       # time passes while paused
        self.assertFalse(self.timer.check_due())
        self.assertAlmostEqual(self.timer.remaining(), 1000)
        self.timer.resume()
        self.clock.advance(999)
        self.assertFalse(self.timer.check_due())
        self.clock.advance(1)
        self.assertTrue(self.timer.check_due())

    def test_countdown_format(self):
        self.assertEqual(hb.format_countdown(1200), "20:00")
        self.assertEqual(hb.format_countdown(75.2), "01:16")
        self.assertEqual(hb.format_countdown(-3), "00:00")
        self.assertEqual(hb.nice_duration(1200), "20 minutes")
        self.assertEqual(hb.nice_duration(30), "30 seconds")


# ---------------------------------------------------------------------------
class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_missing_file_gives_defaults(self):
        settings, problems = hb.load_settings(self.path)
        self.assertEqual(settings, hb.DEFAULT_SETTINGS)
        self.assertEqual(problems, [])

    def test_broken_json_gives_defaults_and_a_message(self):
        self.write('{"interval_minutes": 30,,}')
        settings, problems = hb.load_settings(self.path)
        self.assertEqual(settings, hb.DEFAULT_SETTINGS)
        self.assertEqual(len(problems), 1)
        self.assertIn("Could not read", problems[0])

    def test_partial_file_keeps_other_defaults(self):
        self.write(json.dumps({"interval_minutes": 30, "theme": "dark",
                               "reminders": {"move": {"enabled": False}}}))
        settings, problems = hb.load_settings(self.path)
        self.assertEqual(problems, [])
        self.assertEqual(settings["interval_minutes"], 30)
        self.assertEqual(settings["theme"], "dark")
        self.assertFalse(settings["reminders"]["move"]["enabled"])
        self.assertEqual(settings["reminders"]["move"]["title"], "Stand & Sit")
        self.assertTrue(settings["sound_enabled"])

    def test_bad_values_are_fixed_with_explanations(self):
        self.write(json.dumps({"interval_minutes": 0, "sound_volume": 5, "sound_enabled": "yes",
                               "theme": "rainbow", "favourite_food": "pizza", "heading": 42}))
        settings, problems = hb.load_settings(self.path)
        self.assertEqual(settings["interval_minutes"], 1)       # clamped to the minimum
        self.assertEqual(settings["sound_volume"], 1.0)         # clamped to the maximum
        self.assertTrue(settings["sound_enabled"])              # wrong type -> default
        self.assertEqual(settings["theme"], "cute")
        self.assertEqual(settings["heading"], hb.DEFAULT_SETTINGS["heading"])
        self.assertEqual(len(problems), 6)

    def test_all_reminders_off_switches_them_back_on(self):
        self.write(json.dumps({"reminders": {r: {"enabled": False} for r in hb.REMINDER_ORDER}}))
        settings, problems = hb.load_settings(self.path)
        self.assertTrue(all(r["enabled"] for r in settings["reminders"].values()))
        self.assertEqual(len(problems), 1)

    def test_comment_keys_are_allowed(self):
        self.write(json.dumps({"_comment": "my settings", "interval_minutes": 45}))
        settings, problems = hb.load_settings(self.path)
        self.assertEqual(problems, [])
        self.assertEqual(settings["interval_minutes"], 45)

    def test_save_and_load_round_trip(self):
        settings = copy.deepcopy(hb.DEFAULT_SETTINGS)
        settings["heading"] = "Pause & breathe ✨"
        settings["colors"] = {"primary": "#ff6699"}
        hb.save_settings(settings, self.path)
        loaded, problems = hb.load_settings(self.path)
        self.assertEqual(loaded, settings)
        self.assertEqual(problems, [])
        self.assertFalse(self.path.with_name("settings.json.tmp").exists())

    def test_seconds_placeholder(self):
        settings = copy.deepcopy(hb.DEFAULT_SETTINGS)
        settings["eye_break_seconds"] = 30
        self.assertEqual(hb.reminder_text(settings, "look_far", "title"), "Look Far — 30 Seconds")

    def test_example_file_matches_defaults(self):
        example = Path(hb.__file__).with_name("settings.example.json")
        self.assertEqual(json.loads(example.read_text(encoding="utf-8")), hb.DEFAULT_SETTINGS)

    def test_every_theme_has_every_colour(self):
        keys = set(hb.THEMES["cute"])
        for name, theme in hb.THEMES.items():
            self.assertEqual(set(theme), keys, name)


# ---------------------------------------------------------------------------
class AppTestBase(unittest.TestCase):
    """Starts the real Tkinter app with a fake clock and a temporary folder."""

    settings_override = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.clock = FakeClock()
        self.locked = False
        self.root = tk.Tk()
        self.root.withdraw()
        settings = hb.validate_settings(self.settings_override or {}, [])
        self.app = hb.HydraBuddyApp(self.root, settings, use_tray=False, clock=self.clock,
                                    auto_tick=False, lock_check=lambda: self.locked,
                                    settings_path=self.folder / "settings.json",
                                    startup_folder_path=self.folder)

    def tearDown(self):
        self.app.exit_app()
        self.tmp.cleanup()

    def popups(self):
        return [w for w in self.root.winfo_children()
                if isinstance(w, tk.Toplevel) and w.title() == "HydraBuddy reminder"]


class AppTests(AppTestBase):
    def test_first_reminder_after_interval(self):
        self.clock.advance(1199)
        self.app.tick()
        self.assertFalse(self.app.popup_is_open())
        self.clock.advance(1)
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())
        self.assertEqual(self.app.countdown_text.get(), "Now")

    def test_no_duplicate_popups(self):
        self.app.show_reminder()
        self.app.show_reminder()
        self.clock.advance(5000)
        self.app.tick()
        self.root.update()
        self.assertEqual(len(self.popups()), 1)

    def test_popup_stays_until_dismissed(self):
        self.app.show_reminder()
        self.clock.advance(3600)                 # an hour later it is still there
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())

    def test_dismiss_starts_next_full_interval(self):
        self.clock.advance(1200)
        self.app.tick()
        self.app.dismiss_reminder()
        self.root.update()
        self.assertFalse(self.app.popup_is_open())
        self.assertEqual(len(self.popups()), 0)
        self.assertEqual(self.app.timer.state, hb.ReminderTimer.RUNNING)
        self.assertAlmostEqual(self.app.timer.remaining(), 1200)
        self.clock.advance(1200)
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())   # repeats

    def test_snooze(self):
        self.app.show_reminder()
        self.app.snooze_reminder()
        self.assertFalse(self.app.popup_is_open())
        self.assertAlmostEqual(self.app.timer.remaining(), 300)
        self.clock.advance(300)
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())

    def test_pause_and_resume(self):
        self.clock.advance(100)
        self.app.pause()
        self.assertEqual(self.app.pause_button["state"], "disabled")
        self.assertEqual(self.app.resume_button["state"], "normal")
        self.clock.advance(10_000)
        self.app.tick()
        self.assertFalse(self.app.popup_is_open())
        self.assertEqual(self.app.countdown_text.get(), "18:20")
        self.app.resume()
        self.clock.advance(1100)
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())

    def test_pause_closes_open_popup(self):
        self.app.show_reminder()
        self.app.pause()
        self.assertFalse(self.app.popup_is_open())
        self.assertEqual(self.app.timer.state, hb.ReminderTimer.PAUSED)

    def test_restart_interval(self):
        self.clock.advance(900)
        self.app.start_interval()
        self.assertAlmostEqual(self.app.timer.remaining(), 1200)

    def test_eye_timer_counts_down(self):
        self.app.show_reminder()
        popup = self.app.popup
        popup._start_eye_timer()
        self.assertIn("20s", popup.eye_button.text())

    def test_tray_thread_calls_are_run_on_tk_thread(self):
        self.app.post(self.app.show_reminder)
        self.app._process_calls()
        self.assertTrue(self.app.popup_is_open())

    def test_no_popup_while_locked(self):
        self.locked = True
        self.clock.advance(5000)
        self.app.tick()
        self.assertFalse(self.app.popup_is_open())

    def test_unlock_restarts_full_interval(self):
        self.clock.advance(1100)
        self.locked = True
        self.app.tick()
        self.clock.advance(3600)              # away for an hour
        self.app.tick()
        self.locked = False
        self.app.tick()                       # back at the laptop
        self.assertFalse(self.app.popup_is_open())
        self.assertAlmostEqual(self.app.timer.remaining(), 1200)
        self.clock.advance(1200)
        self.app.tick()
        self.assertTrue(self.app.popup_is_open())

    def test_unlock_closes_old_popup(self):
        self.app.show_reminder()
        self.locked = True
        self.app.tick()
        self.locked = False
        self.app.tick()
        self.assertFalse(self.app.popup_is_open())
        self.assertEqual(self.app.timer.state, hb.ReminderTimer.RUNNING)

    def test_unlock_keeps_pause(self):
        self.app.pause()
        self.locked = True
        self.app.tick()
        self.locked = False
        self.app.tick()
        self.assertEqual(self.app.timer.state, hb.ReminderTimer.PAUSED)

    def test_wake_from_sleep_restarts_interval(self):
        self.clock.advance(1150)
        self.app._last_loop_time -= 3600      # pretend the laptop slept for an hour
        self.app._tick_loop()
        self.assertFalse(self.app.popup_is_open())
        self.assertAlmostEqual(self.app.timer.remaining(), 1200)

    def test_default_popup_has_three_cards_and_three_buttons(self):
        self.app.show_reminder()
        self.assertEqual(self.app.popup.cards, ["water", "look_far", "move"])
        self.assertEqual([b.name for b in self.app.popup.buttons], ["eye", "done", "snooze"])

    def test_changing_interval_saves_and_restarts(self):
        self.clock.advance(500)
        self.app.set_interval_minutes(30)
        self.assertEqual(self.app.interval, 1800)
        self.assertAlmostEqual(self.app.timer.remaining(), 1800)
        saved = json.loads((self.folder / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["interval_minutes"], 30)

    def test_every_theme_draws(self):
        for name in hb.THEMES:
            self.app.set_theme(name)
            self.assertEqual(self.app.theme["bg"], hb.THEMES[name]["bg"])
            self.app.show_reminder()
            self.root.update()
            self.app.dismiss_reminder()
        saved = json.loads((self.folder / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], list(hb.THEMES)[-1])

    def test_startup_checkbox_creates_and_removes_shortcut(self):
        self.app.set_startup(True)
        self.assertTrue((self.folder / hb.STARTUP_SHORTCUT_NAME).exists())
        self.assertTrue(self.app.startup_var.get())
        self.app.set_startup(False)
        self.assertFalse((self.folder / hb.STARTUP_SHORTCUT_NAME).exists())
        self.assertFalse(self.app.startup_var.get())

    def test_reload_settings_from_file(self):
        (self.folder / "settings.json").write_text(json.dumps({"interval_minutes": 10, "theme": "dark"}))
        self.app.reload_settings()
        self.assertEqual(self.app.interval, 600)
        self.assertEqual(self.app.theme_box.get(), "dark")
        self.assertEqual(self.app.problems, [])

    def test_reload_reports_problems(self):
        (self.folder / "settings.json").write_text("not json")
        self.app.reload_settings()
        self.assertEqual(len(self.app.problems), 1)
        self.assertIn("Could not read", self.app.toast.text)

    def test_exit_cleans_up(self):
        self.app.show_reminder()
        self.app.exit_app()
        self.assertTrue(self.app.closed)
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()


class PersonalisedPopupTests(AppTestBase):
    settings_override = {
        "snooze_enabled": False,
        "eye_break_seconds": 30,
        "heading": "A very, very long personal heading that would never fit on one line of the pill",
        "reminders": {"look_far": {"enabled": False},
                      "water": {"text": "Long text. " * 30}},
        "colors": {"primary": "#ff6699", "bg": "not-a-colour"},
    }

    def test_disabled_reminder_and_snooze_are_left_out(self):
        self.app.show_reminder()
        self.assertEqual(self.app.popup.cards, ["water", "move"])
        self.assertEqual([b.name for b in self.app.popup.buttons], ["done"])
        self.assertIsNone(self.app.popup.eye_button)

    def test_custom_and_invalid_colours(self):
        self.assertEqual(self.app.theme["primary"], "#ff6699")
        self.assertEqual(self.app.theme["bg"], hb.THEMES["cute"]["bg"])     # invalid -> theme colour
        self.assertEqual(len(self.app.problems), 1)

    def test_long_texts_stay_inside_the_popup(self):
        self.app.show_reminder()
        popup = self.app.popup
        self.root.update()
        canvas_w = int(popup.canvas["width"])
        canvas_h = int(popup.canvas["height"])
        x1, y1, x2, y2 = popup.canvas.bbox("all")
        self.assertLessEqual(x2, canvas_w + 1)
        self.assertLessEqual(y2, canvas_h + 1)


class SmallScreenTest(AppTestBase):
    def test_popup_shrinks_to_fit_small_screen(self):
        original = hb.get_work_area
        hb.get_work_area = lambda root: (0, 0, 800, 480)
        try:
            self.app.show_reminder()
            w = int(self.app.popup.canvas["width"])
            h = int(self.app.popup.canvas["height"])
            self.assertLessEqual(w, 800 * 0.96)
            self.assertLessEqual(h, 480 * 0.96)
        finally:
            hb.get_work_area = original


class MascotImageTest(AppTestBase):
    def setUp(self):
        super().setUp()
        image = tk.PhotoImage(master=self.root, width=600, height=900)
        image.put("#88ccff", to=(0, 0, 600, 900))
        self.image_path = self.folder / "my_mascot.png"
        image.write(str(self.image_path), format="png")

    def test_custom_mascot_image_is_used_and_shrunk(self):
        self.app.settings["mascot_image"] = str(self.image_path)
        self.app.show_reminder()
        photo = self.app.popup._mascot_photo
        self.assertIsNotNone(photo)
        self.assertLessEqual(photo.height(), 400 * self.app.s)
        self.assertEqual(self.app.problems, [])

    def test_missing_mascot_image_falls_back(self):
        self.app.settings["mascot_image"] = "does_not_exist.png"
        self.app.show_reminder()
        self.assertIsNone(self.app.popup._mascot_photo)
        self.assertEqual(len(self.app.problems), 1)


# ---------------------------------------------------------------------------
class RealTimeTest(unittest.TestCase):
    def test_popup_appears_with_real_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = hb.HydraBuddyApp(root, interval_seconds=2, snooze_seconds=1, use_tray=False,
                                   lock_check=lambda: False, settings_path=Path(folder) / "s.json",
                                   startup_folder_path=folder)
            try:
                end = time.monotonic() + 3.5
                while time.monotonic() < end and not app.popup_is_open():
                    root.update()
                    time.sleep(0.05)
                self.assertTrue(app.popup_is_open(), "pop-up did not appear after 2 seconds")
            finally:
                app.exit_app()


class SoundTest(unittest.TestCase):
    def test_chime_is_a_valid_wav(self):
        data = hb.make_chime_wav(volume=0.6)
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            seconds = wav.getnframes() / wav.getframerate()
        self.assertAlmostEqual(seconds, 1.5, places=2)

    def test_volume_zero_is_silent(self):
        data = hb.make_chime_wav(volume=0.0)
        samples = array.array("h", data[44:])     # skip the 44-byte wav header
        self.assertEqual(max(abs(s) for s in samples), 0)

    def test_sound_off_means_no_sound(self):
        calls = []
        hb.play_reminder_sound = lambda volume=0.6: calls.append(volume)
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = tk.Tk()
                root.withdraw()
                settings = hb.validate_settings({"sound_enabled": False}, [])
                app = hb.HydraBuddyApp(root, settings, use_tray=False, auto_tick=False,
                                       lock_check=lambda: False, settings_path=Path(folder) / "s.json",
                                       startup_folder_path=folder)
                app.show_reminder()
                app.exit_app()
                self.assertEqual(calls, [])
        finally:
            hb.play_reminder_sound = lambda volume=0.6: None


class StartupShortcutTest(unittest.TestCase):
    def test_install_and_remove_in_temp_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = hb.install_startup(folder)
            self.assertTrue(Path(shortcut).exists())
            self.assertTrue(hb.is_startup_installed(folder))
            self.assertTrue(hb.remove_startup(folder))
            self.assertFalse(Path(shortcut).exists())
            self.assertFalse(hb.remove_startup(folder))


if __name__ == "__main__":
    unittest.main()
