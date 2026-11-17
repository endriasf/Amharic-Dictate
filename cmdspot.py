"""
Recognize spoken punctuation and other short voice commands said on their own.

Said alone after a pause, a short command such as "አራት ነጥብ" is often too short for the speech
model to write out: it produces nothing, or a fragment. Instead of asking the model what it heard,
this asks how well each command fits the sound (CTC scoring: the probability that the model's
letter-by-letter output spells exactly that command). The best-fitting command is used only
when it fits clearly better than the other commands and close to what the model heard.
"""

import numpy as np

SPOKEN = ["አራት ነጥብ", "ነጠላ ሰረዝ", "ድርብ ሰረዝ", "የጥያቄ ምልክት", "ቃለ አጋኖ",
          "አዲስ መስመር", "አዲስ አንቀጽ", "ቅንፍ ክፈት", "ቅንፍ ዝጋ", "ጥቅስ ክፈት", "ጥቅስ ዝጋ", "ያንን ሰርዝ"]

MAX_SECONDS = 3.5          # longer phrases are ordinary speech
MAX_GAP = 0.45             # per speech frame: how far below the model's best guess a command may be
MIN_LEAD = 3.0             # how much better (log-probability) than the next-best command


def _logsumexp(a, b):
    m = np.maximum(a, b)
    with np.errstate(invalid="ignore"):
        d = np.where(np.isneginf(m), 0.0, -np.abs(a - b))
    return np.where(np.isneginf(m), -np.inf, m + np.log1p(np.exp(d)))


def ctc_score(lp: np.ndarray, seq, blank: int) -> float:
    """log P(seq | frames) under CTC. lp: [T, V] log-probabilities."""
    T = lp.shape[0]
    ext = [blank]
    for s in seq:
        ext += [s, blank]
    S = len(ext)
    if T < len(seq):
        return -np.inf
    ext = np.array(ext)
    skip = np.zeros(S, bool)
    skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    a = np.full(S, -np.inf)
    a[0] = lp[0, ext[0]]
    a[1] = lp[0, ext[1]]
    for t in range(1, T):
        prev = a
        a = prev.copy()
        a[1:] = _logsumexp(a[1:], prev[:-1])
        a[2:] = np.where(skip[2:], _logsumexp(a[2:], prev[:-2]), a[2:])
        a = a + lp[t, ext]
    return float(_logsumexp(a[-1], a[-2]))


class CommandSpotter:
    def __init__(self, id2tok: dict, blank: int):
        self.blank = blank
        tok2id = {t: i for i, t in id2tok.items()}
        space = tok2id.get("|", tok2id.get(" "))
        self.cands = []                     # (spoken text, token ids)
        for phrase in SPOKEN:
            for form in {phrase, phrase.replace(" ", "")}:
                ids = []
                for ch in form:
                    i = space if ch == " " else tok2id.get(ch)
                    if i is None:
                        break
                    ids.append(i)
                else:
                    self.cands.append((phrase, ids))

    def spot(self, lp: np.ndarray):
        """Returns (command or None, details for the log)."""
        if not self.cands:
            return None, ""
        best = {}
        for phrase, ids in self.cands:
            s = ctc_score(lp, ids, self.blank)
            if s > best.get(phrase, -np.inf):
                best[phrase] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        (p1, s1), (p2, s2) = ranked[0], ranked[1]
        free = float(lp.max(-1).sum())                       # the model's own best guess
        speech = int((lp.argmax(-1) != self.blank).sum()) or int((lp[:, self.blank] < np.log(0.9)).sum())
        speech = max(speech, len(p1))
        gap = (free - s1) / speech
        lead = s1 - s2
        ok = gap <= MAX_GAP and lead >= MIN_LEAD
        return (p1 if ok else None), f"spot={p1} gap={gap:.2f} lead={lead:.1f} next={p2} -> {'USED' if ok else 'no'}"
