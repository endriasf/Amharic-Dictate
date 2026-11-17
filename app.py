"""
Amharic Dictate — offline, system-wide Amharic dictation for Windows.

Press the hotkey, speak Amharic, watch the live transcript in the overlay,
press the hotkey again: the text is pasted into the app you're working in.
All speech is processed on this computer.
"""

import os
import queue
import sys
import threading
import time
import traceback

from config import (APP_NAME, APP_VERSION, app_dir, load_config, log_error, save_config,
                    set_start_with_windows)

RELOAD_KEYS = ("model", "device", "quantize_cpu", "auto_level", "lm_decoding", "lm_weight", "fast_preview", "profile")


# --------------------------------------------------------------------------
# Windows helpers
# --------------------------------------------------------------------------
def single_instance() -> bool:
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}Mutex")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def beep(freq: int, ms: int = 70):
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()
    except Exception:
        pass


def wait_modifiers_released(timeout=1.5):
    import keyboard
    end = time.time() + timeout
    while time.time() < end and any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift", "windows")):
        time.sleep(0.03)


def set_clipboard_private(text: str) -> bool:
    """Put text on the clipboard, marked so Windows keeps it out of clipboard history and cloud sync."""
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalAlloc.restype = wintypes.HGLOBAL
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u32.SetClipboardData.restype = wintypes.HANDLE
        u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        u32.RegisterClipboardFormatW.restype = wintypes.UINT
        u32.OpenClipboard.argtypes = [wintypes.HWND]

        def put(fmt, data: bytes):
            h = k32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
            ptr = k32.GlobalLock(h)
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(h)
            if not u32.SetClipboardData(fmt, h):
                raise OSError("SetClipboardData failed")

        for _ in range(10):                                 # another app may hold the clipboard briefly
            if u32.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            return False
        try:
            u32.EmptyClipboard()
            put(13, (text + "\0").encode("utf-16-le"))    # CF_UNICODETEXT
            zero = (0).to_bytes(4, "little")
            put(u32.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), zero)
            put(u32.RegisterClipboardFormatW("CanUploadToCloudClipboard"), zero)
        finally:
            u32.CloseClipboard()
        return True
    except Exception:
        return False


def paste_text(text: str):
    """Paste via the clipboard (reliable for Ethiopic script).

    The dictated text is left on the clipboard afterwards, so if an app is slow to
    paste (Word can be), nothing is lost: the user can press Ctrl+V themselves.
    """
    import keyboard
    import pyperclip
    wait_modifiers_released()
    data = text.replace("\n", "\r\n")
    for _ in range(3):                    # make sure the clipboard really holds our text
        if not set_clipboard_private(data):
            pyperclip.copy(data)
        time.sleep(0.05)
        try:
            if pyperclip.paste() == data:
                break
        except Exception:
            pass
    time.sleep(0.1)
    keyboard.send("ctrl+v")


def make_no_activate(tk_win):
    """Keep the overlay from stealing focus from the app being dictated into."""
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.GetParent(tk_win.winfo_id())
        style = u.GetWindowLongW(hwnd, -20)
        u.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080 | 0x00000008)
    except Exception:
        pass


