#!/usr/bin/env python3
"""
Fine-tune facebook/w2v-bert-2.0 (MIT) into an Amharic CTC speech-recognition model
that you own and can use commercially (subject to the data licenses below).

Data sources (pick any combination with --sources):
  waxal          google/WaxalNLP, config "amh_asr"          CC-BY-4.0  (main source)
  fleurs         google/fleurs,   config "am_et"            CC-BY-4.0
  local:<dir>    your own folder of  clip.wav + clip.txt pairs (any audio format)
  hf:<repo>:<config>:<text_column>   any other HF dataset (check its license!)

CC-BY-4.0 requires attribution: the script writes it into the model card.

Examples
  # standard run on one cloud GPU (24 GB+)
  python train_amharic_ctc.py --sources waxal fleurs --output_dir am-w2vbert

  # add your own corrected recordings
  python train_amharic_ctc.py --sources waxal fleurs local:./my_clips --output_dir am-w2vbert-v2

  # quick smoke test (few minutes) before paying for a long run
  python train_amharic_ctc.py --sources fleurs --max_train_samples 200 --max_steps 50 --output_dir smoke

The result folder (<output_dir>/final) is a drop-in "model" for the Windows app's
config.json and for amharic_asr_benchmark.py.
"""

import argparse

import numpy as np
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SR = 16000

# --------------------------------------------------------------------------
# Text normalization for labels
# --------------------------------------------------------------------------
_HOMOPHONE_SERIES = {0x1210: 0x1200, 0x1280: 0x1200, 0x1220: 0x1230, 0x12D0: 0x12A0, 0x1340: 0x1338}
_HOMOPHONE_MAP = {s + i: d + i for s, d in _HOMOPHONE_SERIES.items() for i in range(7)}
_HOMOPHONE_MAP.update({0x1203: 0x1200, 0x12A3: 0x12A0})
_HOMOPHONE_MAP.update({k: _HOMOPHONE_MAP.get(v, v) for k, v in _HOMOPHONE_MAP.items()})

# Keep Ethiopic syllables (U+1200–U+135A, U+1380–U+139F, U+2D80–U+2DDF), ASCII digits, spaces.
_KEEP_RE = re.compile(r"[^ሀ-ፚᎀ-᎟ⶀ-⷟0-9 ]")
_SPACE_RE = re.compile(r"\s+")


def normalize_label(text: str, homophones: bool) -> str:
    text = unicodedata.normalize("NFC", text or "")
    if homophones:
        text = text.translate(_HOMOPHONE_MAP)
    text = _KEEP_RE.sub(" ", text)          # drops punctuation (። ፣ etc.), Latin, symbols
    return _SPACE_RE.sub(" ", text).strip()


def build_vocab(texts) -> dict:
    chars = sorted({c for t in texts for c in t})
    vocab = {c: i for i, c in enumerate(chars)}
    if " " in vocab:                         # CTC tokenizer uses "|" as word delimiter
        vocab["|"] = vocab.pop(" ")
    vocab["[UNK]"] = len(vocab)
    vocab["[PAD]"] = len(vocab)
    return vocab


def edit_distance(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def wer_cer(refs, hyps):
    we = rw = ce = rc = 0
    for r, h in zip(refs, hyps):
        we += edit_distance(r.split(), h.split()); rw += len(r.split())
        r2, h2 = r.replace(" ", ""), h.replace(" ", "")
        ce += edit_distance(r2, h2); rc += len(r2)
    return we / max(rw, 1), ce / max(rc, 1)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}


def decode_audio(a) -> np.ndarray:
    """Decode an audio entry ({'bytes', 'path'}) to 16 kHz mono float32 with soundfile/librosa.
    Avoids datasets' torchcodec decoder, which breaks when its build doesn't match the installed PyTorch."""
    import io
    import soundfile as sf
    try:
        src = io.BytesIO(a["bytes"]) if a.get("bytes") else a["path"]
        data, sr = sf.read(src, dtype="float32", always_2d=True)
        data = data.mean(axis=1)
    except Exception:
        try:
            import librosa
            src = io.BytesIO(a["bytes"]) if a.get("bytes") else a["path"]
            data, sr = librosa.load(src, sr=None, mono=True)
        except Exception:
            return np.zeros(0, dtype=np.float32)        # unreadable clip: filtered out later (0 s)
    if sr != SR:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=SR)
    return data.astype(np.float32)


