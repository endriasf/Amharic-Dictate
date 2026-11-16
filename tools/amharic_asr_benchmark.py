#!/usr/bin/env python3
"""
Amharic ASR benchmark — compare candidate offline models on YOUR recordings.

Measures, per model:
  * WER / CER  (after Amharic homophone + punctuation normalization)
  * RTF        (real-time factor = processing time / audio duration; < 1.0 is faster than real time)
  * Load time  (seconds to load the model)

---------------------------------------------------------------------------
SETUP
  python -m venv .venv && source .venv/bin/activate      # Windows: .venv\\Scripts\\activate
  pip install torch transformers librosa soundfile accelerate

DATA  (one folder, matched pairs by file name)
  clips/
    001.wav   001.txt      <- .txt holds the correct Amharic transcript (UTF-8)
    002.m4a   002.txt      <- wav, flac, mp3, m4a, ogg all fine (resampled to 16 kHz)
  Tip: 20–30 clips, 5–30 s each, mixing quiet room / noisy room / fast speech /
  names & numbers. Record on the mic you'll actually use.

RUN
  python amharic_asr_benchmark.py --data clips
  python amharic_asr_benchmark.py --data clips --models badrex/Ethio-ASR-amharic BuzzASR/amharic
  python amharic_asr_benchmark.py --data clips --device cpu     # simulate a laptop with no GPU

OUTPUT
  results_per_clip.csv   every clip × model: reference, hypothesis, WER, CER, RTF
  results_summary.csv    one row per model (also printed as a table)
---------------------------------------------------------------------------
Note: the Ethio-ASR models are CC-BY-NC 4.0 (non-commercial). Check each model
card's license before shipping anything.
"""

import argparse
import csv
import gc
import re
import sys
import time
import unicodedata
from pathlib import Path

DEFAULT_MODELS = [
    "badrex/Ethio-ASR-amharic",                    # Amharic-only CTC (top on telecom benchmark)
    "badrex/Ethio-ASR-multilingual-94M",           # small CTC, phone/laptop friendly
    "agkphysics/wav2vec2-large-xlsr-53-amharic",   # 316M CTC, read-speech baseline
    # "BuzzASR/amharic",                           # Whisper-large-v3 fine-tune; heavy, uncomment to try
]

AUDIO_EXTS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}
SR = 16000

# --------------------------------------------------------------------------
# Amharic normalization
# --------------------------------------------------------------------------
# Homophone series that sound identical in modern Amharic. Each Ethiopic
# "series" is 8 code points; offsets 0-6 are the 7 vowel orders.
_HOMOPHONE_SERIES = {
    0x1210: 0x1200,  # ሐ-series -> ሀ-series
    0x1280: 0x1200,  # ኀ-series -> ሀ-series
    0x1220: 0x1230,  # ሠ-series -> ሰ-series
    0x12D0: 0x12A0,  # ዐ-series -> አ-series
    0x1340: 0x1338,  # ፀ-series -> ጸ-series
}
_HOMOPHONE_MAP = {
    src + i: dst + i
    for src, dst in _HOMOPHONE_SERIES.items()
    for i in range(7)
}
# ሃ/ኣ (4th order) are pronounced like ሀ/አ (1st order) and spelled either way,
# e.g. ዓለም / ኣለም / አለም.  Apply after the series map above.
_HOMOPHONE_MAP.update({0x1203: 0x1200, 0x12A3: 0x12A0})
_HOMOPHONE_MAP.update({k: _HOMOPHONE_MAP.get(v, v) for k, v in _HOMOPHONE_MAP.items()})

