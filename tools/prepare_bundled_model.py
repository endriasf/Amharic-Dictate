"""
Prepare the speech model that ships inside the installer (used by build/build.ps1).

Downloads a model from Hugging Face (or copies a local folder), stores its weights at half precision
(about half the size, no meaningful accuracy change — the app converts back to full precision when
loading), and stamps the author and licence into the weights file and config.json.

  python tools/prepare_bundled_model.py --source <hf-user>/amharic-speech-to-text-efa-v1 --out build/model
"""
import argparse
import json
import os
import shutil

AUTHOR = "Endrias F. Abitte"
KEEP = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json",
        "special_tokens_map.json", "added_tokens.json", "README.md", "LICENSE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Hugging Face model id or local folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Amharic Speech-to-Text EFA v1")
    ap.add_argument("--license", default="cc-by-sa-4.0")
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

    import torch
    from safetensors.torch import load_file, save_file
    weights = os.path.join(src, "model.safetensors")
    tensors = load_file(weights)
    half = {k: (v.half() if v.is_floating_point() else v).contiguous() for k, v in tensors.items()}
    meta = {"format": "pt", "name": args.name, "author": AUTHOR, "license": args.license,
            "source": args.source}
    save_file(half, os.path.join(args.out, "model.safetensors"), metadata=meta)

    cfg_path = os.path.join(args.out, "config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    cfg.update({"model_name": args.name, "author": AUTHOR, "license": args.license})
    cfg["torch_dtype"] = "float32"          # the app runs it at full precision
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    size = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out)) / 1e9
    print(f"Bundled model ready in {args.out} ({size:.2f} GB), credited to {AUTHOR}")


if __name__ == "__main__":
    main()
