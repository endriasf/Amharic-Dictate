"""Diagnose short phrases saved in decode_audio/ (opt-in diagnostics): try them a few ways."""
import glob, os, sys, wave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
from config import load_config
from engine import Transcriber, ensure_model
from voiceprofile import active_adapter

cfg = load_config()
path = ensure_model(cfg["model"])
profile, adapter = active_adapter(cfg)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = sorted(glob.glob(os.path.join(here, "decode_audio", "*.wav")))

def load(f):
    w = wave.open(f)
    return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768

def show(t, a, label):
    text = t(a)
    print(f"   {label:14s} -> '{text}'   plain='{t.last_greedy}' conf={t.last_confidence:.2f}  {t.last_spot}")

for name, ad in (("with profile", adapter), ("no profile", None)):
    print(f"===== {name}", flush=True)
    t = Transcriber(path, cfg["device"], cfg["quantize_cpu"], use_lm=True, auto_level=True,
                    min_confidence=0.0, adapter=ad)
    t.want_alternatives = False
    for f in files:
        a = load(f)
        if len(a) > 16000 * 3.5:
            continue
        print(os.path.basename(f), f"{len(a)/16000:.1f}s", flush=True)
        show(t, a, "as recorded")
        show(t, np.pad(a, 8000), "+0.5s silence")
        show(t, a / (np.abs(a).max() + 1e-9) * 0.5, "louder")
        lp = None
        with t.torch.inference_mode():
            x = t.processor(a / (np.abs(a).max() + 1e-9) * 0.5, sampling_rate=16000, return_tensors="pt")
            x = {k: v.to(t.device) for k, v in x.items()}
            if t.device == "cuda":
                x = {k: (v.half() if v.is_floating_point() else v) for k, v in x.items()}
            p = t.model(**x).logits[0].float().softmax(-1).cpu().numpy()
        frames = []
        for row in p:
            o = np.argsort(-row)
            nb = [(t._id2tok[i], row[i]) for i in o[:4] if i != t._blank and row[i] > 0.03]
            if nb:
                frames.append("/".join(f"{c}{v:.2f}" for c, v in nb[:2]))
        print("   letters heard:", " ".join(frames)[:400], flush=True)
