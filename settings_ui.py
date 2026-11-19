"""Settings window (tkinter)."""

import theme as T
import os
import tkinter as tk
from tkinter import ttk

from config import APP_TITLE, APP_VERSION, MODEL_PRESETS, bring_to_front, bundled_model_dir
from textproc import COMMANDS

INSERT_MODES = [("on_stop", "Paste when I stop"), ("per_phrase", "Type as I speak (each phrase)"),
                ("clipboard", "Copy to clipboard only")]
MODES = [("toggle", "Press hotkey to start, press again to stop"), ("hold", "Hold a key while speaking (push-to-talk)")]
DEVICES = [("auto", "Automatic"), ("cpu", "CPU"), ("cuda", "NVIDIA GPU")]


def open_settings(root, cfg: dict, on_save):
    win = tk.Toplevel(root)
    win.title(f"{APP_TITLE} settings")
    win.resizable(False, False)
    bring_to_front(win)
    pad = {"padx": 10, "pady": 4}

    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=8, pady=8)
    v = {}

    def labeled(parent, row, text, widget):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", **pad)
        widget.grid(row=row, column=1, sticky="we", **pad)

    def combo(parent, key, options):
        labels = [l for _, l in options]
        var = tk.StringVar(value=dict(options).get(cfg[key], cfg[key]))
        cb = ttk.Combobox(parent, textvariable=var, values=labels, width=46)
        v[key] = (var, {l: k for k, l in options})
        return cb

    def check(parent, row, key, text):
        var = tk.BooleanVar(value=bool(cfg[key]))
        ttk.Checkbutton(parent, text=text, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        v[key] = (var, None)

    def entry(parent, key, width=20):
        var = tk.StringVar(value=str(cfg[key]))
        v[key] = (var, None)
        return ttk.Entry(parent, textvariable=var, width=width)

    # ---- General
    g = ttk.Frame(nb); nb.add(g, text="General")
    labeled(g, 12, "Appearance", combo(g, "appearance", [("system", "Same as Windows (light or dark)"),
                                                          ("dark", "Dark"), ("light", "Light")]))
    labeled(g, 0, "Dictation mode", combo(g, "mode", MODES))
    labeled(g, 1, "Hotkey (toggle mode)", entry(g, "hotkey"))
    labeled(g, 2, "Hold key (push-to-talk)", entry(g, "hold_key"))
    labeled(g, 3, "Pause / resume hotkey", entry(g, "pause_hotkey"))
    labeled(g, 4, "Delete last word hotkey", entry(g, "delete_hotkey"))
    labeled(g, 9, "Undo hotkey", entry(g, "undo_hotkey"))
    labeled(g, 5, "Output", combo(g, "insert", INSERT_MODES))
    check(g, 6, "beep", "Play a short beep on start/stop")
    from config import is_store_app
    if is_store_app():                 # Store version: Windows controls this
        ttk.Label(g, text="To start automatically when you sign in, turn on Amharic Dictate in "
                          "Windows Settings → Apps → Startup.", foreground=T.MUTED, wraplength=520
                  ).grid(row=7, column=0, columnspan=2, sticky="w", **pad)
    else:
        check(g, 7, "start_with_windows", "Start automatically when I sign in to Windows")
    if not is_store_app():             # Store version: the Store updates the app
        check(g, 11, "check_updates", "Check for new versions once a day (asks GitHub for the latest version "
                                      "number only — nothing about you or your dictation is sent)")
    check(g, 13, "free_memory_when_idle", "Free memory when I'm not dictating (after 10 minutes): uses about "
                                          "0.5 GB instead of 4 GB. The next dictation takes a few seconds to start.")
    hist = ttk.Frame(g); hist.grid(row=8, column=0, columnspan=2, sticky="we", **pad)
    hvar = tk.BooleanVar(value=bool(cfg["save_history"])); v["save_history"] = (hvar, None)
    ttk.Checkbutton(hist, text="Save a history of everything I dictate (a text file, not encrypted)",
                    variable=hvar).grid(row=0, column=0, columnspan=3, sticky="w")
    from config import history_file
    dvar = tk.StringVar(value=str(cfg.get("history_dir", ""))); v["history_dir"] = (dvar, None)
    where = ttk.Label(hist, text="", foreground=T.MUTED)
    where.grid(row=1, column=0, sticky="w", padx=(24, 8))

    def show_where(*_):
        where.config(text=f"Saved to: {history_file({'history_dir': dvar.get()})}")

    def choose_folder():
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=win, title="Choose where to save the dictation history",
                                    initialdir=str(history_file({'history_dir': dvar.get()}).parent))
        if d:
            dvar.set(os.path.normpath(d)); show_where()

    def open_folder():
        os.startfile(str(history_file({'history_dir': dvar.get()}).parent))
    ttk.Button(hist, text="Change folder…", command=choose_folder).grid(row=1, column=1, padx=2)
    ttk.Button(hist, text="Open folder", command=open_folder).grid(row=1, column=2, padx=2)
    show_where()
    check(g, 10, "live_word", "Live dictation into Microsoft Word: text appears as you speak, corrections update "
                              "the document, and edits you make in Word update the box")

    # ---- Text
    t = ttk.Frame(nb); nb.add(t, text="Text")
    check(t, 0, "voice_commands", "Spoken punctuation commands")
    def show(o):
        return {"\x08": "delete last word", "\x0e": "« or »"}.get(o, o.replace(chr(10), "↵"))
    seen, items = set(), []
    for p, o in COMMANDS:
        if " " in p and o not in seen:
            seen.add(o); items.append(f"“{p}” → {show(o)}")
    cmds = "   ".join(items)
    ttk.Label(t, text=cmds, wraplength=420, foreground=T.MUTED).grid(row=1, column=0, columnspan=2, sticky="w", padx=28)
    check(t, 2, "numbers_to_digits", "Write spoken numbers as digits (ሁለት መቶ ሀምሳ → 250)")
    check(t, 3, "auto_period", "Add ። automatically at the end of each phrase")
    check(t, 9, "spellcheck", "Underline words that look misspelled (red)")
    check(t, 8, "autocorrect_spelling", "Fix sound-alike spellings using the Amharic dictionary (ሠ/ሰ, ፀ/ጸ, ሐ/ሀ…)")
    check(t, 7, "model_punctuation", "Let the speech model add ። ፣ ? on its own (often wrong)")
    labeled(t, 4, "Pause that ends a phrase (ms)", entry(t, "silence_ms", 8))
    # dictation text size: slider + number + live Amharic preview
    fs_min, fs_max, fs_default = 10, 36, 15
    try:
        fs_now = max(fs_min, min(fs_max, int(cfg.get("font_size", fs_default))))
    except (TypeError, ValueError):
        fs_now = fs_default
    fs_var = tk.IntVar(value=fs_now)
    v["font_size"] = (fs_var, None)
    fs = ttk.Frame(t)
    preview = tk.Label(t, text="ሰላም፣ እንዴት ነህ? ይህ የጽሑፍ መጠን ነው።", anchor="w", fg=T.TEXT, bg=T.FIELD,
                       padx=10, pady=6)

    def fs_update(*_):
        try:
            size = int(float(fs_var.get()))
        except (tk.TclError, ValueError):
            return
        size = max(fs_min, min(fs_max, size))
        if fs_var.get() != size:
            fs_var.set(size)
        preview.config(font=("Ebrima", size))

    ttk.Scale(fs, from_=fs_min, to=fs_max, orient="horizontal", length=200,
              command=lambda val: fs_var.set(int(float(val)))).pack(side="left")
    fs.winfo_children()[0].set(fs_now)
    ttk.Spinbox(fs, from_=fs_min, to=fs_max, textvariable=fs_var, width=4,
                command=lambda: fs.winfo_children()[0].set(fs_var.get())).pack(side="left", padx=8)
    ttk.Button(fs, text=f"Default ({fs_default})",
               command=lambda: (fs_var.set(fs_default), fs.winfo_children()[0].set(fs_default))).pack(side="left")
    fs_var.trace_add("write", fs_update)
    labeled(t, 5, "Dictation text size", fs)
    preview.grid(row=6, column=0, columnspan=2, sticky="we", padx=10, pady=(0, 10))   # right under the size
    fs_update()

    # ---- Model
    m = ttk.Frame(nb); nb.add(m, text="Speech model")
    if bundled_model_dir():      # installed app: the built-in model only, shown but not changeable
        labeled(m, 0, "Model", ttk.Label(m, text="Amharic Speech-to-Text EFA v1 (built in)"))
        ttk.Label(m, text="An AI speech model made for Amharic dictation. It runs on this computer.",
                  foreground=T.MUTED).grid(row=1, column=0, columnspan=2, sticky="w", padx=10)
    else:                        # running from source: developers can try other models
        presets = list(MODEL_PRESETS)
        if cfg["model"] not in dict(presets):
            presets.append((cfg["model"], cfg["model"]))
        labeled(m, 0, "Model", combo(m, "model", presets))
        ttk.Label(m, text="Developers: you can also paste a Hugging Face model id or a local folder path.",
                  foreground=T.MUTED).grid(row=1, column=0, columnspan=2, sticky="w", padx=10)
    labeled(m, 2, "Run on", combo(m, "device", DEVICES))
    check(m, 5, "auto_level", "Even out quiet or fading speech (automatic volume levelling)")
    check(m, 6, "lm_decoding", "Use the Amharic dictionary to pick words when audio is unclear")
    check(m, 3, "quantize_cpu", "Faster CPU mode (int8) — less accurate, for slow PCs")
    ttk.Label(m, text=f"{APP_TITLE} {APP_VERSION} — all speech is processed on this computer.",
              foreground=T.MUTED).grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=(14, 4))

    status = ttk.Label(win, text="", foreground=T.DANGER)
    status.pack(anchor="w", padx=12)

    def save():
        new = dict(cfg)
        try:
            for key, (var, mapping) in v.items():
                val = var.get()
                if mapping is not None:
                    val = mapping.get(val, val.strip())
                if key in ("silence_ms", "font_size"):
                    val = int(val)
                new[key] = val
        except (ValueError, tk.TclError):
            status.config(text="Numbers only for pause length and text size.")
            return
        if not str(new["model"]).strip():
            status.config(text="Choose a model.")
            return
        win.destroy()
        on_save(new)

    btns = ttk.Frame(win); btns.pack(fill="x", padx=8, pady=8)
    ttk.Button(btns, text="Save", command=save).pack(side="right", padx=4)
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
    win.focus_force()
    return win
