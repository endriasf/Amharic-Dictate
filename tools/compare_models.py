"""
Compare speech models on the same recordings: your voice-profile reading sentences
(clip_*.wav + clip_*.txt in %APPDATA%\\AmharicDictate\\profiles\\*\\voice_data).

For each model it reports word and letter error rates, both for the raw model output and with the
app's dictionary-guided decoding. Results are printed and saved to compare_results.txt.

  python tools\\compare_models.py MODEL [MODEL ...]
  MODEL = a Hugging Face id (e.g. badrex/Ethio-ASR-amharic) or a local folder.

  python tools\\compare_models.py --dump OUT.npz MODEL
      saves the model's per-frame letter probabilities for every recording (for tuning the decoder).
"""
import os
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

here = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(here))

from config import app_dir                      # noqa: E402

_PUNCT = re.compile(r"[።፣፤፥፦፧?!.,:;\"'«»()\[\]\-]")


def norm(text):
    text = unicodedata.normalize("NFC", text)
    return " ".join(_PUNCT.sub(" ", text).split())


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def rates(pairs):
    we = rw = ce = rc = 0
    for ref, hyp in pairs:
        r, h = norm(ref), norm(hyp)
        we += edit_distance(r.split(), h.split()); rw += len(r.split())
        ce += edit_distance(r.replace(" ", ""), h.replace(" ", "")); rc += len(r.replace(" ", ""))
    return we / max(rw, 1), ce / max(rc, 1)


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def find_clips():
    clips = []
    for d in sorted((app_dir() / "profiles").glob("*/voice_data")):
        for wav in sorted(d.glob("clip_*.wav")):
            txt = wav.with_suffix(".txt")
            if txt.exists():
                clips.append((wav, txt.read_text(encoding="utf-8").strip()))
    return clips


def main():
    for stream in (sys.stdout, sys.stderr):        # Amharic text in logs (Windows defaults to cp1252)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = sys.argv[1:]
    dump = None
    if args[:1] == ["--dump"]:
        dump, args = args[1], args[2:]
    models = args or ["badrex/Ethio-ASR-amharic"]
    clips = find_clips()
    if not clips:
        print("No voice-profile recordings found (record some in Voice profiles first).")
        return 1
    print(f"{len(clips)} recordings, {sum(len(load_wav(w)) for w, _ in clips) / 16000 / 60:.1f} minutes\n")
    from engine import Transcriber, ensure_model
    if dump:
        import json
        import torch
        from lmdecode import level_audio
        tr = Transcriber(ensure_model(models[0], print), "cpu", False, use_lm=False, auto_level=True)
        arrays, refs = {}, []
        for i, (wav, ref) in enumerate(clips):
            audio = level_audio(load_wav(wav), 16000)
            with torch.inference_mode():
                inputs = tr.processor(audio, sampling_rate=16000, return_tensors="pt")
                lp = tr.model(**inputs).logits[0].float().log_softmax(-1).numpy().astype(np.float16)
            arrays[f"c{i}"] = lp
            refs.append(ref)
            print(f"\r  dump {i + 1}/{len(clips)}", end="", flush=True)
        meta = {"model": models[0], "refs": refs, "blank": tr._blank,
                "id2tok": {str(k): v for k, v in tr._id2tok.items()}}
        np.savez_compressed(dump, meta=np.array(json.dumps(meta, ensure_ascii=False)), **arrays)
        print(f"\nSaved {dump}")
        return 0
    lines = []
    for m in models:
        path = ensure_model(m, print)
        t0 = time.time()
        tr = Transcriber(path, "cpu", False, use_lm=True, lm_weight=0.25, auto_level=True)
        plain, guided, samples = [], [], []
        from textproc import autocorrect, finish_phrase
        cfg = {"voice_commands": True, "numbers_to_digits": False, "model_punctuation": False}

        def app_text(raw):            # what the app would actually type (spoken commands applied)
            return autocorrect(finish_phrase(raw, cfg))[0]

        for i, (wav, ref) in enumerate(clips):
            hyp = tr(load_wav(wav))
            plain.append((ref, app_text(tr.last_greedy)))
            guided.append((ref, app_text(hyp)))
            if i < 3:
                samples.append(f"    said : {ref}\n    heard: {hyp}")
            print(f"\r  {m}: {i + 1}/{len(clips)}", end="", flush=True)
        pw, pc = rates(plain)
        gw, gc = rates(guided)
        secs = (time.time() - t0) / len(clips)
        line = (f"{m}\n  raw model      : {pw:6.1%} words wrong, {pc:6.1%} letters wrong\n"
                f"  with dictionary   : {gw:6.1%} words wrong, {gc:6.1%} letters wrong\n"
                f"  speed          : {secs:.2f} s per sentence\n" + "\n".join(samples))
        print("\n" + line + "\n")
        lines.append(line)
    out = here / "compare_results.txt"
    out.write_text(f"{len(clips)} recordings\n\n" + "\n\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
