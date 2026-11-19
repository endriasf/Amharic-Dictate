#!/usr/bin/env python3
"""
How small can the Amharic speech model get before dictation gets worse?

Takes one CTC speech model (default: Abittee/amharic-speech-to-text-efa-v1, w2v-BERT 2.0,
~0.6 B parameters, 2.4 GB in float32) and simulates shipping its weights in smaller formats.
For every format it reports the approximate size of the weights, WER and CER on the
WAXAL Amharic test set and the FLEURS Amharic test set, and the change versus float32.
Groundwork for an iPhone app (Core ML can store weights in all of these formats).

Variants (all decoded greedily, argmax CTC, no dictionary / language model)
  fp32          the original weights                                     (baseline)
  fp16          every weight rounded to float16 (run in float32)
  int8          every nn.Linear weight: int8, one scale per output channel (symmetric);
                everything else float16
  int8-dynamic  torch quantize_dynamic(nn.Linear, qint8), exactly what the Windows app
                uses for its live preview; runs on the CPU (slow on big test sets)
  pal6          every nn.Linear weight: 6-bit palette (64 k-means centroids per layer);
                everything else float16
  pal4          the same with a 4-bit palette (16 centroids), like coremltools'
                palettize_weights(nbits=4)
The int8 / palette variants are simulated: weights are compressed and immediately turned
back into float32 ("fake quantisation"), so the accuracy is what the compressed file
would give, while the model still runs with normal PyTorch.

---------------------------------------------------------------------------
GOOGLE COLAB  (Runtime > Change runtime type > T4 GPU), one cell per line:
  !git clone https://github.com/endriasf/amharic-dictate
  %cd amharic-dictate
  !pip install -q "transformers>=4.46" "datasets[audio]" soundfile librosa accelerate
  from huggingface_hub import notebook_login; notebook_login()   # free HF token, read access
  !python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500

WINDOWS PC  (in the repo folder, with the app's Python environment)
  pip install "transformers>=4.46" "datasets[audio]" soundfile librosa accelerate
  python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500

OPTIONS
  --max-clips 500          quick run: 500 random clips per test set (default: whole test sets)
  --variants fp32 pal4     only some variants (fp32 is always added as the baseline)
  --datasets waxal         only one test set; local:<folder> uses your own clip.wav + clip.txt pairs
  --batch-size 8           faster on a GPU, for a first look (padding shifts the numbers a little)
  --also-conv              also compress the Conformer's 1x1 convolutions (~75 M weights)
  --palette-group-size 16  one palette per block of 16 output channels instead of per layer
  --self-test              check the compression maths on a tiny random network (no downloads)

OUTPUT (in --out-dir, default compression_results/)
  compression_results.csv / .md   one row per variant (also printed)
  per_clip.csv                    every clip: reference and each variant's transcript
---------------------------------------------------------------------------
How to read it: pick the smallest variant whose WER stays within about 0.5 points of
fp32 on both test sets. The script prints that recommendation at the end.
"""

import argparse
import csv
import gc
import math
import os
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reuse the repo's own Amharic text handling and scoring (no second copy of these rules):
from amharic_asr_benchmark import error_counts, normalize_amharic          # noqa: E402

SR = 16000
DATASETS = {
    "waxal": "WAXAL amh_asr test",
    "fleurs": "FLEURS am_et test",
}
VARIANTS = {
    "fp32": "float32 (original)",
    "fp16": "float16 weights",
    "int8": "int8 per-channel Linear, rest fp16",
    "int8-dynamic": "torch quantize_dynamic int8 (app preview)",
    "pal6": "6-bit palette (64 centroids) Linear, rest fp16",
    "pal4": "4-bit palette (16 centroids) Linear, rest fp16",
}


# ==========================================================================
# Weight compression helpers (pure torch; tested by --self-test)
# ==========================================================================
def _bytes_per_elem(t):
    return t.element_size()