def tray_image(state: str):
    from PIL import Image, ImageDraw
    colors = {"ready": (40, 140, 90), "active": (220, 50, 50), "busy": (150, 150, 150),
              "paused": (230, 160, 30)}
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=colors.get(state, colors["busy"]))
    d.rounded_rectangle((25, 14, 39, 38), radius=7, fill="white")
    d.arc((19, 24, 45, 46), 0, 180, fill="white", width=3)
    d.line((32, 46, 32, 52), fill="white", width=3)
    return img


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
class App:
    def __init__(self):
        import tkinter as tk

        self.cfg = load_config()
        self.ui_q: "queue.Queue[tuple]" = queue.Queue()
        self.engine = None
        self.stream = None
        self._mic_users = set()
        self._mic_lock = threading.Lock()
        self.active = False
        self.loading = False
        self._toggle_lock = threading.Lock()
        self._settings_win = None
        self._session_hotkeys = []
        self.recorder_tap = None          # set by the voice-training window to receive mic audio
        self._train_win = None
        self.word = None                  # live link to a Word document while dictating into Word
        self._moving = False

        # ---- overlay
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        bg = "#1e1e1e"
        self.root.configure(bg=bg)
        frame = tk.Frame(self.root, bg=bg, padx=16, pady=10)
        frame.pack(fill="both", expand=True)
        top = tk.Frame(frame, bg=bg)
        top.pack(fill="x")
        self.status = tk.Label(top, text="", fg="#9aa0a6", bg=bg, font=("Segoe UI", 9), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        mini_btn = tk.Label(top, text="—", fg="#c8c8c8", bg="#3a3a3a", font=("Segoe UI", 10, "bold"),
                            padx=9, pady=0, cursor="hand2")
        mini_btn.pack(side="right", padx=(10, 0))
        mini_btn.bind("<Button-1>", lambda e: self.minimize())
        mini_btn.bind("<Enter>", lambda e: mini_btn.config(bg="#555"))
        mini_btn.bind("<Leave>", lambda e: mini_btn.config(bg="#3a3a3a"))
        self.meter = tk.Canvas(top, width=80, height=8, bg="#333", highlightthickness=0)
        self.meter.pack(side="right")
        self.meter_bar = self.meter.create_rectangle(0, 0, 0, 8, fill="#3ddc84", width=0)
        # Read-only Text widget: wraps long dictation and auto-scrolls to the newest words
        self.text = tk.Text(frame, fg="white", bg=bg, wrap="word", height=3, bd=0, highlightthickness=0,
                            cursor="arrow", takefocus=0, padx=0, pady=4, spacing1=2)
        self.text.pack(fill="both", expand=True)
        self.text.config(state="disabled")

        self.text.tag_configure("unsure", foreground="#ffc266", underline=True)
        self.text.tag_configure("gap", foreground="#4fc3f7")
        self.text.tag_configure("selected", background="#2f6fd6", foreground="white")
        self.text.tag_configure("misspelled", foreground="#ff7b7b", underline=True)
        self._spell_cache = {}

        # Suggestion row: shown after clicking a word
        self.sugg = tk.Frame(frame, bg=bg)
        top = tk.Frame(self.sugg, bg=bg)
        top.pack(fill="x")
        self.sugg_title = tk.Label(top, text="", fg="#9aa0a6", bg=bg, font=("Segoe UI", 9))
        self.sugg_title.pack(side="left", padx=(0, 6))
        self.sugg_chips = tk.Frame(top, bg=bg)           # suggested words
        self.sugg_chips.pack(side="left")
        row2 = tk.Frame(self.sugg, bg=bg)
        row2.pack(fill="x", pady=(3, 0))
        self.sugg_actions = tk.Frame(row2, bg=bg)        # Remove / Join / Insert…
        self.sugg_actions.pack(side="left")
        keep = tk.Label(row2, text="✕ Keep original", fg="white", bg="#3a3a3a", font=("Segoe UI", 9),
                        padx=8, pady=2, cursor="hand2")
        keep.pack(side="right")
        keep.bind("<Button-1>", lambda e: self._suggestion_chosen(None))

        # Button bar (shown while dictating). Labels instead of tk.Button so clicks never take focus
        # away from the app being dictated into.
        self.bar = tk.Frame(frame, bg=bg)
        bar_left = tk.Frame(self.bar, bg=bg)
        bar_left.pack(side="left")
        bar_right = tk.Frame(self.bar, bg=bg)
        bar_right.pack(side="right")
        bar_mid = tk.Frame(self.bar, bg=bg)
        bar_mid.pack(side="left", expand=True)
        self.buttons = {}
        for key, label, cmd, color in (
            ("undo",   "↶ Undo",         self.undo,         "#3a3a3a"),
            ("pause",  "⏸ Pause",        self.toggle_pause, "#3a3a3a"),
            ("delete", "⌫ Delete word",  self.delete_word,  "#3a3a3a"),
            ("copy",   "⧉ Copy",         self.copy_text,    "#3a3a3a"),
            ("cancel", "✕ Cancel",       self.cancel,       "#5a2a2a"),
            ("done",   "✓ Done",         self.toggle,       "#1f6f4a"),
        ):
            parent = bar_right if key in ("done", "cancel") else bar_left
            b = tk.Label(parent, text=label, fg="white", bg=color, font=("Segoe UI", 10),
                         padx=10, pady=4, cursor="hand2")
            b.pack(side="left", padx=(0, 6) if parent is bar_left else (6, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.config(bg="#555"))
            b.bind("<Leave>", lambda e, w=b, c=color: w.config(bg=c))
            self.buttons[key] = b

        # punctuation buttons (more reliable than saying the command)
        for mark in ("።", "፣", "፤", "?", "!", "«", "»", "(", ")"):
            pb = tk.Label(bar_mid, text=mark, fg="white", bg="#2f3b4a", font=("Nyala", 14, "bold"),
                          width=2, cursor="hand2")
            pb.pack(side="left", padx=2)
            pb.bind("<Button-1>", lambda e, m=mark: self.engine and self.active and self.engine.add_punctuation(m))
            pb.bind("<Enter>", lambda e, w=pb: w.config(bg="#555"))
            pb.bind("<Leave>", lambda e, w=pb: w.config(bg="#2f3b4a"))

        # click a word to remove it; the next thing you say replaces it
        self.text.bind("<Button-1>", self._on_text_click)

        # drag the box by its status line
        for w in (self.status, top):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        self._apply_font()
        self._place_overlay()
        self.root.update_idletasks()
        make_no_activate(self.root)
        self._build_mini(bg)

        # ---- tray
        import pystray
        self.tray = pystray.Icon(
            APP_NAME, tray_image("busy"), f"{APP_NAME} (loading…)",
            menu=pystray.Menu(
                pystray.MenuItem("Start / stop dictation", lambda: self.toggle(), default=True),
                pystray.MenuItem("Pause / resume", lambda: self.toggle_pause()),
                pystray.MenuItem("Show dictation box", lambda: self.ui_q.put(("restore",))),
                pystray.MenuItem("Delete last word", lambda: self.delete_word()),
                pystray.MenuItem("Settings…", lambda: self.ui_q.put(("settings",))),
                pystray.MenuItem("Voice profiles…", lambda: self.ui_q.put(("train",))),
                pystray.MenuItem("Check Amharic spelling in Word…", lambda: self.ui_q.put(("spell",))),
                pystray.MenuItem("Open history", lambda: self._open_file("history.txt")),
                pystray.MenuItem("Open log", lambda: self._open_file("error.log")),
                pystray.MenuItem(f"Quit {APP_NAME}", lambda: self.quit()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("About…", lambda: self.ui_q.put(("about",))),
            ),
        )
        self.tray.run_detached()

        try:
            self.ensure_profile()
        except Exception:
            log_error(traceback.format_exc())
        self._reload_model()
        self.root.after(50, self._pump_ui)

    # ---------- helpers
    def _apply_font(self):
        family = self.cfg["font"]
        try:
            from tkinter import font as tkfont
            if family not in tkfont.families():
                family = "Ebrima"
        except Exception:
            pass
        self.text.config(font=(family, int(self.cfg["font_size"])))

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        dx, dy = self._drag
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    # ---------- minimize to a small bar (dictation keeps going, nothing is lost)
    def _build_mini(self, bg):
        import tkinter as tk
        self._minimized = False
        m = self.mini = tk.Toplevel(self.root)
        m.overrideredirect(True)
        m.attributes("-topmost", True)
        m.attributes("-alpha", 0.94)
        m.configure(bg=bg)
        box = tk.Frame(m, bg=bg, padx=10, pady=6)
        box.pack(fill="both", expand=True)
        self.mini_status = tk.Label(box, text="", fg="white", bg=bg, font=("Segoe UI", 10), anchor="w",
                                    cursor="fleur")
        self.mini_status.pack(side="left", padx=(0, 10))
        for label, cmd in (("⏸", self.toggle_pause), ("⤢ Show", self.restore), ("✓ Done", self.toggle)):
            b = tk.Label(box, text=label, fg="white", bg="#1f6f4a" if "Done" in label else "#3a3a3a",
                         font=("Segoe UI", 10), padx=8, pady=2, cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, c=cmd: c())
            if label == "⏸":
                self.mini_pause = b
        for w in (self.mini_status, box):            # drag the bar anywhere
            w.bind("<ButtonPress-1>", lambda e: setattr(self, "_mini_drag", (e.x_root - m.winfo_x(), e.y_root - m.winfo_y())))
            w.bind("<B1-Motion>", lambda e: m.geometry(f"+{e.x_root - self._mini_drag[0]}+{e.y_root - self._mini_drag[1]}"))
        m.update_idletasks()
        sw, sh = m.winfo_screenwidth(), m.winfo_screenheight()
        m.geometry(f"+{sw - m.winfo_reqwidth() - 380}+{sh - m.winfo_reqheight() - 70}")
        m.withdraw()
        make_no_activate(m)

    def _update_mini(self):
        if not self._minimized:
            return
        paused = bool(self.engine and self.engine.paused)
        words = len((self.engine.committed_text() if self.engine else "").split())
        state = "⏸ Paused" if paused else ("● Listening" if self.active else "Amharic Dictate")
        self.mini_status.config(text=f"{state}  ·  {words} words", fg="#ffcc66" if paused else "#ff6b6b" if self.active else "white")
        self.mini_pause.config(text="▶" if paused else "⏸")

    def minimize(self):
        if not self.active:
            self.root.withdraw()
            return
        self._minimized = True
        self.root.withdraw()
        self._update_mini()
        self.mini.deiconify()
        self.mini.lift()

    def restore(self):
        if not self._minimized:
            if self.active:
                self.root.deiconify(); self.root.lift()
            return
        self._minimized = False
        self.mini.withdraw()
        self.root.deiconify()
        self.root.lift()

    def _place_overlay(self):
        w, h = 860, 280
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 90}")

    def _open_file(self, name):
        p = app_dir() / name
        if p.exists():
            os.startfile(p)

    def hotkey_label(self):
        return self.cfg["hotkey"] if self.cfg["mode"] == "toggle" else f"hold {self.cfg['hold_key']}"

    # ---------- model / mic / hotkeys
    def _reload_model(self):
        if self.loading:
            return
        self.loading = True
        self.tray.icon = tray_image("busy")
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        from engine import DictationEngine, Transcriber, ensure_model
        try:
            self.ui_q.put(("show", "Loading Amharic speech model…", ""))
            t0 = time.time()
            path = ensure_model(self.cfg["model"], lambda s: self.ui_q.put(("status", s)))
            os.environ["HF_HUB_OFFLINE"] = "1"   # everything is local from here on
            from textproc import lexicon
            lexicon()                                    # load the Amharic dictionary once
            level = self.cfg.get("auto_level", True)
            from voiceprofile import active_adapter
            profile, adapter = active_adapter(self.cfg)
            self._loaded_adapter = (str(adapter), os.path.getmtime(adapter)) if adapter else None
            transcriber = Transcriber(path, self.cfg["device"], self.cfg["quantize_cpu"],
                                      use_lm=self.cfg.get("lm_decoding", True),
                                      lm_weight=float(self.cfg.get("lm_weight", 0.25)), auto_level=level,
                                      min_confidence=float(self.cfg.get("min_confidence", 0.45)),
                                      adapter=adapter)
            preview = None
            if transcriber.device == "cpu" and not self.cfg["quantize_cpu"] and self.cfg.get("fast_preview", True):
                self.ui_q.put(("status", "Preparing fast live preview…"))
                preview = Transcriber(path, "cpu", True, auto_level=level,     # int8 copy: quick preview
                                      adapter=adapter if not transcriber.profile_problem else None)
            self.engine = DictationEngine(transcriber, self.cfg, self._on_partial, self._on_phrase, preview)
            self.apply_my_words()
            self.apply_learning()
            here = os.path.dirname(os.path.abspath(__file__))
            if os.path.exists(os.path.join(here, "decode_log.flag")):    # opt-in, text only
                self.engine.decode_log = os.path.join(here, "decode_log.txt")
            if os.path.exists(os.path.join(here, "debug_audio.flag")):   # opt-in diagnostics
                self.engine.debug_dir = os.path.join(here, "debug")
            self._register_hotkeys()
            self.tray.icon = tray_image("ready")
            self.tray.title = f"{APP_NAME} — {self.hotkey_label()}" + (f" — {profile}" if profile else "")
            if adapter and transcriber.profile_problem:
                who = f"Voice profile not used: {transcriber.profile_problem}."
            elif adapter:
                who = f"Voice profile: {profile}"
            elif profile:
                who = f"Profile: {profile} (no voice training yet)"
            else:
                who = ""
            self.ui_q.put(("show", f"Ready on {transcriber.device.upper()} ({time.time() - t0:.0f}s). "
                                   f"Press {self.hotkey_label()} to dictate.", who))
            self.ui_q.put(("hide_after", 3000))
        except Exception as e:
            log_error(traceback.format_exc())
            self.ui_q.put(("show", f"Could not load the model: {e}", "Open Settings from the tray icon to pick another model."))
        finally:
            self.loading = False

    def _open_mic(self):
        import sounddevice as sd
        from engine import BLOCK, SR
        self.stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK,
            callback=self._on_mic,
        )
        self.stream.start()

    def mic_acquire(self, who: str):
        """Open the microphone while someone needs it (dictation or a training recording)."""
        with self._mic_lock:
            self._mic_users.add(who)
            if self.stream is None:
                self._open_mic()

    def mic_release(self, who: str):
        """Close the microphone as soon as nothing needs it, so it is never on in the background."""
        with self._mic_lock:
            self._mic_users.discard(who)
            if not self._mic_users and self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                finally:
                    self.stream = None

    def _on_mic(self, indata, frames, t, status):
        block = indata[:, 0]
        if self.engine:
            self.engine.feed(block)
        tap = self.recorder_tap
        if tap:
            tap(block)

    def apply_my_words(self):
        """Load the active profile's "My words" into the dictionary."""
        try:
            import voiceprofile as vp
            from textproc import set_user_words
            set_user_words(vp.load_my_words(self.cfg["profile"]) if self.cfg.get("profile") else [])
            self._spell_cache = {}                   # re-check red underlines with the new words
        except Exception:
            log_error(traceback.format_exc())

    def apply_learning(self):
        if not self.engine:
            return
        try:
            import voiceprofile as vp
            meta = vp.load_meta(self.cfg["profile"]) if self.cfg.get("profile") else {}
            self.engine.learn = bool(meta.get("learn_from_corrections", False))
        except Exception:
            self.engine.learn = False

    def _learn_from_session(self, final_text: str):
        """Save corrected phrases of a finished dictation as training examples (opt-in), in the background."""
        records = list(getattr(self.engine, "records", []) or [])
        self.engine.records = []
        if not (self.engine.learn and records and self.cfg.get("profile")):
            return
        profile = self.cfg["profile"]

        def work():
            try:
                import voiceprofile as vp
                from learning import corrected_phrases, save_corrections
                pairs = corrected_phrases(records, final_text)
                if pairs:
                    save_corrections(vp.voice_dir(profile), pairs)
            except Exception:
                log_error(traceback.format_exc())
        threading.Thread(target=work, daemon=True).start()

    def _maybe_auto_retrain(self):
        import voiceprofile as vp
        import voice_training as vt
        from learning import count_corrections
        profile = self.cfg.get("profile")
        if not profile or vt.training_running(profile):
            return
        meta = vp.load_meta(profile)
        if not (meta.get("learn_from_corrections") and meta.get("auto_retrain", True)):
            return
        d = vp.voice_dir(profile)
        total = sum(1 for p in d.glob("*.wav") if p.with_suffix(".txt").exists())
        new = count_corrections(d) - int(meta.get("last_trained_corrections", 0))
        if new >= vt.AUTO_RETRAIN_AFTER and total >= vt.MIN_CLIPS:
            vt.launch_training(self.cfg, profile)
            self.ui_q.put(("show", "Improving your voice profile in the background…",
                           f"Learning from {new} new corrections. You can keep working."))
            self.ui_q.put(("hide_after", 3500))

    def _check_profile_update(self):
        """Load a voice profile as soon as its background training finishes (when not dictating)."""
        now = time.time()
        if now < getattr(self, "_next_profile_check", 0) or self.loading or self.active or not self.engine:
            return
        self._next_profile_check = now + 5
        try:
            from voiceprofile import active_adapter
            _, adapter = active_adapter(self.cfg)
            current = (str(adapter), os.path.getmtime(adapter)) if adapter else None
        except Exception:
            return
        if current != getattr(self, "_loaded_adapter", None):
            self._reload_model()
            return
        try:
            self._maybe_auto_retrain()
        except Exception:
            log_error(traceback.format_exc())

    def ensure_profile(self):
        """First run: ask who is dictating (like Dragon) and move any older recordings into that profile."""
        import voiceprofile as vp
        if self.cfg.get("profile") and self.cfg["profile"] in vp.list_profiles():
            return
        existing = vp.list_profiles()
        default = os.environ.get("USERNAME", "User")
        if existing:
            name = existing[0]
        else:
            from tkinter import simpledialog
            name = simpledialog.askstring(APP_NAME, "Who's dictating?\n\nType your name to create your voice profile.",
                                          initialvalue=default, parent=self.root) or default
            name = vp.create_profile(name)
        vp.migrate_old_voice_data(name)
        new = dict(self.cfg); new["profile"] = name
        self.cfg = new
        save_config(new)

    def show_about(self):
        from tkinter import messagebox
        model = self.cfg.get("model", "")
        if model == "bundled":
            model = "Amharic Speech-to-Text EFA v1 (built in)"
        if "Ethio-ASR" in model:
            model_credit = ("Speech model: Ethio-ASR (Amharic) by badrex, CC BY-NC 4.0 — "
                            "free, non-commercial use only.")
        else:
            model_credit = (f"Speech model: {model}, CC BY-SA 4.0 — based on facebook/w2v-bert-2.0 (MIT), "
                            "trained on WAXAL (Google & partners) and FLEURS (Google) Amharic speech data.")
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n"
            "Offline Amharic dictation for Windows.\n\n"
            f"{model_credit}\n\n"
            "Amharic dictionary: Leipzig Corpora Collection (CC BY 4.0).\n"
            "Reading sentences: Leipzig Corpora Collection, Amharic Wikipedia (CC BY 4.0).\n\n"
            "Everything you dictate stays on this computer.\n\n"
            "Created by Endrias F. Abitte",
            parent=self.root)

    def open_spelling(self):
        try:
            from spell_window import SpellWindow
            if getattr(self, "_spell_win", None) is not None and self._spell_win.win.winfo_exists():
                self._spell_win.win.lift()
                self._spell_win.scan()
                return
            self._spell_win = SpellWindow(self)
        except Exception as e:
            log_error(traceback.format_exc())
            from tkinter import messagebox
            messagebox.showerror(APP_NAME, f"Amharic spelling for Word isn't available: {e}", parent=self.root)

    def open_training(self):
        from voice_training import VoiceTrainingWindow
        if self._train_win is not None and self._train_win.win.winfo_exists():
            self._train_win.win.lift()
            return
        self._train_win = VoiceTrainingWindow(self)

    def _register_hotkeys(self):
        import keyboard
        keyboard.unhook_all()
        if self.cfg["mode"] == "hold":
            key = self.cfg["hold_key"]
            keyboard.on_press_key(key, lambda e: (not self.active) and self.toggle())
            keyboard.on_release_key(key, lambda e: self.active and self.toggle())
        else:
            keyboard.add_hotkey(self.cfg["hotkey"], self.toggle, suppress=True)

    def _add_session_hotkeys(self):
        import keyboard
        for key, fn in ((self.cfg.get("pause_hotkey"), self.toggle_pause),
                        (self.cfg.get("delete_hotkey"), self.delete_word),
                        (self.cfg.get("undo_hotkey"), lambda: self.ui_q.put(("undo",)))):
            if key:
                try:
                    self._session_hotkeys.append(keyboard.add_hotkey(key, fn, suppress=True))
                except Exception:
                    log_error(traceback.format_exc())

    def _remove_session_hotkeys(self):
        import keyboard
        for h in self._session_hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._session_hotkeys = []
        self.recorder_tap = None          # set by the voice-training window to receive mic audio
        self._train_win = None

    def toggle_pause(self):
        if not (self.engine and self.active):
            return
        on = not self.engine.paused
        self.engine.pause(on)
        self.tray.icon = tray_image("paused" if on else "active")
        if self.cfg["beep"]:
            beep(440 if on else 880, 60)
        self.ui_q.put(("pausebtn", on))
        if on:
            self.ui_q.put(("status", f"⏸ Paused — press {self.cfg.get('pause_hotkey')} to continue, "
                                     f"{self.hotkey_label()} to finish"))
        else:
            self.ui_q.put(("status", "● Listening… speak Amharic"))

    def _on_text_click(self, e):
        if not (self.engine and self.active):
            return
        if self.cfg["insert"] == "per_phrase":
            self.status.config(text="Click-to-replace needs Output = 'Paste when I stop' (Settings)")
            return
        idx = self.text.index(f"@{e.x},{e.y}")
        n = self.text.count("1.0", idx, "chars")
        off = int(n[0]) if n else 0
        if self.engine.replacing:
            self.engine.cancel_selection()               # put a highlighted word back before choosing another
            self.sugg.pack_forget()
        committed = self.engine.committed_text()
        if off >= len(committed):
            self.status.config(text="That part is still being finished — click it again in a moment")
            return
        seps = " \n"
        marks = "።፣፤፥፦?!«»()"
        if committed[off] in marks:                      # clicked a punctuation mark: select just the mark
            if self.engine.begin_replace(off, off + 1):
                self.status.config(text="Selected punctuation — remove it or pick another mark")
                self._show_suggestions(committed[off])
            return
        if committed[off] in seps:                       # clicked the space between two words: insert there
            if self.engine.begin_insert(off):
                self.status.config(text="Insert here — say the words (they go where ▮ is)")
                self._show_suggestions(None)
            return
        start = off
        while start > 0 and committed[start - 1] not in seps:
            start -= 1
        end = off
        while end < len(committed) and committed[end] not in seps:
            end += 1
        while end > start and committed[end - 1] in "።፣፤፥፦?!":   # keep punctuation after the word
            end -= 1
        if end <= start:
            return
        word = committed[start:end]
        if self.engine.begin_replace(start, end):
            self.status.config(text=f"Selected “{word}” — say the new word, pick a suggestion, or choose an action")
            self._show_suggestions(word)

    def undo(self):
        if not (self.engine and self.active):
            return
        if self.engine.undo():
            n = self.engine.undo_steps
            self.status.config(text=f"↶ Undone — {n} more step{'s' if n != 1 else ''} available" if n else "↶ Undone — nothing more to undo")
            self.sugg.pack_forget()
        else:
            self.status.config(text="Nothing to undo")

    def copy_text(self):
        import pyperclip
        text = self.text.get("1.0", "end").replace("▮", "").replace("⟦", "").replace("⟧", "").strip()
        if text:
            pyperclip.copy(text.replace("\n", "\r\n"))
            self.status.config(text="Copied — paste anywhere with Ctrl+V")

    def cancel(self):
        """Stop dictating and throw the text away."""
        if self.engine and self.active:
            threading.Thread(target=self._toggle, kwargs={"discard": True}, daemon=True).start()

    def delete_word(self):
        if not (self.engine and self.active):
            return
        if self.engine.replacing and self.engine.gap_word:      # a clicked word is waiting: remove it
            self._remove_clicked()
            return
        if self.cfg["insert"] == "per_phrase":
            # text is already in the other app: delete the word there
            import keyboard
            wait_modifiers_released()
            keyboard.send("ctrl+backspace")
        self.engine.delete_last_word()

    # ---------- settings
    def open_settings(self):
        from settings_ui import open_settings
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = open_settings(self.root, self.cfg, self.apply_settings)

    def apply_settings(self, new: dict):
        old = self.cfg
        save_config(new)
        self.cfg = new
        try:
            set_start_with_windows(new["start_with_windows"])
        except Exception:
            log_error(traceback.format_exc())
        self._apply_font()
        if any(old.get(k) != new.get(k) for k in RELOAD_KEYS):
            self._reload_model()
            return
        if self.engine:
            self.engine.cfg = new
            try:
                self._register_hotkeys()
            except Exception as e:
                log_error(traceback.format_exc())
                self.ui_q.put(("show", f"Invalid hotkey: {e}", "Open Settings to fix it."))
                return
        self.tray.title = f"{APP_NAME} — {self.hotkey_label()}"
        self.ui_q.put(("show", "Settings saved", f"Hotkey: {self.hotkey_label()}"))
        self.ui_q.put(("hide_after", 2000))

    # ---------- dictation
    def toggle(self):
        if self._train_win is not None and getattr(self._train_win, "recording", False):
            return                                   # recording a training sentence: no dictation
        if self.engine and not self.loading:
            threading.Thread(target=self._toggle, daemon=True).start()

    def _toggle(self, discard=False):
        if not self._toggle_lock.acquire(blocking=False):
            return
        try:
            if not self.active:
                self.mic_acquire("dictation")
                self.word = None
                if self.cfg.get("live_word", True) and self.cfg["insert"] == "on_stop":
                    from wordsync import WordSync, word_is_in_front
                    if word_is_in_front():
                        link = WordSync(self._word_edited, log_error)
                        if link.start():
                            self.word = link
                        else:
                            log_error(link.error)
                self.active = True
                self.engine.on_speech_start = self._speech_started if self.word else None
                self.engine.start()
                self._add_session_hotkeys()
                self.tray.icon = tray_image("active")
                if self.cfg["beep"]:
                    beep(880)
                self.ui_q.put(("show", "● Listening… speak Amharic" +
                               ("   ·   live in Word" if self.word else ""), ""))
                self.ui_q.put(("bar", True))
            else:
                self.active = False
                self._remove_session_hotkeys()
                self.ui_q.put(("bar", False))
                self.ui_q.put(("status", "Discarding…" if discard else "Finishing…"))
                text = self.engine.stop()
                self.mic_release("dictation")
                link, self.word = self.word, None
                in_document = False
                if link is not None:
                    if discard:
                        link.cancel()
                    else:
                        text = link.finish(text)       # Word's version, including any edits made there
                        in_document = True
                self.tray.icon = tray_image("ready")
                if self.cfg["beep"]:
                    beep(520)
                if discard:
                    self.engine.records = []             # cancelled: never learn from it
                    self.ui_q.put(("show", "Dictation discarded", ""))
                    self.ui_q.put(("hide_after", 1200))
                else:
                    self._learn_from_session(text)
                    self._deliver(text, in_document)
        except Exception as e:
            log_error(traceback.format_exc())
            self.active = False
            try:
                self.mic_release("dictation")
            except Exception:
                pass
            self.ui_q.put(("show", f"Error: {e}", "Details are in the log (tray → Open log)."))
        finally:
            self._toggle_lock.release()

    def _speech_started(self):
        """Follow the cursor: if you clicked elsewhere in Word, the next words go there."""
        link = self.word
        if link is None or not link.cursor_away or not self.engine:
            return
        threading.Thread(target=self._move_to_cursor, args=(link,), daemon=True).start()

    def _move_to_cursor(self, link):
        if self._moving or self.engine.replacing:        # busy, or in the middle of a correction in the box
            return
        self._moving = True
        try:
            previous = self.engine.document_text()
            link.hold(True)                              # nothing may be written while we switch spots
            try:
                if not self.engine.start_new_passage():
                    return
                moved = link.new_passage()
            finally:
                link.hold(False)
            link.update(self.engine.document_text())
            self._learn_from_session(previous)          # the finished passage (if learning is on)
            if moved:
                self.ui_q.put(("status", "● Continuing at your new spot in Word"))
        finally:
            self._moving = False

    def _word_edited(self, text: str):
        """Called from the Word link when the dictated text was edited directly in Word."""
        if self.engine and self.active and self.engine.set_document_text(text):
            self.ui_q.put(("status", "Updated from your edit in Word"))

    def _deliver(self, text: str, in_document: bool = False):
        if in_document:                       # live in Word: the text is already there
            if self.cfg["save_history"] and text:
                with open(app_dir() / "history.txt", "a", encoding="utf-8") as f:
                    f.write(time.strftime("[%Y-%m-%d %H:%M] ") + text.replace("\n", " ⏎ ") + "\n")
            self.ui_q.put(("status", "Done — your text is in Word"))
            self.ui_q.put(("hide_after", 900))
            return
        if not text:
            self.ui_q.put(("show", "No speech detected — check the microphone in Windows sound settings", ""))
            self.ui_q.put(("hide_after", 2500))
            return
        if self.cfg["save_history"]:
            with open(app_dir() / "history.txt", "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M] ") + text.replace("\n", " ⏎ ") + "\n")
        mode = self.cfg["insert"]
        if mode == "on_stop":
            self.ui_q.put(("hide_after", 0))
            time.sleep(0.1)
            paste_text(text)
        elif mode == "clipboard":
            import pyperclip
            pyperclip.copy(text.replace("\n", "\r\n"))
            self.ui_q.put(("status", "Copied to clipboard — paste with Ctrl+V"))
            self.ui_q.put(("hide_after", 2500))
        else:  # per_phrase: already typed
            self.ui_q.put(("hide_after", 800))

    def _on_partial(self, text: str):
        self.ui_q.put(("text", text))
        link = self.word
        if link is not None and self.engine:
            link.update(self.engine.document_text())

    def _on_phrase(self, phrase: str):
        if self.cfg["insert"] == "per_phrase":
            threading.Thread(target=paste_text, args=(phrase if phrase.endswith("\n") else phrase + " ",),
                             daemon=True).start()

    # ---------- UI thread
    def _set_text(self, text: str):
        sel = None
        a, b = text.find("⟦"), text.find("⟧")
        if 0 <= a < b:                                   # highlighted word
            word = text[a + 1:b]
            text = text[:a] + word + text[b + 1:]
            sel = (a, a + len(word))
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self._tag_words()
        if sel:
            self.text.tag_add("selected", f"1.0+{sel[0]}c", f"1.0+{sel[1]}c")
            self.text.tag_raise("selected")
        self.text.see("end")              # always show the latest words
        self.text.config(state="disabled")

    def _tag_words(self):
        alts = self.engine.alternatives if self.engine else {}
        for word in list(alts)[-200:]:
            start = "1.0"
            while True:
                pos = self.text.search(word, start, stopindex="end")
                if not pos:
                    break
                end = f"{pos}+{len(word)}c"
                before = self.text.get(f"{pos}-1c", pos) if pos != "1.0" else " "
                after = self.text.get(end, f"{end}+1c")
                if before in " \n" and (after in " \n።፣፤?!" or after == ""):   # whole word only
                    self.text.tag_add("unsure", pos, end)
                start = end
        if self.cfg.get("spellcheck", True):
            import re
            from textproc import misspelling_fix
            content = self.text.get("1.0", "end")
            for m in re.finditer(r"[^\s▮]+", content):
                w = m.group()
                if w not in self._spell_cache:
                    if len(self._spell_cache) > 5000:
                        self._spell_cache.clear()
                    self._spell_cache[w] = bool(misspelling_fix(w))
                if self._spell_cache[w]:
                    self.text.tag_add("misspelled", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        pos = self.text.search("▮", "1.0", stopindex="end")
        if pos:
            self.text.tag_add("gap", pos, f"{pos}+1c")

    def _show_suggestions(self, word):
        from textproc import suggest
        import tkinter as tk
        is_mark = bool(word) and len(word) == 1 and word in "።፣፤፥፦?!«»()"
        if is_mark:
            options = [m for m in ("።", "፣", "፤", "?", "!", "፦") if m != word]
        else:
            options = suggest(word, self.engine.alternatives.get(word, []), limit=5) if word else []
        for holder in (self.sugg_chips, self.sugg_actions):
            for w in holder.winfo_children():
                w.destroy()

        def action(label, fn, color="#3a3a3a"):
            b = tk.Label(self.sugg_actions, text=label, fg="white", bg=color, font=("Segoe UI", 9),
                         padx=7, pady=2, cursor="hand2")
            b.pack(side="left", padx=(0, 5))
            b.bind("<Button-1>", lambda e: fn())

        if word is None:
            self.sugg_title.config(text="Say the words to insert here")
            action("⌫ Join words (remove space)", self._join_words)
        elif is_mark:
            self.sugg_title.config(text="Change to:")
            action("🗑 Remove", self._remove_clicked, "#5a2a2a")
        else:
            self.sugg_title.config(text=("Say it again, or pick:" if options else "Say the word again"))
            action("🗑 Remove", self._remove_clicked, "#5a2a2a")
            action("⇤ Join previous", lambda: self._join_clicked("prev"))
            action("Join next ⇥", lambda: self._join_clicked("next"))
            if self.cfg.get("profile"):
                action("★ My words", lambda w=word: self._add_my_word(w), "#2a4a5a")
            action("➕ Insert before", lambda: self._keep_and_insert("before"))
            action("➕ Insert after", lambda: self._keep_and_insert("after"))
        for opt in options:
            family = self.text.cget("font").split(" ")[0].strip("{}") or "Ebrima"
            b = tk.Label(self.sugg_chips, text=opt, fg="white", bg="#264a73", font=(family, 13),
                         padx=8, pady=1, cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, o=opt: self._suggestion_chosen(o))
        self.sugg.pack(fill="x", pady=(4, 0), before=self.bar)

    def _add_my_word(self, word):
        import voiceprofile as vp
        word = word.strip("።፣፤፥፦?!«»()")
        if not word:
            return
        vp.add_my_word(self.cfg["profile"], word)
        self.apply_my_words()
        self._suggestion_chosen(None)            # keep the word as it is
        self.status.config(text=f"Added “{word}” to My words")

    def _remove_clicked(self):
        if self.engine:
            word = self.engine.gap_word
            self.engine.fill_gap("")
            self.status.config(text=f"Removed “{word}”" if word else "● Listening… speak Amharic")
            self.sugg.pack_forget()

    def _join_clicked(self, direction):
        if self.engine:
            self.engine.join_clicked(direction)
            self.status.config(text="Joined — keep talking")
            self.sugg.pack_forget()

    def _join_words(self):
        if self.engine:
            self.engine.join_at_gap()
            self.status.config(text="Joined the two words — keep talking")
            self.sugg.pack_forget()

    def _keep_and_insert(self, where):
        if self.engine:
            self.engine.keep_word_insert(where)
            self.status.config(text=f"Insert {where} the word — say the words (they go where ▮ is)")
            self._show_suggestions(None)

    def _suggestion_chosen(self, option):
        if not self.engine:
            return
        if option is None:
            self.engine.undo_replace()
            self.status.config(text="● Listening… speak Amharic")
        else:
            self.engine.fill_gap(option)
            self.status.config(text=f"Replaced with “{option}” — keep talking")
        self.sugg.pack_forget()

    def _show(self, status: str, text: str):
        self.status.config(text=status)
        self._set_text(text)
        self.root.deiconify()
        self.root.lift()

    def _pump_ui(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                kind = msg[0]
                if kind == "show":
                    if self._minimized and self.active:
                        self.status.config(text=msg[1])
                    else:
                        self._show(msg[1], msg[2])
                elif kind == "status":
                    self.status.config(text=msg[1])
                    if not self._minimized:
                        self.root.deiconify()
                elif kind == "restore":
                    self.restore()
                elif kind == "text":
                    self._set_text(msg[1])
                elif kind == "hide_after":
                    self.root.after(msg[1], lambda: (not self.active) and self.root.withdraw())
                elif kind == "settings":
                    self.open_settings()
                elif kind == "undo":
                    self.undo()
                elif kind == "train":
                    self.open_training()
                elif kind == "about":
                    self.show_about()
                elif kind == "spell":
                    self.open_spelling()
                elif kind == "bar":
                    if not msg[1] and self._minimized:          # dictation finished: back to normal
                        self._minimized = False
                        self.mini.withdraw()
                    if msg[1]:
                        self.buttons["pause"].config(text="⏸  Pause")
                        self.bar.pack(fill="x", pady=(6, 0))
                    else:
                        self.bar.pack_forget()
                elif kind == "pausebtn":
                    self.buttons["pause"].config(text="▶  Resume" if msg[1] else "⏸  Pause")
        except queue.Empty:
            pass
        if self.sugg.winfo_ismapped() and not (self.engine and self.active and self.engine.replacing):
            self.sugg.pack_forget()
        self._check_profile_update()
        self._update_mini()
        level = self.engine.level if (self.engine and self.active) else 0.0
        self.meter.coords(self.meter_bar, 0, 0, min(80, int(level * 1600)), 8)
        self.root.after(50, self._pump_ui)

    def quit(self):
        try:
            if self.stream:
                self.stream.stop()
            self.tray.stop()
        finally:
            self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()


def selftest(out_path: str) -> int:
    """Used by the CI build: verify the frozen app can import everything it needs."""
    lines, code = [], 0
    for mod in ("numpy", "torch", "sounddevice", "keyboard", "pyperclip", "pystray", "PIL",
                "huggingface_hub", "engine", "textproc", "settings_ui", "lmdecode", "voiceprofile",
                "voice_training", "train_local", "learning", "wordsync", "wordspell", "spell_window", "win32com.client", "pythoncom"):
        try:
            __import__(mod)
            lines.append(f"OK   {mod}")
        except Exception as e:
            lines.append(f"FAIL {mod}: {e}"); code = 1
    try:
        from transformers import (AutoModelForCTC, AutoProcessor, SeamlessM4TFeatureExtractor,  # noqa: F401
                                  Wav2Vec2BertForCTC, Wav2Vec2CTCTokenizer, Wav2Vec2ForCTC)
        lines.append("OK   transformers CTC classes")
    except Exception as e:
        lines.append(f"FAIL transformers: {e}"); code = 1
    from config import bundled_model_dir
    bundled = bundled_model_dir()
    if bundled:                                   # installer builds: the built-in model must load and run
        try:
            import numpy as np
            from engine import Transcriber
            tr = Transcriber(bundled, "cpu", False, use_lm=True)
            tr(np.zeros(16000, dtype=np.float32))
            lines.append(f"OK   built-in model ({bundled})")
        except Exception as e:
            lines.append(f"FAIL built-in model: {e}"); code = 1
    else:
        lines.append("--   no built-in model in this build")
    from textproc import finish_phrase
    ok = finish_phrase("ሁለት መቶ ሰዎች አራት ነጥብ", {}) == "200 ሰዎች።"
    lines.append(("OK" if ok else "FAIL") + "   text processing"); code |= (not ok)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"{APP_NAME} {APP_VERSION}\n" + "\n".join(lines) + "\n")
    return code


def main():
    from config import bundled_model_dir
    if bundled_model_dir():               # installed app: everything is local, never contact the internet
        for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_DATASETS_OFFLINE"):
            os.environ[var] = "1"
    if len(sys.argv) >= 2 and sys.argv[1] == "--train":       # background voice training (packaged app)
        import train_local
        train_local.run_and_exit(sys.argv[2:])
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    if not single_instance():
        return
    # Running under pythonw has no console: send output to run.log next to the app
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        try:
            log = open(app_dir() / "run.log", "w", encoding="utf-8", buffering=1)
        except Exception:
            log = open(os.devnull, "w")
        sys.stdout = sys.stderr = log
    try:
        App().run()
    except Exception:
        log_error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