# Ethiopic punctuation ፡ ። ፣ ፤ ፥ ፦ ፧ ፨ plus general punctuation.
_ETHIOPIC_PUNCT = "፡።፣፤፥፦፧፨"
_TAG_RE = re.compile(r"<[^>]*>|\[[^\]]*\]")   # e.g. language-ID tags some models emit
_PUNCT_RE = re.compile(rf"[{_ETHIOPIC_PUNCT}]|[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_amharic(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _TAG_RE.sub(" ", text)
    text = text.translate(_HOMOPHONE_MAP)
    text = _PUNCT_RE.sub(" ", text)
    text = text.lower()                       # only affects any Latin text mixed in
    return _SPACE_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------
# Metrics (no extra dependency)
# --------------------------------------------------------------------------
def _edit_distance(ref, hyp) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def error_counts(ref: str, hyp: str):
    """Return (word_errors, ref_words, char_errors, ref_chars) on normalized text."""
    rw, hw = ref.split(), hyp.split()
    rc, hc = ref.replace(" ", ""), hyp.replace(" ", "")
    return _edit_distance(rw, hw), len(rw), _edit_distance(rc, hc), len(rc)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load_dataset(folder: Path):
    pairs = []
    for audio in sorted(folder.iterdir()):
        if audio.suffix.lower() not in AUDIO_EXTS:
            continue
        ref_file = audio.with_suffix(".txt")
        if not ref_file.exists():
            print(f"  ! skipping {audio.name}: no matching {ref_file.name}", file=sys.stderr)
            continue
        pairs.append((audio, ref_file.read_text(encoding="utf-8").strip()))
    if not pairs:
        sys.exit(f"No audio+txt pairs found in {folder}")
    return pairs


def load_audio(path: Path):
    import librosa
    audio, _ = librosa.load(str(path), sr=SR, mono=True)
    return audio


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
def pick_device(requested: str):
    import torch
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_pipeline(model_id: str, device: str):
    import torch
    from transformers import pipeline

    dtype = torch.float16 if device == "cuda" else torch.float32
    asr = pipeline(
        "automatic-speech-recognition",
        model=model_id,
        device=device,
        torch_dtype=dtype,
    )
    gen_kwargs = {}
    if asr.model.config.model_type == "whisper":
        gen_kwargs = {"num_beams": 1, "no_repeat_ngram_size": 3, "repetition_penalty": 1.2}
    return asr, gen_kwargs


def transcribe(asr, gen_kwargs, audio):
    kwargs = {"chunk_length_s": 30, "stride_length_s": 5} if len(audio) > 30 * SR else {}
    if gen_kwargs:
        kwargs["generate_kwargs"] = gen_kwargs
    out = asr({"raw": audio, "sampling_rate": SR}, **kwargs)
    return out["text"]


def sync(device):
    import torch
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def free(device):
    import torch
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="folder of audio + matching .txt files")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()

    device = pick_device(args.device)
    print(f"Device: {device}")

    dataset = load_dataset(args.data)
    print(f"Loading {len(dataset)} clips…")
    clips = [(p, ref, load_audio(p)) for p, ref in dataset]
    total_audio_s = sum(len(a) for _, _, a in clips) / SR
    print(f"Total audio: {total_audio_s:.1f} s\n")

    per_clip_rows, summary_rows = [], []

    for model_id in args.models:
        print(f"=== {model_id}")
        try:
            t0 = time.perf_counter()
            asr, gen_kwargs = build_pipeline(model_id, device)
            load_s = time.perf_counter() - t0
        except Exception as e:  # noqa: BLE001
            print(f"  ! failed to load: {e}\n")
            summary_rows.append({"model": model_id, "error": str(e)[:200]})
            continue

        # Warm-up so the first clip's timing isn't skewed by kernel compilation.
        transcribe(asr, gen_kwargs, clips[0][2][: SR * 2])

        tot = {"we": 0, "rw": 0, "ce": 0, "rc": 0, "proc": 0.0}
        for path, ref, audio in clips:
            sync(device)
            t0 = time.perf_counter()
            hyp = transcribe(asr, gen_kwargs, audio)
            sync(device)
            proc = time.perf_counter() - t0

            ref_n, hyp_n = normalize_amharic(ref), normalize_amharic(hyp)
            we, rw, ce, rc = error_counts(ref_n, hyp_n)
            dur = len(audio) / SR
            for k, v in zip(("we", "rw", "ce", "rc", "proc"), (we, rw, ce, rc, proc)):
                tot[k] += v

            per_clip_rows.append({
                "model": model_id,
                "clip": path.name,
                "duration_s": round(dur, 2),
                "wer": round(we / max(rw, 1), 4),
                "cer": round(ce / max(rc, 1), 4),
                "rtf": round(proc / dur, 3),
                "reference": ref,
                "hypothesis": hyp,
            })
            print(f"  {path.name:<24} WER {we / max(rw, 1):6.1%}  CER {ce / max(rc, 1):6.1%}  RTF {proc / dur:5.2f}")

        row = {
            "model": model_id,
            "wer": round(tot["we"] / max(tot["rw"], 1), 4),
            "cer": round(tot["ce"] / max(tot["rc"], 1), 4),
            "rtf": round(tot["proc"] / total_audio_s, 3),
            "load_s": round(load_s, 1),
            "params_m": round(sum(p.numel() for p in asr.model.parameters()) / 1e6),
            "error": "",
        }
        summary_rows.append(row)
        print(f"  -> WER {row['wer']:.1%}  CER {row['cer']:.1%}  RTF {row['rtf']:.2f}  ({row['params_m']}M params)\n")

        del asr
        free(device)

    # ---- write results
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "results_per_clip.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["model", "clip", "duration_s", "wer", "cer", "rtf", "reference", "hypothesis"])
        w.writeheader()
        w.writerows(per_clip_rows)

    fields = ["model", "wer", "cer", "rtf", "load_s", "params_m", "error"]
    with open(args.out / "results_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(summary_rows)

    # ---- print ranking
    ok = sorted((r for r in summary_rows if not r.get("error")), key=lambda r: r["wer"])
    print("=" * 78)
    print(f"{'model':<46}{'WER':>7}{'CER':>7}{'RTF':>7}{'params':>9}")
    for r in ok:
        print(f"{r['model']:<46}{r['wer']:>7.1%}{r['cer']:>7.1%}{r['rtf']:>7.2f}{r['params_m']:>8}M")
    for r in summary_rows:
        if r.get("error"):
            print(f"{r['model']:<46}  FAILED: {r['error'][:30]}")
    print("=" * 78)
    print("Live use needs RTF well under 1.0 on your target hardware (aim for < 0.3).")
    print(f"Wrote {args.out / 'results_per_clip.csv'} and {args.out / 'results_summary.csv'}")


if __name__ == "__main__":
    main()
