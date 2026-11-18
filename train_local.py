"""
Personal voice adaptation on CPU.

Trains a small low-rank add-on (LoRA, a few MB) for one voice profile on the person's own
recordings (clip_*.wav + clip_*.txt). The shared speech model itself is never changed.
Some recordings are held out; the add-on is saved only if it beats the plain model on them.

Usage (normally started by the app):
  python train_local.py --base <model folder> --base-name <model id> --data <voice_data>
                        --out <adapter.pt> --profile-json <profile.json> --progress <json>
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import wave

import numpy as np

SR = 16000


class Progress:
    def __init__(self, path):
        self.path = path
        self.t0 = time.time()

    def update(self, fraction, message, done=False, **extra):
        data = {"fraction": max(0.0, min(1.0, fraction)), "message": message, "done": done,
                "elapsed_s": round(time.time() - self.t0), **extra}
        tmp = self.path + ".tmp"
        for attempt in range(5):          # the window may be reading the file at this moment (Windows locks it)
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self.path)
                return
            except OSError:
                time.sleep(0.2 * (attempt + 1))
        # progress is only informational: never let it stop training


def load_wav(path):
    with wave.open(path, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return pcm


def normalize(text, vocab):
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[።፣፤፥፦፧፨?!.,:;\"'«»()\[\]-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(c for c in text if c == " " or c in vocab)


SPOKEN_PUNCT = {"።": "አራት ነጥብ", "፣": "ነጠላ ሰረዝ", "፤": "ድርብ ሰረዝ", "?": "የጥያቄ ምልክት", "!": "ቃለ አጋኖ",
                "(": "ቅንፍ ክፈት", ")": "ቅንፍ ዝጋ", "«": "ጥቅስ ክፈት", "»": "ጥቅስ ዝጋ"}


class SpokenMarks:
    """A reading sentence and the punctuation marks in it that have a spoken form. Each mark may or
    may not have been said aloud ("አራት ነጥብ" for ።, "ነጠላ ሰረዝ" for ፣, ...), independently."""

    def __init__(self, raw, vocab):
        self.raw = unicodedata.normalize("NFC", raw).strip()
        self.vocab = vocab
        self.marks = [k for k, c in enumerate(self.raw) if c in SPOKEN_PUNCT]

    def text(self, said=()):
        said = set(said)
        return normalize("".join(f" {SPOKEN_PUNCT[c]} " if k in said else c
                                 for k, c in enumerate(self.raw)), self.vocab)


def choose_spoken(sm, nll):
    """Pick which marks were said aloud: start from none, then try saying each mark (two passes)
    and keep the change when the recording fits better. nll(text) -> lower is a better fit."""
    said = set()
    best = nll(sm.text(said))
    for _ in range(2):
        changed = False
        for k in sm.marks:
            trial = said ^ {k}
            score = nll(sm.text(trial))
            if score < best:
                said, best, changed = trial, score, True
        if not changed:
            break
    return sm.text(said), said


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def error_rates(pairs):
    we = rw = ce = rc = 0
    for ref, hyp in pairs:
        we += edit_distance(ref.split(), hyp.split()); rw += len(ref.split())
        r2, h2 = ref.replace(" ", ""), hyp.replace(" ", "")
        ce += edit_distance(r2, h2); rc += len(r2)
    return we / max(rw, 1), ce / max(rc, 1)


_LOCK_FILE = None


def acquire_training_lock(folder: str) -> bool:
    """Only one training per profile at a time (a second one would compete for the same files)."""
    global _LOCK_FILE
    os.makedirs(folder, exist_ok=True)
    f = open(os.path.join(folder, "training.lock"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _LOCK_FILE = f                    # held until this process exits
    return True


def main(argv=None):
    if sys.stdout is None:                         # installed app (no console)
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):        # Amharic in messages must never stop training
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--progress", required=True)
    ap.add_argument("--base-name", default="")
    ap.add_argument("--profile-json", default="")
    ap.add_argument("--epochs", type=int, default=0, help="0 = choose from the number of recordings")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=0, help="for quick tests")
    ap.add_argument("--always-save", action="store_true", help="for tests: save the add-on even if not better")
    args = ap.parse_args(argv)
    prog = Progress(args.progress)
    if not acquire_training_lock(os.path.dirname(os.path.abspath(args.progress))):
        prog.update(1.0, "Another training for this profile is already running — this one was not started.",
                    done=True, ok=False)
        return 2

    try:
        prog.update(0.0, "Loading the speech model…")
        import torch
        from transformers import AutoModelForCTC, AutoProcessor
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        torch.manual_seed(0)

        processor = AutoProcessor.from_pretrained(args.base)
        model = AutoModelForCTC.from_pretrained(args.base)
        vocab = set(processor.tokenizer.get_vocab())

        # ---- data
        clips = []
        for name in sorted(os.listdir(args.data)):
            if name.startswith(("clip_", "corr_")) and name.endswith(".wav"):
                txt = os.path.join(args.data, name[:-4] + ".txt")
                if os.path.exists(txt):
                    sm = SpokenMarks(open(txt, encoding="utf-8").read(), vocab)
                    if sm.text():
                        clips.append((os.path.join(args.data, name), sm))
        if len(clips) < 10:
            prog.update(1.0, "Not enough recordings to train (need at least 30).", done=True, ok=False)
            return 1

        # ---- did the person say the punctuation ("አራት ነጥብ") while reading? Ask the standard model
        # which version of each sentence fits the recording best. Training on the wrong version would
        # teach the profile to write nothing when you say a punctuation word.
        model.eval()
        to_check = [i for i, (_, sm) in enumerate(clips) if sm.marks]
        said_count, marks_count = {}, {}
        with torch.inference_mode():
            for n, i in enumerate(to_check):
                wav, sm = clips[i]
                try:
                    lp = model(**processor(load_wav(wav), sampling_rate=SR, return_tensors="pt")).logits
                    lp = lp.float().log_softmax(-1).transpose(0, 1)
                    T = torch.tensor([lp.shape[0]])

                    def nll(text):
                        ids = processor.tokenizer(text, return_tensors="pt").input_ids
                        return torch.nn.functional.ctc_loss(lp, ids, T, torch.tensor([ids.shape[1]]),
                                                            blank=processor.tokenizer.pad_token_id,
                                                            reduction="sum", zero_infinity=True).item()
                    text, said = choose_spoken(sm, nll)
                    for k in sm.marks:
                        c = sm.raw[k]
                        marks_count[c] = marks_count.get(c, 0) + 1
                        said_count[c] = said_count.get(c, 0) + (k in said)
                    clips[i] = (wav, text)
                except Exception:
                    clips[i] = (wav, sm.text())
                prog.update(0.02 * (n + 1) / max(1, len(to_check)),
                            f"Checking how you read punctuation ({n + 1}/{len(to_check)})")
        clips = [(w, t if isinstance(t, str) else t.text()) for w, t in clips]
        print("punctuation said aloud: " + ", ".join(f"{c} {said_count[c]}/{marks_count[c]}" for c in marks_count),
              flush=True)
        if not args.epochs:                      # small sets need more passes; big sets fewer
            args.epochs = 8 if len(clips) < 80 else 5 if len(clips) < 200 else 3
        rnd = random.Random(42)
        rnd.shuffle(clips)
        n_test = max(5, len(clips) // 8)
        test, train = clips[:n_test], clips[n_test:]

        def features(audio):
            return processor(audio, sampling_rate=SR, return_tensors="pt")

        def evaluate(m, label, start, span):
            m.eval()
            pairs = []
            with torch.inference_mode():
                for i, (wav, ref) in enumerate(test):
                    inputs = features(load_wav(wav))
                    ids = m(**inputs).logits.argmax(-1)
                    hyp = re.sub(r"\s+", " ", processor.batch_decode(ids)[0].replace("|", " ")).strip()
                    pairs.append((ref, hyp))
                    prog.update(start + span * (i + 1) / len(test), f"{label} ({i + 1}/{len(test)})")
            return error_rates(pairs)

        # ---- baseline
        base_wer, base_cer = evaluate(model, "Testing the standard model on your voice", 0.02, 0.08)

        # ---- add the small trainable voice add-on (everything else stays frozen)
        from voiceprofile import inject_lora, save_adapter
        lora_names = inject_lora(model)
        if not lora_names:
            prog.update(1.0, "Training failed: could not find the model's layers.", done=True, ok=False)
            return 1
        params = [p for p in model.parameters() if p.requires_grad]
        n_train = sum(p.numel() for p in params)
        opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
        model.config.ctc_zero_infinity = True

        total_steps = args.epochs * len(train)
        if args.max_steps:
            total_steps = min(total_steps, args.max_steps)
        warmup = max(1, total_steps // 10)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / warmup) * max(0.05, 1 - s / max(total_steps, 1)))

        # ---- train
        model.train()
        step, t_start, running = 0, time.time(), None
        done_training = False
        for epoch in range(args.epochs):
            order = list(range(len(train)))
            rnd.shuffle(order)
            for k in order:
                wav, text = train[k]
                audio = load_wav(wav)
                if len(audio) > 20 * SR:
                    continue
                inputs = features(audio)
                labels = processor.tokenizer(text, return_tensors="pt").input_ids
                out = model(**inputs, labels=labels)
                loss = out.loss / args.accum
                if torch.isfinite(loss):
                    loss.backward()
                    lv = out.loss.item()
                    running = lv if running is None else 0.95 * running + 0.05 * lv
                step += 1
                if step % args.accum == 0:
                    torch.nn.utils.clip_grad_norm_(params, 1.0)
                    opt.step(); sched.step(); opt.zero_grad()
                per_step = (time.time() - t_start) / step
                eta = per_step * (total_steps - step)
                prog.update(0.10 + 0.80 * step / total_steps,
                            f"Training on your voice: epoch {epoch + 1}/{args.epochs}, step {step}/{total_steps} — "
                            f"about {eta / 3600:.1f} h left" if eta > 5400 else
                            f"Training on your voice: epoch {epoch + 1}/{args.epochs}, step {step}/{total_steps} — "
                            f"about {max(1, round(eta / 60))} min left",
                            loss=round(running or 0, 3))
                if args.max_steps and step >= args.max_steps:
                    done_training = True
                    break
            if done_training:
                break
        if step % args.accum:
            opt.step(); opt.zero_grad()

        # ---- compare and save only if better
        new_wer, new_cer = evaluate(model, "Testing your voice profile", 0.90, 0.08)
        n_corr = sum(1 for w, _ in clips if os.path.basename(w).startswith("corr_"))
        better = new_cer < base_cer - 0.005 or args.always_save
        summary = (f"Without profile: {base_wer:.0%} of words wrong ({base_cer:.0%} of letters).  "
                   f"With your profile: {new_wer:.0%} of words wrong ({new_cer:.0%} of letters).")
        result = {"base_wer": base_wer, "base_cer": base_cer, "new_wer": new_wer, "new_cer": new_cer,
                  "clips": len(clips), "trained_params": n_train,
                  "punctuation_said": {c: f"{said_count[c]}/{marks_count[c]}" for c in marks_count}, "date": time.strftime("%Y-%m-%d %H:%M")}
        if better:
            save_adapter(args.out, model, lora_names, args.base_name or args.base, result)
            if args.profile_json:
                try:
                    meta = json.load(open(args.profile_json, encoding="utf-8"))
                except Exception:
                    meta = {}
                meta.update({"use_adapter": True, "result": result})
                meta["last_trained_corrections"] = n_corr
                tmp = args.profile_json + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=1)
                os.replace(tmp, args.profile_json)
            prog.update(1.0, "Done! Your voice profile is now active. " + summary, done=True, ok=True,
                        base_wer=base_wer, new_wer=new_wer)
        else:
            if args.profile_json:                 # don't retrain automatically again until more corrections arrive
                try:
                    meta = json.load(open(args.profile_json, encoding="utf-8"))
                    meta["last_trained_corrections"] = n_corr
                    tmp = args.profile_json + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, args.profile_json)
                except Exception:
                    pass
            prog.update(1.0, "Done, but no improvement yet — nothing was changed. " + summary +
                        "  Recording more sentences usually helps.", done=True, ok=False,
                        base_wer=base_wer, new_wer=new_wer)
        return 0
    except Exception as e:
        import traceback
        prog.update(1.0, f"Training failed: {e}", done=True, ok=False, error=traceback.format_exc())
        return 1


def run_and_exit(argv=None):
    """Run training, then end the process at once. Without this, background threads started by
    torch/transformers can keep the process alive after training is done, so the app still
    thinks it is training."""
    try:
        rc = main(argv)
    except BaseException:
        rc = 1
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    os._exit(rc or 0)


if __name__ == "__main__":
    run_and_exit()
