"""Speech-to-text model wrapper and the live dictation engine (UI-independent)."""

import collections
import os
import re
import queue
import threading
import time

import numpy as np

from textproc import (CLOSERS, DELETE_WORD, OPENERS, QUOTE_TOGGLE, autocorrect, clean_text, finish_phrase,
                      join_phrases)

GAP_MARK = "▮"                 # shown where new words will be inserted
SEL_L, SEL_R = "⟦", "⟧"        # wrap the highlighted (clicked) word in the display text

SR = 16000
BLOCK = 1600  # 100 ms


MODEL_FILES = ["*.json", "*.safetensors", "*.bin", "*.txt", "*.model", "README.md"]


def _paths_file():
    from config import app_dir
    return os.path.join(app_dir(), "model_paths.json")


def _remembered_paths() -> dict:
    import json
    try:
        with open(_paths_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ensure_model(model_id: str, on_status=lambda s: None) -> str:
    """Return a local folder for the model. Downloads only the first time; after that no internet is used."""
    import json
    from config import BUNDLED_MODEL, MODEL_PRESETS, bundled_model_dir
    if model_id == BUNDLED_MODEL:
        bundled = bundled_model_dir()
        if bundled:
            return bundled                             # shipped inside the app: never downloads
        model_id = MODEL_PRESETS[0][0]                 # running from source: fall back to the default model
    if os.path.isdir(model_id):
        return model_id
    paths = _remembered_paths()
    known = paths.get(model_id)
    if known and os.path.isfile(os.path.join(known, "config.json")):
        return known                                   # already on this PC: no network at all
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(model_id, local_files_only=True, allow_patterns=MODEL_FILES)
        if not os.path.isfile(os.path.join(path, "config.json")):
            raise FileNotFoundError(path)
    except Exception:
        on_status("Downloading model (one time only, 0.5–2.5 GB)… keep the internet on")
        path = snapshot_download(model_id, allow_patterns=MODEL_FILES)
    paths[model_id] = path
    try:
        with open(_paths_file(), "w", encoding="utf-8") as f:
            json.dump(paths, f, indent=1)
    except Exception:
        pass
    return path


_PUNCT_CHARS = set("።፣፤፥፦፧?!.,")


def ctc_alternatives(probs: np.ndarray, id2tok: dict, blank: int, min_conf=0.75, min_alt=0.08, per_word=3) -> dict:
    """
    From CTC frame probabilities (T x V), find letters the model was unsure about and build
    alternative spellings using its runner-up letter. Returns {word: [alternative spellings]}.
    """
    best = probs.argmax(-1)
    words, cur = [], []           # cur: list of (char, conf, alt_char, alt_p)
    t = 0
    T = len(best)
    while t < T:
        k = int(best[t])
        t2 = t
        while t2 + 1 < T and int(best[t2 + 1]) == k:
            t2 += 1
        if k != blank:
            tok = id2tok.get(k, "")
            if tok in ("|", " ") or tok in _PUNCT_CHARS:
                if cur:
                    words.append(cur); cur = []
            elif not tok.startswith("[") and not tok.startswith("<"):
                seg = probs[t:t2 + 1]
                conf = float(seg[:, k].max())
                masked = seg.copy()
                masked[:, [k, blank]] = 0.0
                for i2, tk in id2tok.items():
                    if tk in ("|", " ") or tk in _PUNCT_CHARS or tk.startswith("[") or tk.startswith("<"):
                        masked[:, i2] = 0.0
                j = int(masked.max(0).argmax())
                cur.append((tok, conf, id2tok.get(j, ""), float(masked[:, j].max())))
        t = t2 + 1
    if cur:
        words.append(cur)
    out = {}
    for w in words:
        word = "".join(c for c, *_ in w)
        cands = []
        for i, (c, conf, alt, ap) in enumerate(w):
            if conf < min_conf and ap >= min_alt and alt:
                cands.append((ap, word[:i] + alt + word[i + 1:]))
        if cands:
            cands.sort(reverse=True)
            out[word] = [v for _, v in cands[:per_word]]
    return out


class Transcriber:
    def __init__(self, model_path: str, device: str = "auto", quantize_cpu: bool = True,
                 use_lm: bool = False, lm_weight: float = 0.25, auto_level: bool = True,
                 min_confidence: float = 0.0, adapter=None):
        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        self.torch = torch
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_path)
        model = AutoModelForCTC.from_pretrained(model_path).eval()
        self.profile_problem = ""
        if adapter is not None:                    # personal voice profile: merged into the weights
            from voiceprofile import merge_adapter
            self.profile_problem = merge_adapter(model, adapter)
        if device == "cpu":
            torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
            if quantize_cpu:
                model = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
        else:
            model = model.half()
        self.model = model.to(device)
        self._lock = threading.Lock()
        self.want_alternatives = False
        self.last_alternatives = {}
        tok = self.processor.tokenizer
        self._id2tok = {i: t for t, i in tok.get_vocab().items()}
        self._blank = tok.pad_token_id
        self.auto_level = auto_level
        self.min_confidence = min_confidence
        self.last_greedy = ""
        self.last_confidence = 1.0
        self.lm = None
        if use_lm:
            from lmdecode import LexiconDecoder
            self.lm = LexiconDecoder(self._id2tok, self._blank, weight=lm_weight)

    def __call__(self, audio: np.ndarray) -> str:
        if len(audio) < SR // 4:
            return ""
        if self.auto_level:
            from lmdecode import level_audio
            audio = level_audio(audio, SR)
        with self._lock, self.torch.inference_mode():
            inputs = self.processor(audio, sampling_rate=SR, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            if self.device == "cuda":
                inputs = {k: (v.half() if v.is_floating_point() else v) for k, v in inputs.items()}
            logits = self.model(**inputs).logits
            ids = logits.argmax(dim=-1)
            if self.want_alternatives:
                try:
                    probs = logits[0].float().softmax(-1).cpu().numpy()
                    self.last_alternatives = ctc_alternatives(probs, self._id2tok, self._blank)
                except Exception:
                    self.last_alternatives = {}
            self.last_greedy = clean_text(self.processor.batch_decode(ids)[0])
            # confidence: how sure the model was about the letters it heard (low for noise / background talk)
            probs = logits[0].float().softmax(-1)
            top, arg = probs.max(-1)
            spoken = arg != self._blank
            self.last_confidence = float(top[spoken].mean()) if bool(spoken.any()) else 0.0
            if self.min_confidence and self.last_confidence < self.min_confidence:
                return ""
            if self.lm is not None:
                try:
                    lp = logits[0].float().log_softmax(-1).cpu().numpy()
                    return clean_text(self.lm.decode(lp, self.last_greedy))
                except Exception:
                    pass                                      # fall back to plain decoding
            return clean_text(self.processor.batch_decode(ids)[0])


class DictationEngine:
    """
    100 ms blocks -> adaptive energy VAD -> phrases.
    Live preview re-transcribes the current phrase every `partial_every_s` (fast model).
    A pause ends the phrase; its accurate final text is produced on a background
    worker so the live preview never stalls. Finals are committed in order.
    """

    def __init__(self, transcribe, cfg, on_partial, on_phrase, preview=None):
        self.transcribe = transcribe          # accurate model: final text
        self.preview = preview or transcribe  # fast model: live preview
        self.cfg = cfg
        self.on_partial = on_partial
        self.on_phrase = on_phrase
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.running = False
        self.committed: list[str] = []
        self.level = 0.0                    # mic level for the UI meter
        self._thread = None
        self.paused = False
        self._lock = threading.RLock()
        self.debug_dir = None               # set to a folder to save session audio + timings
        self.learn = False             # keep phrase audio to learn from corrections (opt-in)
        self.records = []
        self.decode_log = None              # set to a file path to log each decoding step (text only)
        self._session = []
        self._timings = []
        self._jobs: "queue.Queue" = queue.Queue()
        self._pending = collections.deque()  # preview text of phrases awaiting their final text
        self._current = ""                    # preview of the phrase being spoken now
        self._worker = None
        self.alternatives = {}                # word -> model's alternative spellings (unsure words)
        if hasattr(transcribe, "want_alternatives"):
            transcribe.want_alternatives = True
        self._history = collections.deque(maxlen=14)   # undo snapshots
        self._replacing = False               # a clicked word was removed; next phrase fills the gap
        self._after = ""                      # committed text after that gap
        self._seq = 0                         # id of the next phrase to be finalized
        self._in_phrase = False               # a phrase is being spoken right now
        self._gap_min = 0                     # phrases with id >= this fill the clicked spot

    def _refresh(self):
        with self._lock:
            cur_id = self._seq                       # id the phrase being spoken will get
            if not self._replacing:
                parts = list(self.committed) + [t for _, t in self._pending if t]
                if self._current:
                    parts.append(self._current)
            else:
                into = [t for i, t in self._pending if t and i >= self._gap_min]
                tail = [t for i, t in self._pending if t and i < self._gap_min]
                if self._current:
                    (into if cur_id >= self._gap_min else tail).append(self._current)
                parts = list(self.committed) + into
                if into:
                    pass                                  # new words shown in place of the highlighted one
                elif self._gap_word:
                    sel = SEL_L + self._gap_word + SEL_R
                    if self._gap_word in "።፣፤፥፦?!" or self._gap_word in CLOSERS:
                        if parts:
                            parts[-1] = parts[-1] + sel           # marks sit right against the previous word
                        else:
                            parts.append(sel)
                    else:
                        parts.append(sel)
                else:
                    parts.append(GAP_MARK)
                if self._after:
                    if self._gap_word in OPENERS and not into:   # an opening mark sits right against the next word
                        parts[-1] = parts[-1] + self._after
                    else:
                        parts.append(self._after)
                parts += tail                             # spoken before the click: stays at the end
            text = join_phrases(parts)
        self.on_partial(text)

    def _mark_gap_start(self):
        """Only speech that starts after this moment goes into the clicked spot."""
        self._gap_min = self._seq + (1 if self._in_phrase else 0)

    # ---- undo (up to 14 steps)
    def _snap(self):
        with self._lock:
            self._history.append((list(self.committed), self._after, self._replacing, self._gap_word))

    def undo(self) -> bool:
        with self._lock:
            if not self._history:
                return False
            committed, after, replacing, gap = self._history.pop()
            self.committed, self._after, self._replacing, self._gap_word = committed, after, replacing, gap
        self._refresh()
        return True

    @property
    def undo_steps(self) -> int:
        return len(self._history)

    # ---- click-to-replace (called from the UI thread)
    def committed_text(self) -> str:
        with self._lock:
            return join_phrases(self.committed)

    def document_text(self) -> str:
        """All finished text in reading order, as it should appear in the document
        (a highlighted word still shows as itself; speech still being recognised is left out)."""
        with self._lock:
            if not self._replacing:
                return join_phrases(self.committed).strip(" ")
            parts = list(self.committed)
            if self._gap_word:
                parts.append(self._gap_word)
            if self._after:
                parts.append(self._after)
            return join_phrases(parts).strip(" ")

    def set_document_text(self, text: str) -> bool:
        """The person edited the text in the document itself: adopt it (Undo can bring the old text back)."""
        with self._lock:
            if self._replacing or text == join_phrases(self.committed).strip(" "):
                return False                 # mid-correction: the next sync will pick it up
            self._history.append((list(self.committed), self._after, self._replacing, self._gap_word))
            self.committed = [text] if text else []
        self._refresh()
        return True

    def _restore_selection(self):
        with self._lock:
            if self._replacing:
                if self._gap_word:
                    self.committed.append(self._gap_word)
                self._merge_after()
                self._gap_word = ""

    def cancel_selection(self):
        self._restore_selection()
        self._refresh()

    def begin_replace(self, start: int, end: int) -> bool:
        """Highlight committed text[start:end]; the next finished phrase replaces it."""
        self._snap()
        with self._lock:
            if self._replacing:
                self._restore_selection()
            full = join_phrases(self.committed)
            if not (0 <= start < end <= len(full)):
                return False
            before, after = full[:start].rstrip(" "), full[end:].lstrip(" ")
            self._gap_word = full[start:end]
            self.committed = [before] if before else []
            self._after = after
            self._replacing = True
            self._mark_gap_start()
        self._refresh()
        return True

    def begin_insert(self, pos: int) -> bool:
        """Open a gap at a position between words; the next finished phrase is inserted there."""
        self._snap()
        with self._lock:
            if self._replacing:
                self._restore_selection()
            full = join_phrases(self.committed)
            if not (0 <= pos <= len(full)):
                return False
            before, after = full[:pos].rstrip(" "), full[pos:].lstrip(" ")
            self.committed = [before] if before else []
            self._after = after
            self._gap_word = ""
            self._replacing = True
            self._mark_gap_start()
        self._refresh()
        return True

    def keep_word_insert(self, where: str):
        """While replacing a clicked word: put it back and open the gap 'before' or 'after' it instead."""
        with self._lock:
            if not self._replacing or not self._gap_word:
                return
            word = self._gap_word
            if where == "after":
                self.committed.append(word)
            else:
                self._after = join_phrases([word] + ([self._after] if self._after else []))
            self._gap_word = ""
        self._refresh()

    def join_at_gap(self):
        """Remove the space where the gap is, joining the words on either side (e.g. 'ቤተ ክርስቲያን' -> 'ቤተክርስቲያን')."""
        with self._lock:
            if not self._replacing or self._gap_word:
                return
            before = join_phrases(self.committed)
            joined = before.rstrip(" ") + self._after.lstrip(" ")
            self.committed = [joined] if joined else []
            self._after, self._replacing = "", False
        self._refresh()

    def join_clicked(self, direction: str):
        """Put the clicked word back, glued to the previous ('prev') or next ('next') word."""
        with self._lock:
            if not self._replacing or not self._gap_word:
                return
            before = join_phrases(self.committed).rstrip(" ")
            after = self._after.lstrip(" ")
            word = self._gap_word
            if direction == "prev":
                text = before + word + ((" " + after) if after else "")
            else:
                text = ((before + " ") if before else "") + word + after
            self.committed = [text] if text else []
            self._after, self._replacing, self._gap_word = "", False, ""
        self._refresh()

    @property
    def gap_word(self) -> str:
        return self._gap_word if self._replacing else ""

    def fill_gap(self, text: str):
        """Put text where the clicked word was (a chosen suggestion, or the original word for Undo)."""
        with self._lock:
            if not self._replacing:
                return
            if text:
                self.committed.append(text)
            self._merge_after()
        self._refresh()

    def undo_replace(self):
        self.fill_gap(self._gap_word)

    @property
    def replacing(self) -> bool:
        return self._replacing

    def _merge_after(self):
        with self._lock:
            if self._replacing:
                self.committed = [join_phrases(self.committed + ([self._after] if self._after else []))]
                if self.committed == [""]:
                    self.committed = []
                self._after, self._replacing = "", False

    def feed(self, block: np.ndarray):
        if self.running and not self.paused:
            b = block.copy()
            self.q.put(b)
            if self.debug_dir:
                self._session.append(b)

    def _timed(self, audio, kind):
        t0 = time.perf_counter()
        text = (self.preview if kind == "partial" else self.transcribe)(audio)
        if self.debug_dir:
            self._timings.append(f"{kind:8s} audio={len(audio)/SR:5.1f}s  took={time.perf_counter()-t0:5.2f}s  queue={self.q.qsize()}  text={text}")
        return text

    def _save_debug(self):
        import os, wave
        os.makedirs(self.debug_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if self._session:
            pcm = (np.clip(np.concatenate(self._session), -1, 1) * 32767).astype("<i2")
            with wave.open(os.path.join(self.debug_dir, f"session-{stamp}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        with open(os.path.join(self.debug_dir, f"session-{stamp}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(self._timings) + "\n")

    # ---- pause / delete (called from the UI thread)
    def pause(self, on: bool):
        if not self.running or on == self.paused:
            return
        self.paused = on
        if on:
            self.q.put(None)          # tells the loop to finish the phrase in progress now
            self.level = 0.0

    def add_punctuation(self, mark: str):
        """Called from the UI: finish the phrase being spoken, then add the mark after it."""
        if self.running:
            self.q.put(("punct", mark))
        else:
            self._add_mark(mark)
            self._refresh()

    def _add_mark(self, mark: str):
        self._snap()
        if mark in OPENERS:
            with self._lock:
                self.committed.append(mark)
            return
        with self._lock:
            if self.committed and mark == "።":
                # a half-heard "አራት ነጥብ" left "4"/"አ" at the end: the button replaces it
                self.committed[-1] = re.sub(r"\s(?:4|አ|አራ|አራት)$", "", self.committed[-1].rstrip(" "))
            if self.committed:
                self.committed[-1] = self.committed[-1].rstrip(" ") + mark if mark not in "\n" else self.committed[-1] + mark
            else:
                self.committed.append(mark)

    def delete_last_word(self):
        """Called from the UI: runs after any phrases still being finalized, so it removes the right word."""
        if self.running or (self._worker and self._worker.is_alive()):
            self._jobs.put(("delete",))
        else:
            self._delete_now()
            self._refresh()

    def _delete_now(self):
        self._snap()
        with self._lock:
            while self.committed:
                words = self.committed[-1].rstrip().split(" ")
                words.pop()
                rest = " ".join(words).rstrip()
                if rest:
                    self.committed[-1] = rest
                    break
                self.committed.pop()
                break

    def _commit(self, text: str):
        """Add a finished phrase, applying any spoken 'delete that' commands."""
        while QUOTE_TOGGLE in text:
            with self._lock:
                so_far = join_phrases(self.committed) + text[: text.index(QUOTE_TOGGLE)]
            mark = "«" if so_far.count("«") <= so_far.count("»") else "»"
            i = text.index(QUOTE_TOGGLE)
            if mark == "»":                       # closing quote attaches to the previous word
                text = text[:i].rstrip(" ") + "»" + text[i + 1:]
                if i == 0 or not text[:i].strip():
                    with self._lock:              # quote closes text from an earlier phrase
                        if self.committed:
                            self.committed[-1] = self.committed[-1].rstrip(" ") + "»"
                            text = text.lstrip("»").lstrip(" ")
            else:
                text = text[:i] + "«" + text[i + 1:].lstrip(" ")
        parts = text.split(DELETE_WORD)
        for i, part in enumerate(parts):
            if i > 0:
                self._delete_now()
                self._history.pop() if self._history else None   # same undo step as the phrase
            part = part.strip(" ")
            if part:
                with self._lock:
                    self.committed.append(part)
                    replaced = self._replacing
                    if replaced:
                        self._merge_after()       # gap filled: carry on at the end
                if not replaced:
                    self.on_phrase(part)

    def _final_loop(self):
        while True:
            job = self._jobs.get()
            if job is None:
                break
            try:
                if job[0] == "final":
                    raw = self._timed(job[1], "final")
                    text = finish_phrase(raw, self.cfg)
                    preview_was = self._pending[0][1] if self._pending else ""
                    pid = job[2] if len(job) > 2 else self._seq
                    fixed = {}
                    alts = getattr(self.transcribe, "last_alternatives", None)
                    if alts:
                        with self._lock:
                            self.alternatives.update(alts)
                    before_fix = text
                    if self.cfg.get("autocorrect_spelling", True) and text:
                        text, fixed = autocorrect(text)
                    if self.decode_log:
                        try:
                            with open(self.decode_log, "a", encoding="utf-8") as f:
                                f.write(f"{time.strftime('%H:%M:%S')} audio={len(job[1])/SR:.1f}s replacing={self._replacing} "
                                        f"confidence={getattr(self.transcribe, 'last_confidence', 1.0):.2f}\n"
                                        f"  preview : {preview_was}\n"
                                        f"  plain   : {getattr(self.transcribe, 'last_greedy', '')}\n"
                                        f"  dict    : {raw}\n"
                                        f"  commands: {before_fix}\n"
                                        f"  final   : {text}\n")
                        except Exception:
                            pass
                    if self.learn and text and not (self._replacing and pid >= self._gap_min):
                        self._record_phrase(job[1], raw, before_fix, text)
                    with self._lock:
                        for new, old in fixed.items():           # click a fixed word to get the original back
                            self.alternatives[new] = [old] + self.alternatives.get(old, [])
                    with self._lock:
                        if self._pending:
                            self._pending.popleft()
                    if text:
                        if self._replacing and pid < self._gap_min:
                            # spoken before the click: belongs at the end, not in the clicked spot
                            self._snap()
                            with self._lock:
                                clean = text.replace(DELETE_WORD, " ").strip()
                                self._after = join_phrases(([self._after] if self._after else []) + [clean])
                            self.on_phrase(clean)
                        else:
                            if not self._replacing:   # filling a clicked spot is part of that click's undo step
                                self._snap()
                            self._commit(text)
                elif job[0] == "delete":
                    self._delete_now()
                elif job[0] == "punct":
                    self._add_mark(job[1])
            except Exception:
                import traceback
                traceback.print_exc()
            self._refresh()

    def _record_phrase(self, audio, raw, processed, text):
        """Keep a dictated phrase's audio for 'learn from my corrections' (opt-in)."""
        from learning import words
        rw, pw = words(raw), words(processed)
        head = tail = None
        if DELETE_WORD not in text and pw:
            for i in range(len(rw) - len(pw) + 1):           # spoken commands before/after the words
                if rw[i:i + len(pw)] == pw:
                    head, tail = rw[:i], rw[i + len(pw):]
                    break
        self.records.append({"audio": np.asarray(audio, dtype=np.float32), "text": text,
                             "usable": head is not None, "head": head or [], "tail": tail or []})

    def start(self):
        self.paused = False
        self.records = []
        self._seq, self._in_phrase, self._gap_min = 0, False, 0
        self.committed = []
        self._after, self._replacing = "", False
        self._gap_word = ""
        self._history.clear()
        self.alternatives = {}
        self._pending.clear()
        self._current = ""
        self.records = []
        self._jobs = queue.Queue()
        self._worker = threading.Thread(target=self._final_loop, daemon=True)
        self._worker.start()
        self._session, self._timings = [], []
        with self.q.mutex:
            self.q.queue.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> str:
        self.running = False
        if self._thread:
            self._thread.join()        # speech loop hands its last phrase to the worker
        self._jobs.put(None)
        if self._worker:
            self._worker.join()        # wait for every final text
        self._merge_after()
        if self.debug_dir:
            try:
                self._save_debug()
            except Exception:
                pass
        return join_phrases(self.committed).strip(" ")

    def _loop(self):
        cfg = self.cfg
        silence_blocks = max(1, int(cfg["silence_ms"] / 100))
        max_blocks = int(cfg["max_phrase_s"] * 10)
        floor = cfg["min_threshold"]
        recent = []                       # last ~10 s of block levels, for the noise floor
        phrase, pre_roll = [], []
        quiet, next_partial = 0, 0.0

        def best_cut(blocks):
            """Index to split a long phrase: the quietest 100 ms block in the last ~3 s (a gap between words)."""
            lo = max(len(blocks) // 2, len(blocks) - 30)
            hi = len(blocks) - 3
            if hi <= lo:
                return len(blocks)
            rms = [float(np.sqrt(np.mean(blocks[i] ** 2))) for i in range(lo, hi)]
            return lo + int(np.argmin(rms)) + 1

        def finalize():
            nonlocal phrase, quiet
            if phrase:
                with self._lock:
                    pid = self._seq
                    self._seq += 1
                    self._pending.append((pid, self._current))   # keep showing the preview until the final is ready
                    self._current = ""
                    self._in_phrase = False
                self._jobs.put(("final", np.concatenate(phrase), pid))
                self._refresh()
            phrase, quiet = [], 0

        while self.running or not self.q.empty():
            try:
                block = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            if block is None:                 # paused: wrap up the current phrase
                finalize()
                pre_roll = []
                continue
            if isinstance(block, tuple):      # ("punct", mark) from a button: after the current phrase
                finalize()
                self._jobs.put(block)
                continue
            rms = float(np.sqrt(np.mean(block ** 2)) + 1e-9)
            self.level = rms
            recent = (recent + [rms])[-100:]
            # background level: needs ~3 s of audio, and is capped so continuous speech can't be mistaken for noise
            noise = min(float(np.percentile(recent, 10)), 0.004) if len(recent) >= 30 else 0.0
            # hysteresis: harder to start a phrase than to keep one going, so soft word endings aren't cut
            if phrase:
                voiced = rms > max(floor * 0.6, noise * 2.0)
            else:
                voiced = rms > max(floor, noise * 3.0)

            if phrase:
                phrase.append(block)
                quiet = 0 if voiced else quiet + 1
                if quiet >= silence_blocks:
                    finalize()
                    continue
                if len(phrase) >= max_blocks:          # long run of speech without a pause
                    cut = best_cut(phrase)
                    rest = phrase[cut:]
                    phrase = phrase[:cut]
                    finalize()
                    phrase = rest
                    continue
            elif voiced:
                phrase = pre_roll + [block]
                self._in_phrase = True
                quiet = 0
            else:
                pre_roll = (pre_roll + [block])[-5:]   # keep 500 ms before speech starts

            # live preview: only when caught up, and spaced out so it never uses more than ~half the CPU time
            if phrase and time.monotonic() >= next_partial and self.q.qsize() <= 4:
                t0 = time.monotonic()
                partial = finish_phrase(self._timed(np.concatenate(phrase), "partial"), {**cfg, "auto_period": False})
                partial = partial.replace(DELETE_WORD, " ⌫ ")
                with self._lock:
                    self._current = partial
                self._refresh()
                took = time.monotonic() - t0
                next_partial = time.monotonic() + max(cfg["partial_every_s"], took)

        finalize()
        self.level = 0.0
