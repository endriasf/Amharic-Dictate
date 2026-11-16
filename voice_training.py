"""
"Voice profiles" window (Dragon-style): pick or create a profile, do the setup reading,
and train a small personal add-on for that voice on this PC.

Each profile lives in %APPDATA%\\AmharicDictate\\profiles\\<name>\\. Nothing leaves the computer.
"""

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import wave
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np

import voiceprofile as vp
from config import log_error

SR = 16000
SETUP_CLIPS = 50          # Dragon-style setup reading
MIN_CLIPS = 30
TARGET_CLIPS = 300        # more is better


AUTO_RETRAIN_AFTER = 25   # new corrections before an automatic retrain
RUNNING = {}              # profile name -> training process (manual or automatic)


def training_running(profile) -> bool:
    p = RUNNING.get(profile)
    return p is not None and p.poll() is None


def progress_path(profile):
    return vp.profile_dir(profile) / "train_progress.json"


def launch_training(cfg: dict, profile: str):
    """Start background training for a profile's voice add-on. Returns the process."""
    if training_running(profile):
        return RUNNING[profile]
    try:
        progress_path(profile).unlink()
    except OSError:
        pass
    from engine import ensure_model
    base_name = cfg["model"]
    base = ensure_model(base_name)
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--train"]
    else:
        py = sys.executable.replace("pythonw.exe", "python.exe")
        cmd = [py, os.path.join(os.path.dirname(os.path.abspath(__file__)), "train_local.py")]
    cmd += ["--base", base, "--base-name", base_name, "--data", str(vp.voice_dir(profile)),
            "--out", str(vp.adapter_path(profile)),
            "--profile-json", str(vp.profile_dir(profile) / "profile.json"),
            "--progress", str(progress_path(profile))]
    flags = 0x08000000 | 0x00004000       # no console window, below-normal priority
    proc = subprocess.Popen(cmd, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    RUNNING[profile] = proc
    return proc


def load_sentences():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "training_sentences.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def list_clips(profile):
    d = vp.voice_dir(profile)
    return sorted(p for p in d.glob("clip_*.wav") if p.with_suffix(".txt").exists())


def total_minutes(clips):
    secs = 0.0
    for p in clips:
        try:
            with wave.open(str(p), "rb") as w:
                secs += w.getnframes() / w.getframerate()
        except Exception:
            pass
    return secs / 60


class VoiceTrainingWindow:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.sentences = load_sentences()
        self.profile = app.cfg.get("profile") or (vp.list_profiles() or [vp.create_profile("User")])[0]
        self.state = self._load_state()
        self.recording = False
        self.buf = []
        self.last_audio = None
        self.proc = None

        w = self.win = tk.Toplevel(self.root)
        w.title("Voice profiles")
        w.attributes("-topmost", True)
        w.geometry("780x560")
        w.protocol("WM_DELETE_WINDOW", self.close)
        family = app.text.cget("font").split(" ")[0].strip("{}") or "Ebrima"

        # ---------------- profile bar
        pb = ttk.Frame(w, padding=(10, 8, 10, 0))
        pb.pack(fill="x")
        ttk.Label(pb, text="Who's dictating:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.profile_var = tk.StringVar(value=self.profile)
        self.profile_box = ttk.Combobox(pb, textvariable=self.profile_var, state="readonly", width=22,
                                        values=vp.list_profiles())
        self.profile_box.pack(side="left", padx=6)
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: self.switch_profile(self.profile_var.get()))
        ttk.Button(pb, text="New…", command=self.new_profile).pack(side="left")
        ttk.Button(pb, text="Delete", command=self.delete_profile).pack(side="right")
        ttk.Button(pb, text="Import…", command=self.import_profile).pack(side="right", padx=4)
        ttk.Button(pb, text="Export…", command=self.export_profile).pack(side="right")
        self.profile_info = ttk.Label(w, text="", padding=(10, 4), foreground="#245")
        self.profile_info.pack(fill="x")

        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # ---------------- Record tab
        rec = ttk.Frame(nb, padding=12)
        nb.add(rec, text="1. Setup reading")
        self.count_lbl = ttk.Label(rec, text="", font=("Segoe UI", 10))
        self.count_lbl.pack(anchor="w")
        ttk.Label(rec, text="Read this sentence aloud, at your normal speed:", foreground="#555").pack(anchor="w", pady=(10, 2))
        self.sentence_lbl = tk.Label(rec, text="", font=(family, 20), wraplength=700, justify="left",
                                     bg="#f4f4f4", padx=12, pady=12, anchor="w")
        self.sentence_lbl.pack(fill="x")
        self.meter = tk.Canvas(rec, height=10, bg="#ddd", highlightthickness=0)
        self.meter.pack(fill="x", pady=(10, 2))
        self.meter_bar = self.meter.create_rectangle(0, 0, 0, 10, fill="#3ddc84", width=0)
        self.msg = ttk.Label(rec, text="", foreground="#a33")
        self.msg.pack(anchor="w")

        btns = ttk.Frame(rec)
        btns.pack(fill="x", pady=10)
        self.rec_btn = ttk.Button(btns, text="●  Record", command=self.toggle_record)
        self.rec_btn.pack(side="left")
        self.play_btn = ttk.Button(btns, text="▶  Play back", command=self.play, state="disabled")
        self.play_btn.pack(side="left", padx=6)
        self.save_btn = ttk.Button(btns, text="✓  Save & next", command=self.save_next, state="disabled")
        self.save_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="Skip sentence", command=self.skip).pack(side="right")
        ttk.Label(rec, text="Press Record, read the whole sentence at your normal speed, then press Stop. "
                            f"Setup needs {SETUP_CLIPS} sentences (about 5–10 minutes). Reading more later — up to "
                            f"{TARGET_CLIPS} — makes your profile more accurate. You can stop any time and continue later.",
                  wraplength=700, foreground="#555").pack(anchor="w", pady=(6, 0))

        # ---------------- Train tab
        tr = ttk.Frame(nb, padding=12)
        nb.add(tr, text="2. Train profile")
        self.train_info = ttk.Label(tr, text="", wraplength=700, justify="left")
        self.train_info.pack(anchor="w")
        self.progress = ttk.Progressbar(tr, mode="determinate", length=700)
        self.progress.pack(fill="x", pady=12)
        self.train_status = ttk.Label(tr, text="", wraplength=700, justify="left")
        self.train_status.pack(anchor="w")
        tb = ttk.Frame(tr)
        tb.pack(fill="x", pady=12)
        self.train_btn = ttk.Button(tb, text="Start training", command=self.start_training)
        self.train_btn.pack(side="left")
        self.cancel_btn = ttk.Button(tb, text="Stop training", command=self.stop_training, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.use_var = tk.BooleanVar(value=True)
        self.use_chk = ttk.Checkbutton(tb, text="Use this voice profile when dictating", variable=self.use_var,
                                       command=self.toggle_use)
        self.use_chk.pack(side="right")
        ttk.Label(tr, text="Training runs in the background on this computer (no internet) and usually takes 15–40 "
                           "minutes. It builds a small add-on for this voice — the shared speech model is never "
                           "changed, so other profiles are not affected. The add-on is only switched on if it is more "
                           "accurate for this voice than no profile, and it loads automatically when training ends. "
                           "You can keep using the app while it trains.",
                  wraplength=700, foreground="#555").pack(anchor="w", pady=(8, 0))

        # ---------------- My words tab
        mw = ttk.Frame(nb, padding=12)
        nb.add(mw, text="3. My words")
        ttk.Label(mw, text="Names, places and terms you use (one per line). The app prefers these words, corrects "
                           "near-misses to them, and never marks them as misspelled. You can also click a word while "
                           "dictating and press “★ My words”.", wraplength=720, foreground="#555").pack(anchor="w")
        row = ttk.Frame(mw); row.pack(fill="x", pady=8)
        self.word_entry = tk.Entry(row, font=(family, 14))
        self.word_entry.pack(side="left", fill="x", expand=True)
        self.word_entry.bind("<Return>", lambda e: self.add_word())
        ttk.Button(row, text="Add", command=self.add_word).pack(side="left", padx=6)
        lf = ttk.Frame(mw); lf.pack(fill="both", expand=True)
        self.words_list = tk.Listbox(lf, font=(family, 13), height=8, selectmode="extended")
        sb = ttk.Scrollbar(lf, command=self.words_list.yview)
        self.words_list.config(yscrollcommand=sb.set)
        self.words_list.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        ttk.Button(mw, text="Remove selected", command=self.remove_words).pack(anchor="w", pady=(6, 0))

        # ---------------- Learning tab
        lr = ttk.Frame(nb, padding=12)
        nb.add(lr, text="4. Learning")
        self.learn_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(lr, text="Learn from my corrections", variable=self.learn_var,
                        command=self.save_learning).pack(anchor="w")
        ttk.Label(lr, text="When you fix a word while dictating and then press Done, the audio of that sentence and "
                           "your corrected words are saved in this profile (on this computer only) and used the next "
                           "time the profile is trained. Sentences you cancel are never saved. Turn this off when "
                           "dictating confidential information if it must not be stored.",
                  wraplength=720, foreground="#555").pack(anchor="w", padx=(22, 0))
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(lr, text=f"Retrain automatically after {AUTO_RETRAIN_AFTER} new corrections "
                                 "(in the background, when you are not dictating)",
                        variable=self.auto_var, command=self.save_learning).pack(anchor="w", pady=(14, 0))
        self.learn_info = ttk.Label(lr, text="", wraplength=720)
        self.learn_info.pack(anchor="w", pady=(14, 0))
        ttk.Button(lr, text="Delete saved corrections", command=self.clear_corrections).pack(anchor="w", pady=(10, 0))

        self.app.recorder_tap = self._on_audio
        self.show_sentence()
        self.refresh_counts()
        self.refresh_profile()
        if training_running(self.profile):
            self.train_btn.config(state="disabled")
            self.cancel_btn.config(state="normal")
        self._poll()

    # ---------------- state
    @property
    def state_path(self):
        return vp.voice_dir(self.profile) / "progress.json"

    def _load_state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            # each new profile starts at a different place in the list, so profiles read different sentences
            start = (sum(map(ord, self.profile)) * 97) % max(1, len(self.sentences))
            return {"next": start}

    def _save_state(self):
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")

    # ---------------- profiles
    def refresh_profile(self):
        names = vp.list_profiles()
        self.profile_box.config(values=names)
        self.profile_var.set(self.profile)
        meta = vp.load_meta(self.profile)
        res = meta.get("result")
        has = vp.adapter_path(self.profile).exists()
        self.use_var.set(bool(meta.get("use_adapter", True)))
        self.use_chk.config(state="normal" if has else "disabled")
        if has and res:
            info = (f"Voice profile trained {res.get('date', '')} on {res.get('clips', 0)} sentences — "
                    f"{res.get('base_cer', 0):.0%} → {res.get('new_cer', 0):.0%} letters wrong on your test recordings.")
            if not meta.get("use_adapter", True):
                info += "  (switched off)"
        else:
            info = "This profile has no voice training yet — do the setup reading, then train."
        self.profile_info.config(text=info)
        # my words + learning
        self.words_list.delete(0, "end")
        for w in vp.load_my_words(self.profile):
            self.words_list.insert("end", w)
        self.learn_var.set(bool(meta.get("learn_from_corrections", False)))
        self.auto_var.set(bool(meta.get("auto_retrain", True)))
        from learning import count_corrections
        n = count_corrections(vp.voice_dir(self.profile))
        new = n - int(meta.get("last_trained_corrections", 0))
        self.learn_info.config(text=f"Saved corrections: {n}  •  new since last training: {max(0, new)}")

    # ---------------- my words
    def add_word(self):
        w = " ".join(self.word_entry.get().split())
        if not w:
            return
        vp.add_my_word(self.profile, w)
        self.word_entry.delete(0, "end")
        self.app.apply_my_words()
        self.refresh_profile()

    def remove_words(self):
        sel = set(self.words_list.curselection())
        keep = [w for i, w in enumerate(vp.load_my_words(self.profile)) if i not in sel]
        vp.save_my_words(self.profile, keep)
        self.app.apply_my_words()
        self.refresh_profile()

    # ---------------- learning
    def save_learning(self):
        meta = vp.load_meta(self.profile)
        meta["learn_from_corrections"] = bool(self.learn_var.get())
        meta["auto_retrain"] = bool(self.auto_var.get())
        vp.save_meta(self.profile, meta)
        self.app.apply_learning()

    def clear_corrections(self):
        d = vp.voice_dir(self.profile)
        files = list(d.glob("corr_*"))
        if not files:
            return
        if not messagebox.askyesno("Delete corrections", f"Delete {len(files) // 2} saved corrections for "
                                   f"“{self.profile}”? Your setup reading is kept.", parent=self.win):
            return
        for f in files:
            f.unlink(missing_ok=True)
        meta = vp.load_meta(self.profile); meta["last_trained_corrections"] = 0; vp.save_meta(self.profile, meta)
        self.refresh_profile()

    def _busy_training(self):
        return training_running(self.profile)

    def switch_profile(self, name):
        if name == self.profile:
            return
        if self._busy_training() or self.recording:
            messagebox.showinfo("Voice profiles", "Wait for recording/training to finish before switching.", parent=self.win)
            self.profile_var.set(self.profile)
            return
        self.profile = name
        self.state = self._load_state()
        new = dict(self.app.cfg); new["profile"] = name
        self.app.apply_settings(new)
        self.show_sentence(); self.refresh_counts(); self.refresh_profile()
        self.train_status.config(text=""); self.progress["value"] = 0

    def new_profile(self):
        name = simpledialog.askstring("New voice profile", "Name for the new profile:", parent=self.win)
        if name:
            self.switch_profile(vp.create_profile(name))

    def delete_profile(self):
        if len(vp.list_profiles()) <= 1:
            messagebox.showinfo("Voice profiles", "You need at least one profile. Create another one first.", parent=self.win)
            return
        if self._busy_training():
            return
        n = len(list_clips(self.profile))
        if not messagebox.askyesno("Delete profile",
                                   f"Delete the profile “{self.profile}” and its {n} recordings?\n\nThis cannot be undone.",
                                   parent=self.win):
            return
        old = self.profile
        other = [p for p in vp.list_profiles() if p != old][0]
        self.switch_profile(other)
        vp.delete_profile(old)
        self.refresh_profile()

    def export_profile(self):
        path = filedialog.asksaveasfilename(parent=self.win, title="Export voice profile",
                                            initialfile=f"{self.profile} voice profile.zip",
                                            defaultextension=".zip", filetypes=[("Voice profile", "*.zip")])
        if path:
            vp.export_profile(self.profile, path)
            messagebox.showinfo("Voice profiles", f"Saved to:\n{path}", parent=self.win)

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self.win, title="Import voice profile",
                                          filetypes=[("Voice profile", "*.zip")])
        if not path:
            return
        try:
            name = vp.import_profile(path)
        except Exception as e:
            messagebox.showerror("Voice profiles", f"Could not import: {e}", parent=self.win)
            return
        self.switch_profile(name)

    def toggle_use(self):
        meta = vp.load_meta(self.profile)
        meta["use_adapter"] = bool(self.use_var.get())
        vp.save_meta(self.profile, meta)
        self.refresh_profile()            # the app notices the change and reloads the model

    def current_sentence(self):
        if not self.sentences:
            return "(training_sentences.txt is missing)"
        return self.sentences[self.state.get("next", 0) % len(self.sentences)]

    def show_sentence(self):
        self.sentence_lbl.config(text=self.current_sentence())
        self.last_audio = None
        self.play_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.msg.config(text="")

    def refresh_counts(self):
        clips = list_clips(self.profile)
        mins = total_minutes(clips)
        goal = SETUP_CLIPS if len(clips) < SETUP_CLIPS else TARGET_CLIPS
        label = "setup" if goal == SETUP_CLIPS else "for best accuracy"
        self.count_lbl.config(text=f"{self.profile}: {len(clips)} sentences recorded ({mins:.0f} min)   •   "
                                   f"goal {label}: {goal}")
        ready = len(clips) >= MIN_CLIPS
        self.train_info.config(text=(
            f"{self.profile} has {len(clips)} recordings ({mins:.0f} minutes). "
            + (f"Ready to train. Reading more sentences (up to {TARGET_CLIPS}) makes the profile more accurate; "
               "you can retrain any time." if ready else
               f"Record at least {MIN_CLIPS} sentences before training ({SETUP_CLIPS} recommended).")))
        if not self._busy_training():
            self.train_btn.config(state="normal" if ready else "disabled")

    # ---------------- recording
    def _on_audio(self, block):
        if self.recording:
            self.buf.append(block.copy())

    def toggle_record(self):
        if self.app.active:
            self.msg.config(text="Stop dictation first (Ctrl+Alt+Space).")
            return
        if not self.recording:
            self.buf = []
            self.recording = True
            self.rec_btn.config(text="■  Stop")
            self.msg.config(text="Recording… read the sentence, then press Stop.", foreground="#a33")
            self.play_btn.config(state="disabled")
            self.save_btn.config(state="disabled")
        else:
            self.recording = False
            self.rec_btn.config(text="●  Re-record")
            audio = np.concatenate(self.buf) if self.buf else np.zeros(0, np.float32)
            dur = len(audio) / SR
            peak = float(np.abs(audio).max()) if len(audio) else 0.0
            if dur < 1.0:
                self.msg.config(text="Too short — record the whole sentence.", foreground="#a33")
                return
            self.last_audio = audio
            self.play_btn.config(state="normal")
            self.save_btn.config(state="normal")
            if peak < 0.02:
                self.msg.config(text=f"Very quiet ({dur:.1f}s). Move closer to the mic or raise its volume, then re-record "
                                     "— or save anyway.", foreground="#a60")
            elif peak > 0.98:
                self.msg.config(text=f"Too loud / distorted ({dur:.1f}s). Move back a little and re-record.", foreground="#a60")
            else:
                self.msg.config(text=f"Recorded {dur:.1f}s. Play it back, or Save & next.", foreground="#2a7")

    def play(self):
        if self.last_audio is not None:
            try:
                import sounddevice as sd
                sd.play(self.last_audio, SR)
            except Exception as e:
                self.msg.config(text=f"Playback failed: {e}")

    def save_next(self):
        if self.last_audio is None:
            return
        d = vp.voice_dir(self.profile)
        n = max([int(p.stem.split("_")[1]) for p in d.glob("clip_*.wav")] + [-1]) + 1
        base = d / f"clip_{n:05d}"
        pcm = (np.clip(self.last_audio, -1, 1) * 32767).astype("<i2")
        with wave.open(str(base.with_suffix(".wav")), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        base.with_suffix(".txt").write_text(self.current_sentence(), encoding="utf-8")
        self.state["next"] = self.state.get("next", 0) + 1
        self._save_state()
        self.rec_btn.config(text="●  Record")
        self.show_sentence()
        self.refresh_counts()

    def skip(self):
        self.recording = False
        self.rec_btn.config(text="●  Record")
        self.state["next"] = self.state.get("next", 0) + 1
        self._save_state()
        self.show_sentence()

    # ---------------- training
    def _progress_path(self):
        return progress_path(self.profile)

    def start_training(self):
        if training_running(self.profile):
            return
        self.proc = launch_training(self.app.cfg, self.profile)
        self.train_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.train_status.config(text="Starting… loading the model (about a minute).")

    def stop_training(self):
        if training_running(self.profile):
            RUNNING[self.profile].terminate()
        self.cancel_btn.config(state="disabled")
        self.train_status.config(text="Training stopped. Nothing was changed.")
        self.refresh_counts()

    def _poll(self):
        if not self.win.winfo_exists():
            return
        level = float(np.sqrt(np.mean(self.buf[-1] ** 2))) if (self.recording and self.buf) else 0.0
        width = self.meter.winfo_width()
        self.meter.coords(self.meter_bar, 0, 0, min(width, int(level * width * 12)), 10)
        try:
            p = json.loads(self._progress_path().read_text(encoding="utf-8"))
            self.progress["value"] = 100.0 * p.get("fraction", 0.0)
            self.train_status.config(text=p.get("message", ""))
            if p.get("done") and self.cancel_btn.cget("state") == "normal":
                self.cancel_btn.config(state="disabled")
                self.refresh_counts(); self.refresh_profile()
        except Exception:
            pass
        if not training_running(self.profile) and self.cancel_btn.cget("state") == "normal":
            self.cancel_btn.config(state="disabled")
            self.refresh_counts()
        self.win.after(150, self._poll)

    def close(self):
        self.recording = False
        self.app.recorder_tap = None
        self.win.destroy()
