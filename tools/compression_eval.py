#!/usr/bin/env python3
"""
How small can the AmharicDictate speech model get before dictation gets worse?

Takes one CTC model (default Abittee/amharic-speech-to-text-efa-v1, w2v-BERT 2.0,
~0.6 B parameters, float32 ~2.4 GB) and scores several compressed versions of it on
the WAXAL Amharic test set and the FLEURS Amharic test set:

  fp32          the model as published (baseline)
  fp16          weights rounded to half precision (what shipping fp16 would give)
  int8          per-output-channel symmetric 8-bit weights on every nn.Linear
  pal6          6-bit palettisation: k-means, 64 values per Linear layer
  pal4          4-bit palettisation: k-means, 16 values per Linear layer
  int8-dynamic  torch.quantization.quantize_dynamic, exactly as the Windows app's
                live preview does it. CPU only and very slow (~4 h per 1000 clips on
                Colab), so it only runs when named: --variants fp32 int8-dynamic

fp16 / int8 / pal6 / pal4 are simulated: each weight is replaced by the value it would
have in that format and the model still runs in float32. That isolates the accuracy
effect of the storage format, which is what matters for deciding what to ship on an
iPhone (Core ML: palettisation = coremltools.optimize.coreml.palettize_weights,
int8 = linear_quantize_weights). Weights that are not inside an nn.Linear (convolutions,
layer norms, biases) are stored as fp16 in all compressed variants.

Decoding is greedy CTC (argmax, no dictionary or language model), like the published
numbers (WAXAL test: WER 24.4 %, CER 9.6 %). Text is scored with the same Amharic
normalisation as amharic_asr_benchmark.py (homophone letters such as ሀ/ሐ/ኀ and
punctuation are not counted as errors); test clips are loaded and length-filtered
(0.5-20 s) exactly as train_amharic_ctc.py does.

---------------------------------------------------------------------------
GOOGLE COLAB  (Runtime > Change runtime type > T4 GPU)
  !git clone https://github.com/endriasf/Amharic-Dictate
  %cd Amharic-Dictate/tools
  !pip install -q "transformers>=4.46" "datasets[audio]" soundfile librosa
  from huggingface_hub import notebook_login; notebook_login()   # if a dataset asks for it
  !python compression_eval.py --max-clips 500                     # quick run (~1 h on a T4)
  !python compression_eval.py                                     # full test sets

WINDOWS PC
  pip install torch "transformers>=4.46" "datasets[audio]" soundfile librosa
  python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500

OUTPUT  (in --out, default compression_results/)
  compression_summary.csv / compression_summary.md   one row per variant
  compression_per_clip.csv                            every clip x variant: reference, hypothesis
---------------------------------------------------------------------------
"""

import argparse
import csv
import io
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amharic_asr_benchmark import error_counts, normalize_amharic, pick_device  # noqa: E402
from train_amharic_ctc import SR, decode_audio, load_source  # noqa: E402

DEFAULT_MODEL = "Abittee/amharic-speech-to-text-efa-v1"
ALL_VARIANTS = ["fp32", "fp16", "int8", "pal6", "pal4", "int8-dynamic"]
DEFAULT_VARIANTS = ALL_VARIANTS[:-1]   # int8-dynamic is CPU-only: ~4 h per 1000 clips on Colab, so opt-in
DATASETS = {"waxal": "WAXAL amh_asr test", "fleurs": "FLEURS am_et test"}
MAX_WER_LOSS_PP = 0.5     # "no worse" threshold used for the recommendation

# --------------------------------------------------------------------------
# Weight transforms (each takes and returns a float32 tensor of the same shape)
# --------------------------------------------------------------------------


def round_fp16(w):
    """Round to the nearest float16 value, return as float32."""
    import torch
    return w.to(torch.float16).to(torch.float32)


def quant_int8_per_channel(w, bits: int = 8):
    """Symmetric per-output-channel (per row) weight quantisation, quantise-dequantise.
    Scales are stored in fp16, as Core ML / most runtimes do."""
    import torch
    qmax = 2 ** (bits - 1) - 1                         # 127: symmetric range [-127, 127]
    w2 = w.reshape(w.shape[0], -1)
    scale = w2.abs().amax(dim=1, keepdim=True) / qmax
    scale = round_fp16(scale)
    scale = torch.where(scale > 0, scale, torch.ones_like(scale))
    q = torch.clamp(torch.round(w2 / scale), -qmax, qmax)
    return (q * scale).reshape(w.shape)