def load_source(spec: str, split: str):
    """Return a Dataset with columns: audio, text   (or None if split doesn't exist)."""
    from datasets import Audio, Dataset, load_dataset

    if spec == "waxal":
        repo, config, col = "google/WaxalNLP", "amh_asr", "transcription"
    elif spec == "fleurs":
        repo, config, col = "google/fleurs", "am_et", "raw_transcription"
    elif spec.startswith("hf:"):
        _, repo, config, col = spec.split(":", 3)
    elif spec.startswith("local:"):
        folder = Path(spec[len("local:"):])
        files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTS and p.with_suffix(".txt").exists())
        if not files:
            raise SystemExit(f"No audio+txt pairs in {folder}")
        # deterministic ~90/5/5 split based on the file name
        def bucket(p):
            h = sum(map(ord, p.stem)) % 20
            return "test" if h == 0 else "validation" if h == 1 else "train"
        chosen = [p for p in files if bucket(p) == split]
        if not chosen:
            return None
        ds = Dataset.from_dict({
            "audio": [str(p) for p in chosen],
            "text": [p.with_suffix(".txt").read_text(encoding="utf-8") for p in chosen],
        })
        return ds.cast_column("audio", Audio(decode=False))
    else:
        raise SystemExit(f"Unknown source: {spec}")

    try:
        ds = load_dataset(repo, config, split=split)
    except ValueError:
        return None  # split not present
    ds = ds.cast_column("audio", Audio(decode=False))   # decoded by decode_audio (no torchcodec needed)
    ds = ds.rename_column(col, "text") if col != "text" else ds
    return ds.select_columns(["audio", "text"])


def load_all(sources, split, homophones, max_samples=None, seed=42):
    from datasets import concatenate_datasets
    parts = []
    for s in sources:
        repeat = 1
        if s.startswith("local:") and "@" in s:          # e.g. local:voice_data@5 -> count your voice 5x
            s, rep = s.rsplit("@", 1)
            repeat = int(rep)
        ds = load_source(s, split)
        if ds is not None and split == "train" and repeat > 1:
            ds = concatenate_datasets([ds] * repeat)
        if ds is None:
            print(f"  {s}: no '{split}' split, skipped")
            continue
        print(f"  {s} [{split}]: {len(ds)} clips")
        parts.append(ds)
    if not parts:
        return None
    ds = concatenate_datasets(parts).shuffle(seed=seed)
    ds = ds.map(lambda b: {"text": [normalize_label(t, homophones) for t in b["text"]]}, batched=True)
    ds = ds.filter(lambda t: len(t) > 0, input_columns="text")
    if max_samples:
        ds = ds.select(range(min(max_samples, len(ds))))
    return ds


