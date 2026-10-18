# HydraBuddy: Developer Learning Guide

This guide explains how HydraBuddy works, one piece at a time, so you can explain it in an interview and change it confidently. Line numbers refer to [`hydra_buddy.py`](../hydra_buddy.py) at the time of writing. If they have shifted, search for the function name.

**The big picture in one sentence:** a Tkinter window runs a tiny check twice a second, and when a stored deadline has passed, it opens a borderless always-on-top window that is drawn on a canvas.

---

## 1. How the application starts

`main()` (line ~1532) runs when you type `py hydra_buddy.py`.

```python
args = parse_args(argv)                      # read --test, --minimized, ...
if args.test:
    interval, snooze = TEST_INTERVAL_SECONDS, TEST_SNOOZE_SECONDS
enable_dpi_awareness()                       # sharp text on scaled screens
if not acquire_single_instance():            # is HydraBuddy already open?
    messagebox.showinfo(...); return 1
settings, problems = load_settings()         # read + check settings.json
root = tk.Tk()
app = HydraBuddyApp(root, settings, interval_seconds=interval, ...)
root.mainloop()                              # hand control to Tkinter
```

In plain English:
1. Read the command-line options. `--test` means "every 30 seconds".
2. Tell Windows the app handles high-DPI screens itself, so text isn't blurry.
3. Make sure only one copy runs (see section 4).
4. Load `settings.json`, fixing anything invalid.
5. Build the app, then call `mainloop()`. From then on, Tkinter waits for events: clicks, and the timers we schedule with `after()`.

## 2. How the timer works

There are two parts: a **pure-Python timer object** with no GUI code, and a **loop** that checks it.

### `ReminderTimer` (line ~600)

```python
def start(self, seconds=None):
    seconds = self.interval if seconds is None else seconds
    self._deadline = self.clock() + seconds      # "remind me at this moment"
    self.state = self.RUNNING

def check_due(self):
    if self.state == self.RUNNING and self.clock() >= self._deadline:
        self.state = self.WAITING                # stop, wait for the user
        return True
    return False
```

- It stores a **deadline**, not a counter. That's more accurate than "subtract 1 every second", because a late check can't make the timer drift.
- `clock` is `time.monotonic` by default. That's a clock that never jumps when Windows changes the time, for example on a daylight-saving change. The tests pass in a **fake clock**, so "20 minutes later" takes no time at all.
- There are three **states**:
  - `running`: counting down.
  - `paused`: remembers how many seconds were left.
  - `waiting`: the pop-up is showing.
- `check_due()` returns True **once**, because it immediately switches to `waiting`. This is why duplicate pop-ups can't happen.

### The loop: `_tick_loop()` and `tick()` (lines ~1305–1340)

```python
def _tick_loop(self):
    now = time.monotonic()
    if now - self._last_loop_time > SLEEP_GAP_SECONDS:   # a 60-second gap...
        self.welcome_back()                              # ...means the laptop slept
    self._last_loop_time = now
    self.tick()
    self._tick_id = self.root.after(self.TICK_MS, self._tick_loop)   # again in 0.5 s
```

- `root.after(500, fn)` asks Tkinter to call `fn` in 500 ms. Nothing sleeps and nothing blocks, so the window stays responsive. This uses almost no CPU, because the work done each time is just a comparison of two numbers.
- There's only ever **one** scheduled call, because each run schedules exactly one next run. Its id is stored in `_tick_id` so `exit_app()` can cancel it.
- `tick()` first checks `is_screen_locked()`. While you're locked out, nothing pops up. When you come back, `welcome_back()` restarts a full interval.

## 3. How the pop-up is created and positioned

`ReminderPopup.__init__` (line ~666):

```python
self.win = tk.Toplevel(app.root)
win.overrideredirect(True)                   # no title bar or border
win.attributes("-topmost", True)             # stay above other windows
win.configure(bg=TRANSPARENT_KEY)
win.attributes("-transparentcolor", TRANSPARENT_KEY)   # that colour becomes see-through
```