def fp16_round(w):
    """Round a float tensor to float16 and back. Returns (tensor, stored bytes)."""
    if not w.is_floating_point():
        return w, w.numel() * _bytes_per_elem(w)
    return w.half().float(), w.numel() * 2


def int8_per_channel(w):
    """Symmetric int8, one fp16 scale per output channel (row). Returns (dequantised, bytes)."""
    rows = w.reshape(w.shape[0], -1).float()
    scale = rows.abs().amax(dim=1, keepdim=True).clamp(min=1e-12) / 127.0
    scale = scale.half().float()                    # scales are stored as float16
    scale = scale.clamp(min=float(torch.finfo(torch.float16).tiny))
    q = torch.round(rows / scale).clamp(-127, 127)
    return (q * scale).reshape(w.shape).to(w.dtype), w.numel() + w.shape[0] * 2


def kmeans_1d(x, k, iters=300):
    """Batched 1-D k-means (Lloyd). x: (B, N) float. Returns (centroids (B, k), labels (B, N)).

    In one dimension every cluster is a contiguous run of the sorted values, so after one sort
    each Lloyd step only needs k boundary look-ups and prefix sums: O(k log N) per step, which
    allows many steps (1-D Lloyd converges slowly). Centroids start at evenly spaced quantiles."""
    B, N = x.shape
    k = min(k, N)
    xs = x.float().sort(dim=1).values.contiguous()
    csum = torch.zeros(B, N + 1, dtype=torch.float64, device=x.device)
    csum[:, 1:] = xs.double().cumsum(dim=1)
    pos = ((torch.arange(k, device=x.device, dtype=torch.float64) + 0.5) / k * (N - 1)).round().long()
    c = xs[:, pos].double()
    zero = torch.zeros(B, 1, dtype=torch.long, device=x.device)
    full = torch.full((B, 1), N, dtype=torch.long, device=x.device)
    for _ in range(iters):
        bounds = ((c[:, 1:] + c[:, :-1]) / 2).float().contiguous()
        cut = torch.searchsorted(xs, bounds, right=True)        # values <= boundary go left
        edges = torch.cat([zero, cut, full], dim=1)
        cnt = (edges[:, 1:] - edges[:, :-1]).double()
        sums = csum.gather(1, edges[:, 1:]) - csum.gather(1, edges[:, :-1])
        new = torch.where(cnt > 0, sums / cnt.clamp(min=1), c)
        new = new.sort(dim=1).values
        if torch.equal(new, c):
            break
        c = new
    c = c.float()
    bounds = ((c[:, 1:] + c[:, :-1]) / 2).contiguous()
    lab = torch.searchsorted(bounds, x.float().contiguous(), right=False)   # x == boundary -> left
    return c, lab


