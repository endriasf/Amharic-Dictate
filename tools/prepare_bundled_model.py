"""
Prepare the speech model that ships inside the installer (used by build/build.ps1).

Downloads a model from Hugging Face (or copies a local folder), stores its weights in 8-bit
(int8 per output channel for every Linear and Conv1d layer, about 600 MB instead of 2.4 GB; see
int8model.py), and stamps the author and licence into the weights file and config.json.

The 8-bit version was measured on the full WAXAL and FLEURS Amharic test sets with
tools/compression_eval.py: +0.04 WER points on both, i.e. the same accuracy. The app expands the
weights back to full precision when it loads them.

Before finishing, this checks that the app's loader gives exactly the weights that were measured,
and that the model runs.

  python tools/prepare_bundled_model.py --source Abittee/amharic-speech-to-text-efa-v1 --out build/model
  python tools/prepare_bundled_model.py ... --format fp16     # the previous half-precision format
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

AUTHOR = "Endrias F. Abitte"
KEEP = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json",
        "special_tokens_map.json", "added_tokens.json", "README.md", "LICENSE")


def measured_int8(w):
    """Exactly the quantise-dequantise of tools/compression_eval.py (quant_int8_per_channel), copied here so
    the build doesn't need that tool's dependencies. Used only to check the bundled weights."""
    import torch
    qmax = 127
    w2 = w.reshape(w.shape[0], -1)
    scale = w2.abs().amax(dim=1, keepdim=True) / qmax
    scale = scale.to(torch.float16).to(torch.float32)
    scale = torch.where(scale > 0, scale, torch.ones_like(scale))
    q = torch.clamp(torch.round(w2 / scale), -qmax, qmax)
    return (q * scale).reshape(w.shape)


def write_int8(tensors, src, out, meta):
    import torch
    from safetensors.torch import save_file
    from transformers import AutoConfig, AutoModelForCTC
    import int8model

    config = AutoConfig.from_pretrained(src)
    try:                                       # only to find which weights are Linear / Conv1d
        with torch.device("meta"):
            skeleton = AutoModelForCTC.from_config(config)
    except Exception:
        skeleton = AutoModelForCTC.from_config(config)
    names = int8model.quantized_weight_names(skeleton)
    del skeleton
    missing = names - set(tensors)
    if missing:
        raise SystemExit(f"Weights not found in the model file: {sorted(missing)[:5]}")
    packed = {}
    for k, v in tensors.items():
        if k in names:
            q, s = int8model.quantize(v)
            packed[k], packed[k + int8model.SCALE_SUFFIX] = q, s
        else:
            packed[k] = (v.float() if v.is_floating_point() else v).contiguous()
    save_file(packed, os.path.join(out, int8model.INT8_FILE), metadata=meta)
    print(f"8-bit weights: {len(names)} Linear/Conv1d weights in int8, {len(tensors) - len(names)} others in float32")
    return names


def check_int8(tensors, names, out):
    """The app's loader must return exactly the measured weights, and the model must run."""
    import numpy as np
    import torch
    import int8model

    model = int8model.load_ctc_model(out).eval()
    got = model.state_dict()
    bad = []
    for k, v in tensors.items():
        want = measured_int8(v.float()) if k in names else (v.float() if v.is_floating_point() else v)
        if k not in got or got[k].shape != want.shape or not torch.equal(got[k].to(want.dtype), want):
            bad.append(k)
    if bad:
        raise SystemExit(f"8-bit check FAILED: {len(bad)} weights differ from the measured variant, e.g. {bad[:3]}")
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(out)
    t = np.arange(3 * 16000) / 16000
    audio = (0.1 * np.sin(2 * np.pi * 220 * t) + 0.01 * np.random.default_rng(0).standard_normal(t.size))
    inputs = processor(audio.astype(np.float32), sampling_rate=16000, return_tensors="pt")
    with torch.inference_mode():
        logits = model(**inputs).logits
    if not torch.isfinite(logits).all():
        raise SystemExit("8-bit check FAILED: the model gives invalid output")
    print(f"8-bit check passed: all {len(tensors)} weights match the measured variant exactly; the model runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Hugging Face model id or local folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Amharic Speech-to-Text EFA v1")
    ap.add_argument("--license", default="cc-by-sa-4.0")
    ap.add_argument("--format", choices=["int8", "fp16"], default="int8")
    args = ap.parse_args()

    if os.path.isdir(args.source):
        src = args.source
    else:
        from huggingface_hub import snapshot_download
        src = snapshot_download(args.source, allow_patterns=["*.json", "*.safetensors", "*.md", "LICENSE"])

    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)
    for f in KEEP:
        if os.path.isfile(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), os.path.join(args.out, f))

    cfg_path = os.path.join(args.out, "config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    cfg.update({"model_name": args.name, "author": AUTHOR, "license": args.license})
    cfg["torch_dtype"] = "float32"          # the app runs it at full precision
    if args.format == "int8":
        cfg["weights_format"] = "int8 per-channel (Linear + Conv1d), expanded to float32 when loaded"
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    from safetensors.torch import load_file, save_file
    tensors = load_file(os.path.join(src, "model.safetensors"))
    meta = {"format": "pt", "name": args.name, "author": AUTHOR, "license": args.license,
            "source": args.source, "weights": args.format}
    if args.format == "int8":
        names = write_int8(tensors, args.out, args.out, meta)
        check_int8(tensors, names, args.out)
    else:
        half = {k: (v.half() if v.is_floating_point() else v).contiguous() for k, v in tensors.items()}
        save_file(half, os.path.join(args.out, "model.safetensors"), metadata=meta)

    size = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out)) / 1e9
    print(f"Bundled model ready in {args.out} ({size:.2f} GB, {args.format}), credited to {AUTHOR}")


if __name__ == "__main__":
    main()