def kmeans_1d(x, k: int, iters: int = 30, tol: float = 1e-7):
    """Batched 1-D k-means (Lloyd). x: (G, M) -> centroids (G, k) sorted, labels (G, M).
    In 1-D the nearest centroid is found by binary search against the midpoints,
    so this is fast even for 4 M-value layers. Initialised at evenly spaced quantiles."""
    import torch
    g, m = x.shape
    k = min(k, m)
    xs = x.sort(dim=1).values
    idx = ((torch.arange(k, device=x.device, dtype=torch.float32) + 0.5) / k * m).long().clamp_(0, m - 1)
    c = xs[:, idx].contiguous()
    ones = torch.ones_like(x)
    labels = None
    for _ in range(iters):
        mid = ((c[:, 1:] + c[:, :-1]) / 2).contiguous()
        labels = torch.searchsorted(mid, x)
        sums = torch.zeros_like(c).scatter_add_(1, labels, x)
        counts = torch.zeros_like(c).scatter_add_(1, labels, ones)
        new_c = torch.where(counts > 0, sums / counts.clamp(min=1), c)
        new_c = new_c.sort(dim=1).values
        shift = (new_c - c).abs().max().item()
        c = new_c
        if shift <= tol * (x.abs().max().item() + 1e-12):
            break
    mid = ((c[:, 1:] + c[:, :-1]) / 2).contiguous()
    labels = torch.searchsorted(mid, x)
    return c, labels