# --------------------------------------------------------------------------
# Collator
# --------------------------------------------------------------------------
@dataclass
class CTCCollator:
    processor: object

    def __call__(self, features):
        inputs = [{"input_features": f["input_features"]} for f in features]
        labels = [{"input_ids": f["labels"]} for f in features]
        batch = self.processor.pad(inputs, padding=True, return_tensors="pt")
        lab = self.processor.pad(labels=labels, padding=True, return_tensors="pt")
        batch["labels"] = lab["input_ids"].masked_fill(lab.attention_mask.ne(1), -100)
        return batch


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", default=["waxal", "fleurs"])
    ap.add_argument("--base_model", default="facebook/w2v-bert-2.0")
    ap.add_argument("--output_dir", default="am-w2vbert")
    ap.add_argument("--epochs", type=float, default=10)
    ap.add_argument("--max_steps", type=int, default=-1)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--grad_accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--warmup_steps", type=int, default=500)
    ap.add_argument("--eval_steps", type=int, default=1000)
    ap.add_argument("--max_seconds", type=float, default=20.0)
    ap.add_argument("--max_train_samples", type=int)
    ap.add_argument("--max_eval_samples", type=int, default=800)
    ap.add_argument("--normalize_homophones", action="store_true",
                    help="train on standardized spelling (higher accuracy, but output always uses ሀ/ሰ/አ/ጸ forms)")
    ap.add_argument("--num_proc", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--push_to_hub", metavar="REPO_ID", help="optional: upload final model (private) to HF")
    args = ap.parse_args()

    import torch
    from transformers import (SeamlessM4TFeatureExtractor, Trainer, TrainingArguments,
                              Wav2Vec2BertForCTC, Wav2Vec2BertProcessor, Wav2Vec2CTCTokenizer)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- data
    print("Loading data…")
    train = load_all(args.sources, "train", args.normalize_homophones, args.max_train_samples)
    evals = load_all(args.sources, "validation", args.normalize_homophones, args.max_eval_samples)
    test = load_all(args.sources, "test", args.normalize_homophones)
    if train is None:
        raise SystemExit("No training data loaded.")

    # ---- tokenizer / processor
    all_text = list(train["text"]) + (list(evals["text"]) if evals else [])
    vocab = build_vocab(all_text)
    (out / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Vocabulary: {len(vocab)} symbols")
    tokenizer = Wav2Vec2CTCTokenizer(str(out / "vocab.json"), unk_token="[UNK]", pad_token="[PAD]", word_delimiter_token="|")
    feature_extractor = SeamlessM4TFeatureExtractor.from_pretrained(args.base_model)
    processor = Wav2Vec2BertProcessor(feature_extractor=feature_extractor, tokenizer=tokenizer)

    def prepare(batch):
        audio = decode_audio(batch["audio"])
        if len(audio) < SR // 4:
            audio = np.zeros(SR // 4, dtype=np.float32)    # keeps the map happy; removed by the length filter
            batch["seconds"] = 0.0
        else:
            batch["seconds"] = len(audio) / SR
        batch["input_features"] = processor(audio, sampling_rate=SR).input_features[0]
        batch["labels"] = processor(text=batch["text"]).input_ids
        return batch

    def featurize(ds, name):
        if ds is None:
            return None
        ds = ds.map(prepare, remove_columns=["audio"], num_proc=args.num_proc, desc=f"features [{name}]")
        ds = ds.filter(lambda s: 0.5 <= s <= args.max_seconds, input_columns="seconds")
        print(f"  {name}: {len(ds)} clips, {sum(ds['seconds']) / 3600:.1f} h")
        return ds

    train, evals, test = featurize(train, "train"), featurize(evals, "validation"), featurize(test, "test")

    # ---- model
    model = Wav2Vec2BertForCTC.from_pretrained(
        args.base_model,
        attention_dropout=0.0, hidden_dropout=0.0, feat_proj_dropout=0.0,
        mask_time_prob=0.0, layerdrop=0.0,
        ctc_loss_reduction="mean", add_adapter=True, ctc_zero_infinity=True,
        pad_token_id=processor.tokenizer.pad_token_id,
        vocab_size=len(processor.tokenizer),
    )

    def compute_metrics(pred):
        ids = pred.predictions.argmax(-1)
        pred.label_ids[pred.label_ids == -100] = processor.tokenizer.pad_token_id
        hyps = processor.batch_decode(ids)
        refs = processor.batch_decode(pred.label_ids, group_tokens=False)
        wer, cer = wer_cer(refs, hyps)
        return {"wer": wer, "cer": cer}

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    targs_kw = dict(
        output_dir=str(out),
        group_by_length=True,
        length_column_name="seconds",
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        gradient_checkpointing=True,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        warmup_steps=args.warmup_steps,
        bf16=bf16,
        fp16=torch.cuda.is_available() and not bf16,
        eval_strategy="steps" if evals is not None else "no",
        eval_steps=args.eval_steps,
        save_steps=args.eval_steps,
        logging_steps=50,
        save_total_limit=2,
        load_best_model_at_end=evals is not None,
        metric_for_best_model="wer",
        greater_is_better=False,
        dataloader_num_workers=min(4, args.num_proc),
        report_to="none",
    )
    # transformers versions differ in which settings exist: drop any this version doesn't know
    import dataclasses
    known = {f.name for f in dataclasses.fields(TrainingArguments)}
    dropped = [k for k in targs_kw if k not in known]
    if dropped:
        print("Note: this transformers version has no", ", ".join(dropped), "- skipped")
    targs = TrainingArguments(**{k: v for k, v in targs_kw.items() if k in known})
    trainer = Trainer(
        model=model, args=targs,
        data_collator=CTCCollator(processor),
        train_dataset=train, eval_dataset=evals,
        compute_metrics=compute_metrics,
        processing_class=processor,
    )

    # pick up where we left off if the machine restarted (checkpoints are saved every eval_steps)
    resume = any(out.glob("checkpoint-*"))
    if resume:
        print("Resuming from the last checkpoint in", out)
    trainer.train(resume_from_checkpoint=True if resume else None)

    # ---- final evaluation + save
    results = {}
    if test is not None:
        m = trainer.evaluate(test, metric_key_prefix="test")
        results = {k: round(v, 4) for k, v in m.items() if k in ("test_wer", "test_cer")}
        print("Test:", results)

    final = out / "final"
    trainer.save_model(str(final))
    processor.save_pretrained(str(final))
    (final / "README.md").write_text(model_card(args, results), encoding="utf-8")
    print(f"\nSaved model to {final}")
    print(f'Use it in the app: set  "model": "{final.resolve().as_posix()}"  in config.json')

    if args.push_to_hub:
        model.push_to_hub(args.push_to_hub, private=True)
        processor.push_to_hub(args.push_to_hub, private=True)


def model_card(args, results) -> str:
    srcs = {
        "waxal": "WAXAL (google/WaxalNLP, amh_asr) — CC-BY-4.0, © Google and partners",
        "fleurs": "FLEURS (google/fleurs, am_et) — CC-BY-4.0, © Google",
    }
    lines = [srcs.get(s, f"{s} — add license/attribution") for s in args.sources]
    return (
        "---\nlanguage: am\nlicense: mit\nbase_model: facebook/w2v-bert-2.0\n"
        "tags: [automatic-speech-recognition, amharic, ctc]\n---\n\n"
        "# Amharic ASR (w2v-BERT 2.0, CTC)\n\n"
        f"Fine-tuned from facebook/w2v-bert-2.0 (MIT).\n\n## Training data and attribution\n"
        + "".join(f"- {l}\n" for l in lines)
        + f"\nHomophone normalization: {'on' if args.normalize_homophones else 'off'}\n\n"
        + (f"## Test results\n{json.dumps(results)}\n" if results else "")
        + "\nOutput is unpunctuated words in Ethiopic script.\n"
    )


if __name__ == "__main__":
    main()
