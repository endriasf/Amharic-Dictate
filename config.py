import json
import os
import sys
import time
from pathlib import Path

APP_NAME = "AmharicDictate"
APP_VERSION = "2.3.0"

MODEL_PRESETS = [
    ("badrex/Ethio-ASR-amharic", "Ethio-ASR Amharic — best accuracy (non-commercial license)"),
    ("badrex/Ethio-ASR-multilingual-94M", "Ethio-ASR 94M — fastest, for older PCs (non-commercial)"),
    ("agkphysics/wav2vec2-large-xlsr-53-amharic", "wav2vec2 XLSR Amharic — read-speech baseline"),
]

DEFAULT_CONFIG = {
    "model": MODEL_PRESETS[0][0],
    "device": "auto",            # auto | cpu | cuda
    "fast_preview": True,
    "auto_level": True,          # even out quiet/fading speech before recognition
    "lm_decoding": True,         # use the Amharic dictionary when choosing letters (final text)
    "lm_weight": 0.25,           # how strongly the dictionary influences unclear words
    "min_confidence": 0.45,      # drop pieces the model is very unsure about (background talk, noise)        # fast int8 copy for the live preview (uses ~1 GB more memory)
    "quantize_cpu": False,       # int8 is faster but drops words; full precision is fast enough
    "mode": "toggle",            # toggle | hold
    "hotkey": "ctrl+alt+space",
    "hold_key": "right ctrl",
    "pause_hotkey": "ctrl+alt+p",          # pause/resume while dictating
    "delete_hotkey": "ctrl+alt+backspace", # delete the last word while dictating
    "undo_hotkey": "ctrl+alt+z",           # undo the last change while dictating (14 steps)
    "insert": "on_stop",         # on_stop | per_phrase | clipboard
    "voice_commands": True,
    "numbers_to_digits": True,
    "auto_period": False,
    "spellcheck": True,          # red underline on words that look misspelled
    "autocorrect_spelling": True, # fix sound-alike misspellings using the Amharic dictionary
    "model_punctuation": False,  # let the model insert ። ፣ ? by itself (it often guesses wrong)
    "silence_ms": 700,
    "max_phrase_s": 6,           # long speech is split at a natural gap this often
    "partial_every_s": 0.6,
    "min_threshold": 0.0012,      # quietest level treated as speech
    "beep": True,
    "font": "Nyala",
    "font_size": 18,
    "start_with_windows": False,
    "save_history": False,       # transcripts may contain sensitive information
    "profile": "",               # active voice profile (folder under %APPDATA%\\AmharicDictate\\profiles)
    "config_version": 8,
}


def app_dir() -> Path:
    d = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    saved = {}
    p = config_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            log_error("config.json invalid; using defaults")
    cfg.update(saved)
    version = saved.get("config_version", 1) if saved else DEFAULT_CONFIG["config_version"]
    if version < 4:                       # older installs: apply tuned speech-detection defaults
        cfg["max_phrase_s"] = DEFAULT_CONFIG["max_phrase_s"]
        cfg["min_threshold"] = DEFAULT_CONFIG["min_threshold"]
    if version < 8:                       # gentler dictionary decoding
        cfg["lm_weight"] = DEFAULT_CONFIG["lm_weight"]
    if version < 7:
        cfg["partial_every_s"] = DEFAULT_CONFIG["partial_every_s"]
    if version < 6:                       # shorter phrases keep the live preview from lagging
        cfg["max_phrase_s"] = DEFAULT_CONFIG["max_phrase_s"]
    if version < 5:                       # full precision measured noticeably more accurate
        cfg["quantize_cpu"] = False
    cfg["config_version"] = DEFAULT_CONFIG["config_version"]
    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def log_error(msg: str):
    with open(app_dir() / "error.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def set_start_with_windows(enabled: bool):
    """Add/remove HKCU Run entry (per-user, no admin needed)."""
    try:
        import winreg
    except ImportError:
        return
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        cmd = f'"{pyw}" "{Path(__file__).with_name("app.py").resolve()}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
