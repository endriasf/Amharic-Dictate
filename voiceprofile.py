"""
Voice profiles (Dragon-style).

Each person has a folder:  %APPDATA%\\AmharicDictate\\profiles\\<name>\\
    profile.json      name, created, use_adapter, training result
    voice_data\\       clip_NNNNN.wav + clip_NNNNN.txt  (their setup reading)
    adapter.pt        small low-rank (LoRA) add-on, a few MB, tied to one base model

The base model is shared and never changed. A profile's add-on is merged into the weights
when the model loads, so dictation speed is the same with or without a profile.
"""

import json
import math
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from config import app_dir

ADAPTER_FILE = "adapter.pt"
LORA_RANK = 16
LORA_ALPHA = 32
LORA_TOP_LAYERS = 8
_SAFE_NAME = re.compile(r"[^\w\- ]+", re.UNICODE)


# ---------------------------------------------------------------- folders
def profiles_root() -> Path:
    d = app_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_name(name: str) -> str:
    name = _SAFE_NAME.sub("", (name or "").strip())[:40].strip()
    return name or "User"


def profile_dir(name: str) -> Path:
    return profiles_root() / clean_name(name)


def voice_dir(name: str) -> Path:
    d = profile_dir(name) / "voice_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def adapter_path(name: str) -> Path:
    return profile_dir(name) / ADAPTER_FILE


def my_words_path(name: str) -> Path:
    return profile_dir(name) / "my_words.txt"


def load_my_words(name: str) -> list:
    try:
        lines = my_words_path(name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def save_my_words(name: str, words: list):
    seen, out = set(), []
    for w in words:
        w = " ".join(w.split())
        if w and w not in seen:
            seen.add(w); out.append(w)
    path = my_words_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def add_my_word(name: str, word: str):
    save_my_words(name, load_my_words(name) + [word])


def list_profiles():
    return sorted(p.name for p in profiles_root().iterdir() if (p / "profile.json").exists())


def load_meta(name: str) -> dict:
    try:
        return json.loads((profile_dir(name) / "profile.json").read_text(encoding="utf-8"))
    except Exception:
        return {"name": clean_name(name)}


def save_meta(name: str, meta: dict):
    path = profile_dir(name) / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def create_profile(name: str) -> str:
    name = clean_name(name)
    base, i = name, 2
    while (profile_dir(name) / "profile.json").exists():
        name = f"{base} {i}"; i += 1
    voice_dir(name)
    save_meta(name, {"name": name, "created": time.strftime("%Y-%m-%d %H:%M"), "use_adapter": True})
    return name


def delete_profile(name: str):
    d = profile_dir(name)
    if d.exists() and d.parent == profiles_root():
        shutil.rmtree(d)


def migrate_old_voice_data(default_name: str) -> str:
    """Move recordings made with the first version of 'Train my voice' into a profile."""
    old = app_dir() / "voice_data"
    if not old.exists() or not any(old.glob("clip_*.wav")):
        return ""
    name = list_profiles()[0] if list_profiles() else create_profile(default_name)
    dest = voice_dir(name)
    for p in old.iterdir():
        target = dest / p.name
        if not target.exists():
            shutil.move(str(p), str(target))
    try:
        old.rmdir()
    except OSError:
        pass
    return name


def export_profile(name: str, zip_path: str):
    d = profile_dir(name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in d.rglob("*"):
            if p.is_file() and not p.name.endswith((".tmp", "train_progress.json")):
                z.write(p, p.relative_to(d).as_posix())


def import_profile(zip_path: str) -> str:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "profile.json" not in names:
            raise ValueError("This file is not an Amharic Dictate voice profile.")
        meta = json.loads(z.read("profile.json").decode("utf-8"))
        name = create_profile(meta.get("name", Path(zip_path).stem))
        dest = profile_dir(name).resolve()
        for member in names:
            target = (dest / member).resolve()
            if dest not in target.parents and target != dest:
                continue                         # ignore unsafe paths inside the zip
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(member))
        meta["name"] = name
        save_meta(name, meta)
    return name


# ---------------------------------------------------------------- the add-on (LoRA)
def _layer_ids(model):
    ids = set()
    for name, _ in model.named_modules():
        m = re.search(r"encoder\.layers\.(\d+)$", name)
        if m:
            ids.add(int(m.group(1)))
    return sorted(ids)


def target_linears(model, top_layers=LORA_TOP_LAYERS):
    """Names of the Linear layers inside the top `top_layers` encoder layers."""
    import torch
    keep = set(_layer_ids(model)[-top_layers:])
    out = []
    for name, mod in model.named_modules():
        m = re.search(r"encoder\.layers\.(\d+)\.", name)
        if m and int(m.group(1)) in keep and isinstance(mod, torch.nn.Linear):
            out.append(name)
    return out


def model_signature(model) -> dict:
    cfg = model.config
    return {"model_type": getattr(cfg, "model_type", ""), "hidden": getattr(cfg, "hidden_size", 0),
            "layers": getattr(cfg, "num_hidden_layers", 0), "vocab": getattr(cfg, "vocab_size", 0)}


def inject_lora(model, rank=LORA_RANK, alpha=LORA_ALPHA, top_layers=LORA_TOP_LAYERS):
    """Wrap the target Linear layers with trainable low-rank adapters. Returns their names."""
    import torch

    class LoRALinear(torch.nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base
            self.scale = alpha / rank
            self.lora_A = torch.nn.Parameter(torch.empty(rank, base.in_features))
            self.lora_B = torch.nn.Parameter(torch.zeros(base.out_features, rank))
            torch.nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))

        def forward(self, x):
            return self.base(x) + (x @ self.lora_A.t() @ self.lora_B.t()) * self.scale

    names = target_linears(model, top_layers)
    for p in model.parameters():
        p.requires_grad = False
    for name in names:
        parent_name, child = name.rsplit(".", 1)
        parent = model.get_submodule(parent_name)
        setattr(parent, child, LoRALinear(getattr(parent, child)))
    return names


