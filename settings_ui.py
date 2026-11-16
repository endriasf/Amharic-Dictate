"""Settings window (tkinter)."""

import tkinter as tk
from tkinter import ttk

from config import APP_NAME, APP_VERSION, BUNDLED_MODEL, MODEL_PRESETS, bundled_model_dir
from textproc import COMMANDS

INSERT_MODES = [("on_stop", "Paste when I stop"), ("per_phrase", "Type as I speak (each phrase)"),
                ("clipboard", "Copy to clipboard only")]
MODES = [("toggle", "Press hotkey to start, press again to stop"), ("hold", "Hold a key while speaking (push-to-talk)")]
DEVICES = [("auto", "Automatic"), ("cpu", "CPU"), ("cuda", "NVIDIA GPU")]


def open_settings(root, cfg: dict, on_save):
    win = tk.Toplevel(root)
    win.title(f"{APP_NAME} settings")
    win.resizable(False, False)
    win.attributes("-topmost", True)
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
    labeled(g, 0, "Dictation mode", combo(g, "mode", MODES))
    labeled(g, 1, "Hotkey (toggle mode)", entry(g, "hotkey"))
    labeled(g, 2, "Hold key (push-to-talk)", entry(g, "hold_key"))
    labeled(g, 3, "Pause / resume hotkey", entry(g, "pause_hotkey"))
    labeled(g, 4, "Delete last word hotkey", entry(g, "delete_hotkey"))
    labeled(g, 9, "Undo hotkey", entry(g, "undo_hotkey"))
    labeled(g, 5, "Output", combo(g, "insert", INSERT_MODES))
    check(g, 6, "beep", "Play a short beep on start/stop")
    check(g, 7, "start_with_windows", "Start automatically when I sign in to Windows")
    check(g, 8, "save_history", "Save a history of transcripts (stored unencrypted on this PC)")

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
    ttk.Label(t, text=cmds, wraplength=420, foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w", padx=28)
    check(t, 2, "numbers_to_digits", "Write spoken numbers as digits (ሁለት መቶ ሀምሳ → 250)")
    check(t, 3, "auto_period", "Add ። automatically at the end of each phrase")
    check(t, 8, "spellcheck", "Underline words that look misspelled (red)")
    check(t, 7, "autocorrect_spelling", "Fix sound-alike spellings using the Amharic dictionary (ሠ/ሰ, ፀ/ጸ, ሐ/ሀ…)")
    check(t, 6, "model_punctuation", "Let the speech model add ። ፣ ? on its own (often wrong)")
    labeled(t, 4, "Pause that ends a phrase (ms)", entry(t, "silence_ms", 8))
    labeled(t, 5, "Overlay font size", entry(t, "font_size", 8))

    # ---- Model
    m = ttk.Frame(nb); nb.add(m, text="Speech model")
    presets = list(MODEL_PRESETS)
    if bundled_model_dir():
        presets.insert(0, (BUNDLED_MODEL, "EFA Amharic Speech-to-Text (built in) — by Endrias F. Abitte"))
    if cfg["model"] not in dict(presets):
        presets.append((cfg["model"], cfg["model"]))
    labeled(m, 0, "Model", combo(m, "model", presets))
    ttk.Label(m, text="You can also paste a Hugging Face model id or a local folder path.",
              foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w", padx=10)
    labeled(m, 2, "Run on", combo(m, "device", DEVICES))
    check(m, 5, "auto_level", "Even out quiet or fading speech (automatic volume levelling)")
    check(m, 6, "lm_decoding", "Use the Amharic dictionary to pick words when audio is unclear")
    check(m, 3, "quantize_cpu", "Faster CPU mode (int8) — less accurate, for slow PCs")
    ttk.Label(m, text=f"{APP_NAME} {APP_VERSION} — all speech is processed on this computer.",
              foreground="#555").grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=(14, 4))

    status = ttk.Label(win, text="", foreground="#b00")
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
        except ValueError:
            status.config(text="Numbers only for pause length and font size.")
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
