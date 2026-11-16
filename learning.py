"""
Learn from corrections (opt-in, per voice profile).

During dictation the engine keeps each phrase's audio and the text the model produced. When the
person finishes (Done / paste), the final text is compared with the model's text. A phrase the
person corrected — and only one we can match safely — is saved as a training example:
the phrase's audio + the corrected words. The next profile training learns from them.

Saved as corr_NNNNN.wav / corr_NNNNN.txt in the profile's voice_data folder, on this computer only.
"""

import difflib
import re
import wave

import numpy as np

SR = 16000
MAX_CORRECTIONS = 2000              # keep the newest ones
MAX_CHANGED_FRACTION = 0.6          # a phrase rewritten more than this is a different sentence, not a fix
_PUNCT = re.compile(r"[።፣፤፥፦፧?!«»()\"'.,:;]")
_ETHIOPIC_WORD = re.compile(r"^[ሀ-ፚ]+$")


def words(text: str):
    return _PUNCT.sub(" ", text.replace("\n", " ")).split()


def corrected_phrases(records, final_text):
    """
    records: [{"audio": np.ndarray, "text": str, "usable": bool}] for each dictated phrase, in order.
    Returns [(audio, corrected_text)] for phrases the person changed and that can be matched safely.
    """
    orig, owner, starts = [], [], []
    for p, r in enumerate(records):
        starts.append(len(orig))
        for w in words(r["text"]):
            orig.append(w)
            owner.append(p)
    final = words(final_text)
    n = len(records)
    out_words = [[] for _ in range(n)]
    changed = [0] * n
    bad = [not r.get("usable", True) for r in records]

    sm = difflib.SequenceMatcher(None, orig, final, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out_words[owner[i1 + k]].append(final[j1 + k])
            continue
        if tag == "insert":
            # words added between two phrases (or at either end) can't be assigned safely
            if i1 == 0 or i1 == len(orig) or owner[i1 - 1] != owner[i1]:
                if i1 > 0:
                    bad[owner[i1 - 1]] = True
                if i1 < len(orig):
                    bad[owner[i1]] = True
                continue
            p = owner[i1]
            out_words[p].extend(final[j1:j2])
            changed[p] += j2 - j1
            continue
        # replace / delete
        ps = set(owner[i1:i2])
        if len(ps) > 1:                         # the change spans two phrases: can't split it
            for p in ps:
                bad[p] = True
            continue
        p = ps.pop()
        out_words[p].extend(final[j1:j2])
        changed[p] += max(i2 - i1, j2 - j1)

    result = []
    for p, r in enumerate(records):
        n_orig = len(words(r["text"]))
        new = out_words[p]
        if bad[p] or not changed[p] or not new or not n_orig:
            continue
        if changed[p] / max(n_orig, len(new)) > MAX_CHANGED_FRACTION:
            continue
        if not all(_ETHIOPIC_WORD.match(w) for w in new):      # digits, Latin etc. are not what was spoken
            continue
        audio = r["audio"]
        if not (1.0 * SR <= len(audio) <= 20 * SR):
            continue
        result.append((audio, " ".join(r.get("head", []) + new + r.get("tail", []))))
    return result


def save_corrections(voice_dir, pairs) -> int:
    """Write corr_NNNNN.wav/.txt files; keeps at most MAX_CORRECTIONS. Returns how many were saved."""
    existing = sorted(voice_dir.glob("corr_*.wav"))
    n = max([int(p.stem.split("_")[1]) for p in existing] + [-1]) + 1
    for audio, text in pairs:
        base = voice_dir / f"corr_{n:05d}"
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
        with wave.open(str(base.with_suffix(".wav")), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        base.with_suffix(".txt").write_text(text, encoding="utf-8")
        n += 1
    existing = sorted(voice_dir.glob("corr_*.wav"))
    for old in existing[: max(0, len(existing) - MAX_CORRECTIONS)]:
        old.unlink(missing_ok=True)
        old.with_suffix(".txt").unlink(missing_ok=True)
    return len(pairs)


def count_corrections(voice_dir) -> int:
    return sum(1 for p in voice_dir.glob("corr_*.wav") if p.with_suffix(".txt").exists())