- **Above other apps:** `-topmost` keeps it above normal windows. `_keep_on_top()` re-applies this every 5 seconds without taking keyboard focus, so typing in another app isn't interrupted.
- **Rounded corners:** the window's background is filled with an unusual magenta (`#ff00fe`), which Windows is told to make transparent. The visible card is a rounded rectangle drawn on top.
- **Drawing:** everything is drawn on a `tk.Canvas`: cards, icons, buttons, and the mascot. `rounded_rect()` uses a classic trick: a polygon with `smooth=True` and doubled corner points.
- **Layout from settings:** `_draw()` (line ~717) loops over the reminders that are switched on and calls `_card()` for each. Each card measures its text with `canvas.bbox()` and grows if your text is long.
- **Centring and fitting:** `get_work_area()` asks Windows for the screen size minus the taskbar. If the pop-up wouldn't fit, it's redrawn at a smaller scale, which is why fonts are sized in pixels via `self.font()`. Then it's centred with `win.geometry("WxH+X+Y")`.
- **Buttons:** `CanvasButton` is a rounded shape plus text, with `tag_bind` for hover and click.

## 4. How background operation works

- **Closing ≠ quitting.** `root.protocol("WM_DELETE_WINDOW", self.hide_to_background)` means the window's X button just hides the window: `withdraw()` if there's a tray icon, `iconify()` (minimise) if not. The `after()` loop keeps running, so reminders continue.
- **Only one copy:** `acquire_single_instance()` creates a Windows *named mutex* called `HydraBuddy_SingleInstance`. If Windows says the name already exists (error 183), another copy is running, so this one shows a message and exits.
- **Start with Windows:** `install_startup()` asks PowerShell to register two **scheduled tasks**. Both run `pythonw.exe` (Python without a console window) with `--minimized`:
  - `HydraBuddy` runs at sign-in (`--autostart`).
  - `HydraBuddy-KeepAlive` runs on every unlock and every 15 minutes (`--keepalive`).

  Both have no time limit (`PT0S`), so Windows never stops them after 3 days. Both also run on battery. `should_start()` decides what each launch does:
  - A keep-alive launch stays away if you clicked **Exit** (the `.exited-by-user` file).
  - A sign-in clears that file.
  - If HydraBuddy is already running, a background launch quietly quits.

  *Why not the Startup folder?* It only runs at a full sign-in. Waking a laptop from sleep isn't a sign-in, so once the app was closed, it never came back.
- **Watchdog:** `Watchdog` is a background thread that checks a *heartbeat*, which `_tick_loop()` updates twice a second. If there's no heartbeat for 60 seconds while the laptop is awake, the app is frozen. The watchdog then:
  1. Writes every thread's current line to `hydra_buddy.log` (`faulthandler.dump_traceback`).
  2. Starts a fresh copy with `--restarted`, which waits for the old copy to finish.
  3. Ends the frozen copy.

  Sleep is detected by a big jump in the wall clock, so a sleeping laptop isn't mistaken for a frozen app.
- **Windows shutdown:** `root.protocol("WM_SAVE_YOURSELF", ...)` closes the app as soon as Windows asks, so it never holds up shutdown.
- **Tray icon (optional):** `pystray` needs its own thread. Tkinter must only be touched from its own thread, so tray clicks call `app.post(func)`, which puts `func` on a `queue.Queue`. `_process_calls()` (run by `after()` every 200 ms) takes jobs off the queue and runs them safely.
- **Sound:** `make_chime_wav()` calculates three fading sine waves (C, E, G) and packs them into WAV bytes. `winsound.PlaySound` plays them on a helper thread, so the window doesn't freeze for 1.5 seconds. Windows applies your system volume on top.

## 5. How settings and customisation work

- `DEFAULT_SETTINGS` (top of the file) holds every setting. `settings.example.json` is an exact copy, and a test checks that they match.
- `load_settings()` reads `settings.json`. Then `validate_settings()` (line ~177) starts from a **copy of the defaults** and only accepts values from your file if they have the right type and range. Everything else is replaced and explained in a `problems` list. A broken file therefore can't crash the app, and `report_problem()` shows each message in the corner.
- `save_settings()` writes to `settings.json.tmp` first, then swaps it in with `os.replace()`. If the computer crashes mid-save, you never end up with half a file.
- **Themes** are dictionaries of colours in `THEMES`. `_make_theme()` copies the chosen one and applies your `colors` overrides. Each override is checked with `root.winfo_rgb()`, which raises an error for anything that isn't a real colour.
- Changing something in the main window calls `set_theme()`, `set_interval_minutes()` and so on. Each one saves the file and calls `apply_settings()`, which rebuilds the main window in the new theme. The next pop-up uses the new settings.

