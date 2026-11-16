"""
Re-transcribe the most recent debug recording with different settings and report
accuracy-relevant output + speed. Writes debug/diagnose.txt.
"""
import glob
import json
import os
import sys
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from config import load_config            # noqa: E402
from engine import SR, Transcriber, ensure_model   # noqa: E402

out_lines = []


def log(s=""):
    print(s)
    out_lines.append(s)


def load_wav(path):
    with wave.open(path, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return pcm


def chunks(a, sec=15):
    n = sec * SR
    return [a[i:i + n] for i in range(0, len(a), n)] or [a]


def main():
    wavs = sorted(glob.glob(os.path.join(HERE, "debug", "session-*.wav")))
    if not wavs:
        log("No recordings in debug\\. Dictate once with debug_audio.flag present.")
        return
    path = wavs[-1]
    audio = load_wav(path)
    cfg = load_config()
    log(f"Recording: {os.path.basename(path)}  length={len(audio)/SR:.1f}s")
    log(f"Mic level: peak={np.abs(audio).max():.3f}  rms={np.sqrt(np.mean(audio**2)):.4f}  "
        f"(clipping if peak≈1.0; too quiet if rms<0.01)")
    log(f"Model: {cfg['model']}")
    model_path = ensure_model(cfg["model"])

    for label, quant in (("int8 (current)", True), ("full precision", False)):
        t0 = time.perf_counter()
        tr = Transcriber(model_path, "cpu", quant)
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        text = " ".join(t for t in (tr(c) for c in chunks(audio)) if t)
        took = time.perf_counter() - t0
        log("")
        log(f"=== {label}: load {load_s:.1f}s, transcribe {took:.1f}s for {len(audio)/SR:.1f}s audio "
            f"(RTF {took / (len(audio)/SR):.2f})")
        log(text or "(no text)")
        del tr

    txt = path.replace(".wav", ".txt")
    if os.path.exists(txt):
        log("")
        log("=== Live session timings (from the app)")
        log(open(txt, encoding="utf-8").read())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("ERROR: " + traceback.format_exc())
    finally:
        os.makedirs(os.path.join(HERE, "debug"), exist_ok=True)
        with open(os.path.join(HERE, "debug", "diagnose.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines) + "\n")
