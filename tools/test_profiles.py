"""Smoke test for voice profiles: train a tiny add-on on synthetic clips, then load it into the Transcriber."""
import math, os, random, struct, sys, time, wave, json
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["HF_HUB_OFFLINE"] = "1"
out = os.path.join(here, "profile_test")
data = os.path.join(out, "voice_data"); os.makedirs(data, exist_ok=True)
sents = [l.strip() for l in open(os.path.join(here, "training_sentences.txt"), encoding="utf-8") if l.strip() and not l.startswith("#")][:14]
rnd = random.Random(1)
for i, s in enumerate(sents):
    n = int(16000 * (3 + rnd.random() * 2))
    fr = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * (180 + 40 * math.sin(k / 4000)) * k / 16000) * (0.5 + 0.5 * math.sin(k / 1600)) + rnd.gauss(0, 300))) for k in range(n))
    with wave.open(os.path.join(data, f"clip_{i:05d}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(fr)
    open(os.path.join(data, f"clip_{i:05d}.txt"), "w", encoding="utf-8").write(s)
from engine import ensure_model, Transcriber
import train_local
base = ensure_model("badrex/Ethio-ASR-amharic")
adapter = os.path.join(out, "adapter.pt")
t = time.time()
rc = train_local.main(["--base", base, "--base-name", "badrex/Ethio-ASR-amharic", "--data", data, "--out", adapter,
                       "--progress", os.path.join(out, "progress.json"), "--epochs", "1", "--max-steps", "6", "--always-save"])
print("train rc", rc, "seconds", round(time.time() - t))
print(open(os.path.join(out, "progress.json"), encoding="utf-8").read())
print("adapter MB", round(os.path.getsize(adapter) / 1e6, 1))
import voiceprofile, torch
from transformers import AutoModelForCTC
from int8model import load_ctc_model  # noqa: E402
m = load_ctc_model(base)
print("signature", voiceprofile.model_signature(m), "lora layers", len(voiceprofile.target_linears(m)))
tr = Transcriber(base, "cpu", False, adapter=adapter)
print("full merge problem:", repr(tr.profile_problem))
pv = Transcriber(base, "cpu", True, adapter=adapter)
print("int8 merge problem:", repr(pv.profile_problem))
import numpy as np
with wave.open(os.path.join(data, "clip_00000.wav")) as w:
    a = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768
print("transcribe ok:", repr(tr(a)))
print("ALL DONE")