def palettize(w, nbits, group_size=0, iters=300):
    """Weight-only palettisation (lookup table of 2**nbits fp16 values) like coremltools.

    group_size 0: one palette per layer. group_size G: one palette per block of G output
    channels. Returns (dequantised tensor, stored bytes: indices + palettes)."""
    k = 2 ** nbits
    out = w.shape[0]
    rows = w.reshape(out, -1).float()
    G = out if group_size <= 0 or group_size >= out else group_size
    deq = torch.empty_like(rows)
    n_palettes = 0
    full = (out // G) * G
    parts = [(0, full, out // G)]
    if full < out:
        parts.append((full, out, 1))
    for start, stop, nblocks in parts:
        block = rows[start:stop].reshape(nblocks, -1)
        c, lab = kmeans_1d(block, k, iters)
        c = c.half().float()                        # the palette is stored as float16
        deq[start:stop] = c.gather(1, lab).reshape(stop - start, -1)
        n_palettes += nblocks
        del block, c, lab
    size = math.ceil(w.numel() * nbits / 8) + n_palettes * k * 2
    return deq.reshape(w.shape).to(w.dtype), size


def compressible_names(model, also_conv=False):
    """state-dict names of the weights the int8 / palette variants compress."""
    kinds = (torch.nn.Linear, torch.nn.Conv1d) if also_conv else (torch.nn.Linear,)
    names = set()
    for mod_name, mod in model.named_modules():
        if isinstance(mod, kinds) and getattr(mod, "weight", None) is not None:
            names.add(f"{mod_name}.weight" if mod_name else "weight")
    return names


def make_transform(variant, targets, group_size=0, iters=300):
    """Return f(name, tensor) -> (tensor for running, stored bytes) for one variant."""
    def f(name, w):
        if variant == "fp32" or not w.is_floating_point():
            return w, w.numel() * _bytes_per_elem(w)
        if variant == "fp16" or name not in targets:
            return fp16_round(w)
        if variant == "int8":
            return int8_per_channel(w)
        if variant in ("pal6", "pal4"):
            return palettize(w, 6 if variant == "pal6" else 4, group_size, iters)
        raise ValueError(variant)
    return f


def apply_variant(model, base_sd, transform):
    """Write transform(base weight) into the model's own tensors, in place.

    base_sd is the pristine float32 state dict (kept on the CPU and never modified), so
    every variant starts from the original weights and no second model is built.
    Returns the approximate stored size of the weights in bytes."""
    live = model.state_dict(keep_vars=True)
    total = 0
    with torch.no_grad():
        for name, w in base_sd.items():
            dst = live[name]
            new, nbytes = transform(name, w.to(dst.device))
            dst.data.copy_(new)
            total += nbytes
            del new
    return total


def state_dict_bytes(model):
    """Exact size of a model's state dict as torch.save would write it."""
    import io
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return buf.tell()


# ==========================================================================
# Data (same loading and label clean-up as train_amharic_ctc.py's test evaluation)
# ==========================================================================
def load_clips(spec, processor, max_clips, min_s, max_s):
    """Return a list of clips {features, mask, ref, seconds} with model inputs precomputed once."""
    from train_amharic_ctc import decode_audio, load_all, normalize_label

    if spec.startswith("local:"):
        from amharic_asr_benchmark import load_dataset as load_folder
        pairs = load_folder(Path(spec[len("local:"):]))
        rows = [({"path": str(a), "bytes": None}, normalize_label(t, False)) for a, t in pairs]
        rows = [r for r in rows if r[1]][: max_clips or None]
    else:
        ds = load_all([spec], "test", homophones=False, max_samples=max_clips)   # shuffled (seed 42)
        if ds is None:
            raise RuntimeError(f"{spec}: no test split")
        rows = ((ex["audio"], ex["text"]) for ex in ds)            # one clip at a time (memory)

    clips, skipped = [], 0
    for i, (audio_entry, text) in enumerate(rows, 1):
        audio = decode_audio(audio_entry)
        seconds = len(audio) / SR
        ref = normalize_amharic(text)
        if not ref or not (min_s <= seconds <= (max_s or float("inf"))):
            skipped += 1
            continue
        inputs = processor(audio, sampling_rate=SR, return_tensors="pt")
        key = "input_features" if "input_features" in inputs else "input_values"
        clips.append({"key": key, "x": inputs[key][0].float(), "has_mask": "attention_mask" in inputs,
                      "ref": ref, "seconds": seconds})
        if i % 500 == 0:
            print(f"    prepared {i} clips…", flush=True)
    print(f"  {DATASETS.get(spec, spec)}: {len(clips)} clips, {sum(c['seconds'] for c in clips) / 3600:.2f} h"
          + (f" ({skipped} skipped: empty text or outside {min_s}-{max_s} s)" if skipped else ""))
    return clips


# ==========================================================================
# Inference + scoring
# ==========================================================================
def transcribe_all(model, processor, clips, device, batch_size=1):
    """Greedy CTC (argmax) transcript for every clip, in the original clip order."""
    hyps = [""] * len(clips)
    order = sorted(range(len(clips)), key=lambda i: clips[i]["x"].shape[0])
    tok = processor.tokenizer
    with torch.inference_mode():
        for b in range(0, len(order), batch_size):
            idx = order[b:b + batch_size]
            key = clips[idx[0]]["key"]
            lens = [clips[i]["x"].shape[0] for i in idx]
            T = max(lens)
            x = torch.zeros((len(idx), T) + tuple(clips[idx[0]]["x"].shape[1:]))
            mask = torch.zeros((len(idx), T), dtype=torch.long)
            for j, i in enumerate(idx):
                x[j, :lens[j]] = clips[i]["x"]
                mask[j, :lens[j]] = 1
            kw = {key: x.to(device)}
            if clips[idx[0]]["has_mask"] or len(idx) > 1:
                kw["attention_mask"] = mask.to(device)
            logits = model(**kw).logits
            ids = logits.argmax(dim=-1).cpu()
            frames = ids.shape[1]
            for j, i in enumerate(idx):
                n = frames if lens[j] == T else max(1, math.ceil(frames * lens[j] / T))   # drop padding frames
                hyps[i] = tok.decode(ids[j, :n].tolist())
            if (b // batch_size) % 200 == 199:
                print(f"    {b + len(idx)}/{len(order)} clips", flush=True)
    return hyps


def score(clips, hyps):
    we = rw = ce = rc = 0
    for c, h in zip(clips, hyps):
        a, b, d, e = error_counts(c["ref"], normalize_amharic(h))
        we += a; rw += b; ce += d; rc += e
    return 100.0 * we / max(rw, 1), 100.0 * ce / max(rc, 1)


# ==========================================================================
# Self-test (no model, no data, no network)
# ==========================================================================
def self_test():
    torch.manual_seed(0)
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and bool(cond)

    # fp16
    w = torch.randn(40, 24)
    r, n = fp16_round(w)
    check(torch.equal(r, w.half().float()) and n == w.numel() * 2, "fp16: rounding and size")
    i = torch.arange(5)
    check(fp16_round(i)[0] is i, "fp16: integer tensors untouched")

    # int8 per channel
    w = torch.randn(40, 24) * torch.linspace(0.01, 3, 40)[:, None]       # very different row ranges
    r, n = int8_per_channel(w)
    scale = (w.abs().amax(1, keepdim=True) / 127).half().float()
    check(((r - w).abs() <= scale / 2 + 1e-6).all(), "int8: error at most half a step in every row")
    check(all(len(row.unique()) <= 255 for row in r), "int8: at most 255 levels per row")
    check(n == 40 * 24 + 40 * 2, "int8: size = 1 byte/weight + fp16 scale per row")
    check(torch.allclose((r / scale).round(), r / scale, atol=1e-3), "int8: values are integer multiples of the scale")

    # k-means on obviously clustered data
    true = torch.tensor([-2.0, -0.5, 0.7, 3.0])
    x = (true[torch.randint(0, 4, (1, 4000))] + 0.01 * torch.randn(1, 4000))
    c, lab = kmeans_1d(x, 4)
    check(torch.allclose(c[0], true, atol=0.02), f"kmeans: recovers known centres {c[0].tolist()}")
    check(lab.shape == x.shape and lab.max() < 4, "kmeans: labels shape/range")

    # palettisation
    w = torch.randn(64, 48)
    r4, n4 = palettize(w, 4)
    r6, n6 = palettize(w, 6)
    check(len(r4.unique()) <= 16 and len(r6.unique()) <= 64, "palette: at most 16 / 64 distinct values")
    e4, e6 = (r4 - w).pow(2).mean().item(), (r6 - w).pow(2).mean().item()
    eu = (torch.round(w / 0.5).clamp(-8, 7) * 0.5 - w).pow(2).mean().item()     # naive uniform 4-bit
    check(e6 < e4 < eu, f"palette: 6-bit error {e6:.5f} < 4-bit {e4:.5f} < naive uniform {eu:.5f}")
    check(n4 == 64 * 48 // 2 + 16 * 2 and n6 == math.ceil(64 * 48 * 6 / 8) + 64 * 2, "palette: size maths")
    rg, ng = palettize(w, 4, group_size=16)
    check(all(len(rg[s:s + 16].unique()) <= 16 for s in range(0, 64, 16)) and ng == 64 * 48 // 2 + 4 * 16 * 2,
          "palette: one palette per 16-channel block")
    wv = torch.randn(256, 256) * torch.linspace(0.2, 2, 256)[:, None]           # rows with different ranges
    ev = (palettize(wv, 4)[0] - wv).pow(2).mean().item()
    evg = (palettize(wv, 4, group_size=64)[0] - wv).pow(2).mean().item()
    check(evg < ev, f"palette: per-block palettes help when rows differ ({evg:.4f} < {ev:.4f})")
    g = torch.randn(1, 200000)
    eg = (palettize(g, 4)[0] - g).pow(2).mean().item()
    check(abs(eg - 0.009497) < 0.0005, f"palette: 4-bit Gaussian error {eg:.5f} ~ Lloyd-Max optimum 0.00950")
    rr, _ = palettize(torch.randn(70, 8), 4, group_size=16)                  # 70 = 4 blocks + remainder 6
    check(rr.shape == (70, 8) and len(rr[64:].unique()) <= 16, "palette: remainder block handled")
    cw = torch.randn(32, 16, 1)
    rc, _ = palettize(cw, 4)
    check(rc.shape == cw.shape and len(rc.unique()) <= 16, "palette: conv-shaped weights")

    # whole-model path: variants start from pristine weights, base never changes
    net = torch.nn.Sequential(torch.nn.Linear(16, 256), torch.nn.ReLU(), torch.nn.Conv1d(1, 4, 1),
                              torch.nn.LayerNorm(256), torch.nn.Linear(256, 64))
    net.eval()
    base = {k: v.detach().clone() for k, v in net.state_dict().items()}
    snap = {k: v.clone() for k, v in base.items()}
    inp = torch.randn(3, 1, 16)
    ref_out = net(inp)
    targets = compressible_names(net)
    check(targets == {"0.weight", "4.weight"}, f"targets: only Linear weights ({sorted(targets)})")
    check(compressible_names(net, also_conv=True) == {"0.weight", "2.weight", "4.weight"}, "targets: --also-conv adds Conv1d")
    sizes = {}
    for v in ("fp32", "fp16", "int8", "pal6", "pal4"):
        sizes[v] = apply_variant(net, base, make_transform(v, targets))
        out = net(inp)
        err = (out - ref_out).abs().max().item()
        check(err < (1e-6 if v == "fp32" else 0.5), f"model {v}: {sizes[v]} bytes, max output change {err:.4f}")
        if v == "pal4":
            check(len(net[4].weight.unique()) <= 16 and net[3].weight.dtype == torch.float32,
                  "model pal4: Linear palettised, model still runs in float32")
            check(torch.equal(net[3].bias, base["3.bias"].half().float()), "model pal4: non-Linear weights fp16-rounded")
    check(all(torch.equal(base[k], snap[k]) for k in base), "base state dict never modified")
    check(sizes["fp32"] > sizes["fp16"] > sizes["int8"] > sizes["pal6"] > sizes["pal4"], "sizes shrink in order")
    apply_variant(net, base, make_transform("fp32", targets))
    check(torch.equal(net(inp), ref_out), "fp32 restores the exact original output")

    # dynamic int8 (what the app does), if this torch build has a quantised engine
    try:
        qd = getattr(torch, "ao", torch).quantization.quantize_dynamic
        lin = torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.ReLU(), torch.nn.Linear(32, 5)).eval()
        x = torch.randn(4, 16)
        y = lin(x)
        fp = state_dict_bytes(lin)
        q = qd(lin, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
        check((q(x) - y).abs().max().item() < 0.1 and state_dict_bytes(q) > 0, f"quantize_dynamic runs (fp32 {fp} B -> {state_dict_bytes(q)} B)")
    except Exception as e:                                      # some CPU builds lack the engine
        print(f"  skip quantize_dynamic: {e}")

    print("\nSelf-test", "PASSED" if ok else "FAILED")
    return ok


# ==========================================================================
# Main
# ==========================================================================
def write_results(out_dir, rows, specs, tol, recommendation):
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ["variant", "description", "size_mb", "size_vs_fp32", "device"]
    for s in specs:
        fields += [f"{s}_wer", f"{s}_cer", f"{s}_wer_change", f"{s}_cer_change"]
    fields += ["seconds"]
    with open(out_dir / "compression_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    head = ["Variant", "Size (MB)", "vs fp32"]
    for s in specs:
        name = DATASETS.get(s, s)
        head += [f"{name} WER %", "Δ WER", f"{name} CER %", "Δ CER"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [f"{r['variant']} — {r['description']}", f"{r['size_mb']:.1f}", f"{r['size_vs_fp32']:.0%}"]
        for s in specs:
            if f"{s}_wer" in r:
                cells += [f"{r[f'{s}_wer']:.2f}", f"{r[f'{s}_wer_change']:+.2f}",
                          f"{r[f'{s}_cer']:.2f}", f"{r[f'{s}_cer_change']:+.2f}"]
            else:
                cells += ["–"] * 4
        lines.append("| " + " | ".join(cells) + " |")
    md = ("# Compression results\n\n" + "\n".join(lines) + "\n\n"
          f"Δ = change in percentage points versus fp32 (positive = more errors). "
          f"Greedy CTC decoding, homophones and punctuation not counted as errors.\n\n"
          f"**Recommendation** (smallest variant within {tol} WER points of fp32 on every test set): "
          f"{recommendation}\n")
    (out_dir / "compression_results.md").write_text(md, encoding="utf-8")
    return md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="Abittee/amharic-speech-to-text-efa-v1", help="HF model id or local folder")
    ap.add_argument("--datasets", nargs="+", default=["waxal", "fleurs"], help="waxal, fleurs, local:<folder>")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--max-clips", type=int, default=None, help="random clips per test set (default: all)")
    ap.add_argument("--min-seconds", type=float, default=0.5, help="as in train_amharic_ctc.py's test evaluation")
    ap.add_argument("--max-seconds", type=float, default=20.0, help="as in train_amharic_ctc.py; 0 = no limit")
    ap.add_argument("--batch-size", type=int, default=1,
                    help="1 = exact (default). Larger is faster on a GPU, but padding changes the numbers a little")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu", "mps"])
    ap.add_argument("--also-conv", action="store_true", help="also compress Conv1d weights")
    ap.add_argument("--palette-group-size", type=int, default=0, help="0 = one palette per layer")
    ap.add_argument("--kmeans-iters", type=int, default=300)
    ap.add_argument("--tolerance", type=float, default=0.5, help="allowed WER increase in points")
    ap.add_argument("--out-dir", type=Path, default=Path("compression_results"))
    ap.add_argument("--self-test", action="store_true", help="test the compression helpers and exit")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):                    # Windows consoles: never crash on Amharic / Δ
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    if args.self_test:
        sys.exit(0 if self_test() else 1)

    from transformers import AutoModelForCTC, AutoProcessor

    variants = ["fp32"] + [v for v in args.variants if v != "fp32"]
    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    torch.backends.cuda.matmul.allow_tf32 = False            # keep "fp32" really fp32 on A100-class GPUs
    torch.backends.cudnn.allow_tf32 = False
    print(f"Device: {device}   variants: {', '.join(variants)}")
    extra = (" + Conv1d" if args.also_conv else "") + (
        f", 1 palette / {args.palette_group_size} rows" if args.palette_group_size > 0 else "")
    if extra:
        for v in ("int8", "pal6", "pal4"):
            VARIANTS[v] = VARIANTS[v].replace(" Linear,", f" Linear{extra if v != 'int8' else extra.split(',')[0]},")

    print(f"Loading {args.model}…")
    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForCTC.from_pretrained(args.model).float().eval()
    base_sd = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.to(device)
    targets = compressible_names(model, args.also_conv)
    n_target = sum(base_sd[n].numel() for n in targets)
    n_all = sum(v.numel() for v in base_sd.values())
    print(f"  {n_all / 1e6:.0f} M weights, {n_target / 1e6:.0f} M of them in the "
          f"{'Linear + Conv1d' if args.also_conv else 'Linear'} layers that int8/palette compress")

    print("Preparing test sets (decoded and featurised once, reused by every variant)…")
    data = {}
    for spec in args.datasets:
        try:
            data[spec] = load_clips(spec, processor, args.max_clips, args.min_seconds, args.max_seconds)
        except Exception as e:
            print(f"  ! {spec} could not be loaded, skipped: {type(e).__name__}: {e}")
    data = {k: v for k, v in data.items() if v}
    if not data:
        sys.exit("No test data could be loaded (logged in to Hugging Face? accepted the dataset terms?)")
    specs = list(data)
    if "int8-dynamic" in variants:
        hours = sum(c["seconds"] for v in data.values() for c in v) / 3600
        print(f"Note: int8-dynamic runs on the CPU ({hours:.1f} h of audio). Leave it out with --variants "
              "if it is too slow.")

    rows, hyps_all = [], {}
    for v in variants:
        print(f"\n=== {v}: {VARIANTS[v]}")
        t0 = time.time()
        run_model, run_device = model, device
        if v == "int8-dynamic":
            model.cpu()                                        # make room; GPU copy restored afterwards
            if device == "cuda":
                torch.cuda.empty_cache()
            apply_variant(model, base_sd, make_transform("fp32", targets))
            try:
                # same call as engine.py, on a CPU copy so the float32 model stays available
                import copy
                qd = getattr(torch, "ao", torch).quantization.quantize_dynamic
                run_model = qd(copy.deepcopy(model), {torch.nn.Linear}, dtype=torch.qint8, inplace=True).eval()
            except Exception as e:                             # e.g. a future torch without eager quantisation
                print(f"  ! skipped, quantize_dynamic failed: {type(e).__name__}: {e}")
                model.to(device)
                continue
            run_device = "cpu"
            torch.set_num_threads(max(1, os.cpu_count() or 2))
            size = state_dict_bytes(run_model)
        else:
            size = apply_variant(model, base_sd, make_transform(v, targets, args.palette_group_size,
                                                                 args.kmeans_iters))
        row = {"variant": v, "description": VARIANTS[v], "size_mb": size / 1e6, "device": run_device}
        for spec in specs:
            hyps = transcribe_all(run_model, processor, data[spec], run_device, args.batch_size)
            hyps_all[(v, spec)] = hyps
            wer, cer = score(data[spec], hyps)
            row[f"{spec}_wer"], row[f"{spec}_cer"] = wer, cer
            print(f"  {DATASETS.get(spec, spec)}: WER {wer:.2f}%  CER {cer:.2f}%")
        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)
        if run_model is not model:
            del run_model
            gc.collect()
            model.to(device)

    base = rows[0]
    for r in rows:
        r["size_vs_fp32"] = r["size_mb"] / base["size_mb"]
        for spec in specs:
            r[f"{spec}_wer_change"] = r[f"{spec}_wer"] - base[f"{spec}_wer"]
            r[f"{spec}_cer_change"] = r[f"{spec}_cer"] - base[f"{spec}_cer"]
    good = [r for r in rows if all(r[f"{s}_wer_change"] <= args.tolerance for s in specs)]
    best = min(good, key=lambda r: r["size_mb"])
    recommendation = f"**{best['variant']}** ({best['description']}, about {best['size_mb']:.0f} MB)"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "per_clip.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "clip", "seconds", "reference"] + variants)
        for spec in specs:
            for i, c in enumerate(data[spec]):
                w.writerow([spec, i, f"{c['seconds']:.2f}", c["ref"]] + [hyps_all[(v, spec)][i] for v in variants])

    md = write_results(args.out_dir, rows, specs, args.tolerance, recommendation)
    print("\n" + md)
    print(f"Saved to {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