## 6. How closing and cleanup work

`exit_app()` (line ~1439):

```python
self.closed = True
for after_id in (self._tick_id, self._queue_id):
    self.root.after_cancel(after_id)         # stop the scheduled loops
self._close_popup()                          # the pop-up also cancels its own after() calls
self.toast.close()
self.tray.stop()
self.root.destroy()
```

- Every repeating `after()` id is stored and cancelled, so nothing fires after the window is gone.
- `ReminderPopup.close()` cancels its own timers: the "keep on top" loop and the eye countdown.
- `closed = True` makes late calls (for example from the tray thread) do nothing.
- The mutex is released automatically when the process ends.

What each button does to the timer:

| Action | Timer effect |
|---|---|
| **Done** / ✕ / `Esc` / `Enter` | Closes the pop-up and starts a full new interval |
| **Snooze** | Closes the pop-up and starts a `snooze_minutes` countdown |
| **Pause** | Closes any pop-up and freezes the remaining time |
| **Resume** | Continues from the frozen time |
| **Start / Restart** | Starts a fresh full interval |
| Lock, then unlock / sleep, then wake | Closes any pop-up and starts a fresh full interval (unless paused) |
| Close the main window | Nothing: the timer keeps running in the background |
| **Exit** | Everything stops. It stays closed until your next sign-in (keep-alive launches respect this) |
| Windows shuts down or signs out | Closes immediately |
| The window freezes for 60 s | The watchdog logs why, starts a fresh copy, and ends the frozen one |

## 7. How to test without waiting 20 minutes

- **By hand:** `py hydra_buddy.py --test` (a reminder every 30 seconds, snooze 10 seconds). Or click **Remind me now**.
- **Automated:** `py -m unittest -v test_hydra_buddy.py` runs 55 tests.
  - `FakeClock` replaces `time.monotonic`. Calling `self.clock.advance(1200)` "waits" 20 minutes instantly.
  - `lock_check=lambda: self.locked` lets a test pretend the laptop is locked.
  - `settings_path` and `startup_folder_path` point to a temporary folder, so tests never touch your real files.
  - One test, `RealTimeTest`, uses the real clock with a 2-second interval, to prove the real `after()` loop works.

---

## 10 likely interview questions

1. **Why store a deadline instead of counting down every second?**
   A countdown that subtracts 1 per tick drifts if a tick is late. Comparing `now >= deadline` is always correct, and pausing just saves `deadline - now`.

2. **Why `time.monotonic()` instead of `time.time()`?**
   `time.time()` can jump when the system clock changes, for example through time sync or daylight saving. `monotonic()` only ever moves forward, so it's the right choice for measuring durations.

3. **How do you avoid freezing the GUI?**
   I never call `time.sleep()` in the GUI thread. Tkinter's `after()` schedules short checks, and the sound plays on a helper thread.

4. **How do you guarantee there's never more than one pop-up or timer?**
   `check_due()` switches to `waiting` the moment it fires, `show_reminder()` returns early if a pop-up is already open, and only one `after()` id is ever scheduled. Tests check all three.

5. **How does the pop-up stay on top without stealing focus?**
   The `-topmost` attribute plus a periodic `lift()`. I don't call `focus_force()` on the pop-up, so whatever you're typing in keeps the keyboard.

6. **How are the rounded corners made in Tkinter?**
   The window background uses a colour that Windows is told to treat as transparent (`-transparentcolor`). A smooth polygon draws the rounded card on top of it.

7. **Tkinter isn't thread-safe. How does the tray icon talk to it?**
   The tray runs in its own thread and only puts functions on a `queue.Queue`. The Tkinter thread empties the queue every 200 ms and runs them.

8. **What happens if the user writes invalid JSON or bad values in `settings.json`?**
   The app starts from the defaults and accepts only values of the right type and range. Everything else is replaced and reported in plain English. Saving goes through a temp file plus `os.replace()`, so the file is never half-written.