def palettize(w, n_bits: int, group_size: int = 0, iters: int = 30):
    """k-means palettisation (2**n_bits values), quantise-dequantise.
    group_size 0 = one palette per layer (coremltools granularity="per_tensor");
    group_size N = one palette per block of N output channels ("per_grouped_channel").
    The palette (lookup table) is stored in fp16, as in Core ML."""
    rows = w.shape[0]
    x = w.reshape(rows, -1)
    k = 2 ** n_bits
    if not group_size or group_size >= rows:
        return _palettize_groups(x.reshape(1, -1), k, iters).reshape(w.shape)
    full = rows // group_size * group_size          # e.g. a 300-row output layer with groups of 32:
    parts = [_palettize_groups(x[:full].reshape(full // group_size, -1), k, iters).reshape(full, -1)]
    if full < rows:                                 # ...9 groups of 32, then one group of the last 12 rows
        parts.append(_palettize_groups(x[full:].reshape(1, -1), k, iters).reshape(rows - full, -1))
    import torch
    return torch.cat(parts).reshape(w.shape)


def _palettize_groups(x, k, iters):
    """x: (groups, values) -> same shape, each group replaced by its own k fp16 palette values."""
    c, labels = kmeans_1d(x.contiguous(), k, iters=iters)
    return round_fp16(c).gather(1, labels)


# --------------------------------------------------------------------------
# Variants: which parameters are compressed, how, and what it would weigh
# --------------------------------------------------------------------------


def linear_weight_names(model, include_conv: bool = False):
    """Names of the weights the int8 / palette variants compress: every nn.Linear,
    plus (with include_conv) every 1-D convolution, as Core ML's palettiser would."""
    import torch
    kinds = (torch.nn.Linear, torch.nn.Conv1d) if include_conv else (torch.nn.Linear,)
    return {f"{name}.weight" for name, mod in model.named_modules() if isinstance(mod, kinds)}


def palette_groups(shape, group_size):
    return math.ceil(shape[0] / group_size) if group_size and group_size < shape[0] else 1


def transform_for(variant: str, name: str, linear_names, group_size: int, iters: int):
    """Return a function float32 tensor -> float32 tensor for this parameter."""
    if variant == "fp32":
        return lambda w: w
    if variant == "fp16" or name not in linear_names:
        return round_fp16                      # non-Linear weights ship in fp16
    if variant == "int8":
        return quant_int8_per_channel
    if variant in ("pal4", "pal6"):
        bits = int(variant[3:])
        return lambda w: palettize(w, bits, group_size, iters)
    raise ValueError(variant)


def estimated_bytes(variant: str, params: dict, linear_names, group_size: int) -> float:
    """Approximate weight-file size for a variant (weights + scales / lookup tables)."""
    total = 0.0
    for name, p in params.items():
        n = p.numel()
        if variant == "fp32":
            total += 4 * n
        elif variant == "fp16" or name not in linear_names:
            total += 2 * n
        elif variant == "int8":
            total += n + 2 * p.shape[0]                              # int8 + fp16 scale per row
        elif variant in ("pal4", "pal6"):
            bits = int(variant[3:])
            total += n * bits / 8 + 2 * (2 ** bits) * palette_groups(p.shape, group_size)
    return total


def measured_bytes(model) -> int:
    import torch
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return buf.tell()


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def load_test_clips(spec: str, max_clips, min_s: float, max_s: float):
    """Test split loaded with train_amharic_ctc.load_source, decoded once and cached
    as int16 (2 bytes per sample) so each variant sees exactly the same audio."""
    ds = load_source(spec, "test")
    if ds is None:
        print(f"  ! {spec}: no test split")
        return []
    clips = []
    skipped = 0
    for i, row in enumerate(ds):
        ref = normalize_amharic(row["text"] or "")
        if not ref:
            skipped += 1
            continue
        audio = decode_audio(row["audio"])
        secs = len(audio) / SR
        if not (min_s <= secs <= (max_s if max_s > 0 else math.inf)):
            skipped += 1
            continue
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        clips.append({"id": f"{spec}-{i}", "ref": row["text"], "ref_n": ref, "pcm": pcm, "secs": secs})
        if max_clips and len(clips) >= max_clips:
            break
        if len(clips) % 500 == 0:
            print(f"    {len(clips)} clips decoded…")
    hours = sum(c["secs"] for c in clips) / 3600
    print(f"  {DATASETS.get(spec, spec)}: {len(clips)} clips, {hours:.2f} h (skipped {skipped})")
    return clips


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def transcribe(model, processor, pcm, device):
    import torch
    audio = pcm.astype(np.float32) / 32767
    inputs = processor.feature_extractor(audio, sampling_rate=SR, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items() if hasattr(v, "to")}
    with torch.inference_mode():
        logits = model(**inputs).logits
    ids = logits.argmax(dim=-1)                       # greedy CTC
    return processor.tokenizer.batch_decode(ids)[0]


def evaluate(model, processor, clips, device, label, per_clip_rows, variant, dataset):
    tot = [0, 0, 0, 0]
    t0 = time.perf_counter()
    for n, clip in enumerate(clips, 1):
        hyp = transcribe(model, processor, clip["pcm"], device)
        counts = error_counts(clip["ref_n"], normalize_amharic(hyp))
        tot = [a + b for a, b in zip(tot, counts)]
        per_clip_rows.append({
            "variant": variant, "dataset": dataset, "clip": clip["id"],
            "duration_s": round(clip["secs"], 2),
            "wer": round(counts[0] / max(counts[1], 1), 4),
            "cer": round(counts[2] / max(counts[3], 1), 4),
            "reference": clip["ref"], "hypothesis": hyp,
        })
        if n % 200 == 0:
            el = time.perf_counter() - t0
            print(f"    {label}: {n}/{len(clips)}  WER so far {tot[0] / max(tot[1], 1):.1%}  ({el:.0f} s)")
    wer, cer = tot[0] / max(tot[1], 1), tot[2] / max(tot[3], 1)
    print(f"    {label}: WER {wer:.2%}  CER {cer:.2%}  ({time.perf_counter() - t0:.0f} s)")
    return wer, cer


def apply_variant(model, base, variant, linear_names, group_size, iters, device):
    """Write the variant's weights into the model, starting from a fresh copy of the
    original float32 weights each time (so variants never stack)."""
    import torch
    params = dict(model.named_parameters())
    t0 = time.perf_counter()
    with torch.no_grad():
        for name, p in params.items():
            fn = transform_for(variant, name, linear_names, group_size, iters)
            w = base[name].to(device=p.device, dtype=torch.float32)
            p.copy_(fn(w))
    if variant not in ("fp32", "fp16"):
        print(f"  weights converted in {time.perf_counter() - t0:.0f} s")


def run_variant(variant, model, base, params, linear_names, processor, data, device, args, per_clip_rows):
    """Build one variant in the (single) loaded model, score it on every test set."""
    import torch
    if variant == "int8-dynamic":
        # Exactly what the Windows app does for live preview. It modifies the model in
        # place (no second 2.4 GB copy), so it must be the last variant.
        apply_variant(model, base, "fp32", linear_names, 0, 0, device)
        model.to("cpu")
        device = "cpu"
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
        size = measured_bytes(model)
        print("  runs on the CPU (PyTorch dynamic quantisation has no GPU kernels) - this one is slow")
    else:
        apply_variant(model, base, variant, linear_names, args.palette_group_size, args.kmeans_iters, device)
        size = estimated_bytes(variant, params, linear_names, args.palette_group_size)
    row = {"variant": variant, "size_mb": round(size / 1e6, 1)}
    for spec, clips in data.items():
        wer, cer = evaluate(model, processor, clips, device, f"{variant} / {spec}", per_clip_rows, variant, spec)
        row[f"{spec}_wer"], row[f"{spec}_cer"] = wer, cer
    return row


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def fmt_pp(x):
    return "" if x is None else f"{x * 100:+.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF model id or local folder")
    ap.add_argument("--max-clips", type=int, default=0,
                    help="use only the first N test clips of each dataset (0 = full test sets)")
    ap.add_argument("--datasets", nargs="+", default=list(DATASETS), choices=list(DATASETS))
    ap.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS, choices=ALL_VARIANTS,
                    help="default: all but int8-dynamic (add it explicitly; it runs on the CPU and is very slow)")
    ap.add_argument("--palette-group-size", type=int, default=0,
                    help="output channels per k-means palette (0 = one palette per layer, the default)")
    ap.add_argument("--include-conv", action="store_true",
                    help="also compress Conv1d weights (Core ML would); default: nn.Linear only")
    ap.add_argument("--kmeans-iters", type=int, default=30)
    ap.add_argument("--min-seconds", type=float, default=0.5)
    ap.add_argument("--max-seconds", type=float, default=20.0, help="as in train_amharic_ctc.py; 0 = no limit")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    ap.add_argument("--out", type=Path, default=Path("compression_results"))
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCTC, AutoProcessor

    device = pick_device(args.device)
    variants = [v for v in ALL_VARIANTS if v in args.variants]     # fixed order, int8-dynamic last
    print(f"Device: {device}   Variants: {', '.join(variants)}")

    # ---- data (decoded once)
    print("Loading test sets…")
    data = {}
    for spec in args.datasets:
        try:
            clips = load_test_clips(spec, args.max_clips, args.min_seconds, args.max_seconds)
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not load {spec}: {e}")
            clips = []
        if clips:
            data[spec] = clips
    if not data:
        sys.exit("No test data loaded (log in with `huggingface-cli login` if a dataset is gated).")

    # ---- model (loaded once, float32)
    print(f"Loading {args.model}…")
    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForCTC.from_pretrained(args.model, torch_dtype=torch.float32).to(device).eval()
    params = dict(model.named_parameters())
    base = {k: v.detach().to("cpu", copy=True) for k, v in params.items()}   # pristine fp32 weights
    linear_names = linear_weight_names(model, args.include_conv) & set(params)
    n_all = sum(p.numel() for p in params.values())
    n_lin = sum(params[k].numel() for k in linear_names)
    print(f"  {n_all / 1e6:.0f} M parameters, {n_lin / n_all:.1%} of them in the compressed layers "
          f"({len(linear_names)} layers) - those are what int8/pal compress")
    if args.include_conv:
        print("  (--include-conv: Conv1d weights are compressed too)")

    per_clip_rows, rows, failed = [], [], []
    for variant in variants:
        print(f"\n=== {variant}")
        try:
            row = run_variant(variant, model, base, params, linear_names, processor, data, device, args, per_clip_rows)
        except Exception as e:  # noqa: BLE001  (e.g. a PyTorch build without dynamic quantisation)
            print(f"  ! {variant} failed: {e}")
            failed.append(variant)
            per_clip_rows = [r for r in per_clip_rows if r["variant"] != variant]
            continue
        rows.append(row)
        report(rows, failed, data, args, per_clip_rows, final=False)   # safe to stop the run from here on
        if variant == "int8-dynamic":
            break                                    # model was quantised in place: always last
    if not rows:
        sys.exit("Every variant failed.")

    report(rows, failed, data, args, per_clip_rows, final=True)


def report(rows, failed, data, args, per_clip_rows, final):
    """Write the summary + per-clip files (after every variant, so an interrupted run keeps
    what it finished); print the table at the end."""
    # ---- deltas vs baseline
    base_row = next((r for r in rows if r["variant"] == "fp32"), None)
    for r in rows:
        for spec in data:
            for m in ("wer", "cer"):
                key = f"{spec}_{m}"
                r[f"{key}_delta"] = (r[key] - base_row[key]) if base_row else None

    # ---- recommendation: smallest iPhone-style variant within MAX_WER_LOSS_PP on every test set
    ok = [r for r in rows if r["variant"] != "int8-dynamic" and base_row and
          all(r[f"{s}_wer_delta"] <= MAX_WER_LOSS_PP / 100 for s in data)]
    best = min(ok, key=lambda r: r["size_mb"]) if ok else None

    # ---- write + print
    args.out.mkdir(parents=True, exist_ok=True)
    cols = ["variant", "size_mb"]
    for spec in data:
        cols += [f"{spec}_wer", f"{spec}_wer_delta", f"{spec}_cer", f"{spec}_cer_delta"]
    with open(args.out / "compression_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in cols})
    with open(args.out / "compression_per_clip.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(per_clip_rows[0]) if per_clip_rows else ["variant"])
        w.writeheader()
        w.writerows(per_clip_rows)

    head = ["Variant", "Size (MB)"]
    for spec in data:
        n = spec.upper()
        head += [f"{n} WER %", f"{n} ΔWER pp", f"{n} CER %", f"{n} ΔCER pp"]
    table = []
    for r in rows:
        line = [r["variant"], f"{r['size_mb']:.0f}" if r["size_mb"] >= 100 else f"{r['size_mb']:.1f}"]
        for spec in data:
            line += [f"{r[f'{spec}_wer'] * 100:.2f}", fmt_pp(r[f"{spec}_wer_delta"]),
                     f"{r[f'{spec}_cer'] * 100:.2f}", fmt_pp(r[f"{spec}_cer_delta"])]
        table.append(line)

    clips_note = f"first {args.max_clips} clips per test set" if args.max_clips else "full test sets"
    if best:
        verdict = (f"Smallest variant within {MAX_WER_LOSS_PP} WER points of fp32 on every test set: "
                   f"**{best['variant']}** ({best['size_mb']:.0f} MB).")
    elif base_row:
        verdict = f"No compressed variant stayed within {MAX_WER_LOSS_PP} WER points of fp32."
    else:
        verdict = "fp32 was not run, so no deltas or recommendation."
    md = [f"# Compression results: {args.model}", "",
          f"Greedy CTC decoding, {clips_note}. Δ = change vs fp32 in percentage points "
          f"(positive = worse). Sizes are approximate weight sizes; int8-dynamic is measured.", "",
          "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    md += ["| " + " | ".join(line) + " |" for line in table]
    md += ["", verdict, ""]
    if failed:
        md += [f"Failed (see the log): {', '.join(failed)}", ""]
    (args.out / "compression_summary.md").write_text("\n".join(md), encoding="utf-8")

    if not final:
        print(f"  (results so far saved to {args.out / 'compression_summary.md'})")
        return
    widths = [max(len(str(x)) for x in col) for col in zip(head, *table)]
    print("\n" + "=" * (sum(widths) + 2 * len(widths)))
    print(f"{args.model}  ({clips_note})")
    for line in [head] + table:
        print("  ".join(str(x).rjust(wd) if i else str(x).ljust(wd) for i, (x, wd) in enumerate(zip(line, widths))))
    print("=" * (sum(widths) + 2 * len(widths)))
    print(verdict.replace("**", ""))
    if failed:
        print("Failed:", ", ".join(failed))
    print(f"Wrote {args.out / 'compression_summary.csv'}, {args.out / 'compression_summary.md'}, "
          f"{args.out / 'compression_per_clip.csv'}")


if __name__ == "__main__":
    main()