def adapter_state(model, names) -> dict:
    layers = {}
    for name in names:
        mod = model.get_submodule(name)
        layers[name] = {"A": mod.lora_A.detach().half().cpu(), "B": mod.lora_B.detach().half().cpu(),
                        "scale": float(mod.scale)}
    return layers


def save_adapter(path, model, names, base_model: str, result: dict):
    import torch
    payload = {"format": 1, "base_model": base_model, "signature": model_signature(model),
               "layers": adapter_state(model, names), "result": result,
               "date": time.strftime("%Y-%m-%d %H:%M")}
    tmp = str(path) + ".tmp"
    torch.save(payload, tmp)
    os.replace(tmp, path)


def merge_adapter(model, path, base_model: str = "") -> str:
    """Merge a saved add-on into the model's weights in place. Returns '' on success, else a reason."""
    import torch
    try:
        payload = torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as e:
        return f"could not read the voice profile ({e})"
    if payload.get("signature") != model_signature(model):
        return "the voice profile was trained for a different speech model — retrain it"
    with torch.no_grad():
        for name, st in payload["layers"].items():
            try:
                lin = model.get_submodule(name)
            except AttributeError:
                return "the voice profile does not match this speech model — retrain it"
            delta = (st["B"].float() @ st["A"].float()) * st["scale"]
            if delta.shape != lin.weight.shape:
                return "the voice profile does not match this speech model — retrain it"
            lin.weight += delta.to(lin.weight.dtype)
    return ""


def active_adapter(cfg: dict):
    """(profile name, adapter path or None) for the profile selected in settings."""
    name = cfg.get("profile") or ""
    if not name or not (profile_dir(name) / "profile.json").exists():
        return name, None
    meta = load_meta(name)
    p = adapter_path(name)
    if meta.get("use_adapter", True) and p.exists():
        return name, p
    return name, None