9. **How do you detect that the user is away?**
   When the screen is locked, `OpenInputDesktop` fails. A gap of more than 60 seconds between the 0.5-second checks means the process was suspended, i.e. the laptop slept. Either way, the countdown restarts.

10. **How did you test time-based behaviour?**
    By *dependency injection*: the timer takes a `clock` function. In tests it's a fake clock I can move forward instantly, and the lock check and file locations can be replaced too. One extra test uses the real clock to make sure the real loop works.

**Good follow-up answers to have ready:**
- *What would you change next?* Multi-monitor support, screen-reader-friendly pop-ups, or packaging as an `.exe` with PyInstaller.
- *Why one file?* For a beginner-friendly tool, one file is easy to read, download and modify. If it grew, I'd split it into `timer.py`, `settings.py`, `ui.py` and so on.

---

## Who did what: an honest record

Keep this up to date, and only tick the boxes in the last section when they're true.

**What I (the author) did**
- Noticed the problem and decided what the app should do: three specific reminders, offline, a cute character, a 20-minute interval, background running, starting with Windows, and sound.
- Wrote the requirements and prompts for Claude Code, and chose which features to add.
- Ran the app on my own laptop and reported real problems. For example, I couldn't hear the sound, and I wanted the countdown to start only once I'm back at the laptop.
- Decided to publish it, and wrote the motivation and story.

**What Claude Code generated**
- Nearly all of the Python code, the 55 tests, the screenshot script, the README, this guide, and the first drafts of the LinkedIn posts.
- The diagnosis of the sound issue: Windows was sending audio to an external HDMI display.
- The verification runs: the test suite, real-time runs in test mode, and screenshots of the real app.

**What I have personally verified** (tick each one only after doing it yourself)

Before starting, exit the background copy (tray icon → *Exit HydraBuddy*, or the **Exit** button). Then open PowerShell in the HydraBuddy folder.

| # | Do this | You should see |
|---|---|---|
| ☐ 1 | `py -m unittest -v test_hydra_buddy.py` | `Ran 55 tests` … `OK` |
| ☐ 2 | `py hydra_buddy.py --test` | The main window, counting down from 00:30 |
| ☐ 3 | Wait 30 seconds, working in another app | The pop-up appears in the centre, above your other app, with the chime |
| ☐ 4 | Click **Look far: start 20s** | The button counts down 20 → 1, then shows "Eyes relaxed ✓" |
| ☐ 5 | Click **Done** | The pop-up closes, and a corner message says "Next reminder in 30 seconds" |
| ☐ 6 | Wait for the next pop-up, then click **Snooze** | It comes back about 10 seconds later |
| ☐ 7 | Click **Pause**, wait 1 minute, click **Resume** | The countdown froze and continues where it stopped |
| ☐ 8 | Close the main window with ✕ | It disappears, but the pop-up still comes (it's running in the background) |
| ☐ 9 | Change **Theme** to *dark*, then click **Remind me now** | The dark pop-up |
| ☐ 10 | **Edit settings file** → change `"heading"` → save → **Reload settings** → **Remind me now** | Your own heading |
| ☐ 11 | Put `"interval_minutes": "abc"` in the file → **Reload settings** | A message explains the mistake, and the app keeps working |
| ☐ 12 | Press `Win + L` while it's running, then unlock | "Welcome back!" message; the countdown restarts |
| ☐ 13 | Run `py hydra_buddy.py --test` a second time while it's open | "HydraBuddy is already running" |
| ☐ 14 | Restart the laptop (with **Start with Windows** ticked) | HydraBuddy starts by itself in the tray/taskbar |
| ☐ 14b | Right-click the tray icon → *Exit*, lock with `Win + L`, unlock | It stays closed (you chose Exit). After your next sign-in, it's back |
| ☐ 15 | Click **Exit** | Everything closes: window, tray icon and pop-ups |
| ☐ 16 | Explain sections 2, 3 and 4 of this guide out loud without reading | You can 🙂 |

Afterwards, remove any test settings you don't want to keep: delete `settings.json`, or fix it in Notepad.
