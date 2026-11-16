"""
Dictionary-guided CTC decoding.

The speech model outputs, for every ~20 ms frame, a probability for each letter. Greedy decoding
picks the single most likely letter per frame, so a faded or unclear syllable often becomes a
non-word. This beam search keeps several candidate spellings alive and, whenever a word is
completed, adds a bonus if it is a real Amharic word (from amharic_words.tsv), weighted by how
common it is. Clear audio still wins; the dictionary only decides when the audio is ambiguous.
"""
import math

import numpy as np

import textproc
from textproc import is_known_word, is_user_word, lexicon

NEG_INF = -1e30
_WORD_END = {"|", " ", "።", "፣", "፤", "፥", "፦", "?", "!", ".", ","}


def _lae(a, b):
    """log(exp(a) + exp(b))"""
    if a < b:
        a, b = b, a
    if b <= NEG_INF:
        return a
    return a + math.log1p(math.exp(b - a))


class LexiconDecoder:
    def __init__(self, id2tok: dict, blank: int, weight: float = 0.25, beam: int = 24, prune: float = -3.0):
        self.id2tok = id2tok
        self.blank = blank
        self.weight = weight
        self.beam = beam
        self.prune = prune                      # only letters with real acoustic support (p > ~5%) are considered
        self.lex = lexicon()
        self._bonus_cache = {}
        self._lex_version = textproc.LEX_VERSION

    def word_bonus(self, word: str) -> float:
        """Log-scale bonus for a completed word: common real words get more, unknown words none."""
        if len(word) < 2 or not self.lex:      # single letters (በ, የ…) are prefixes, not words: no bonus
            return 0.0
        if self._lex_version != textproc.LEX_VERSION:     # "My words" changed
            self._bonus_cache.clear()
            self._lex_version = textproc.LEX_VERSION
        b = self._bonus_cache.get(word)
        if b is None:
            f = self.lex.get(word, 0)
            if is_user_word(word):
                b = 8.0                            # "My words": names and terms the user added
            elif f:
                b = min(math.log(f + 1.0), 6.0) + 0.5
            elif is_known_word(word):          # known stem with a prefix/suffix
                b = 1.0
            else:
                b = 0.0
            b *= self.weight
            if len(self._bonus_cache) > 50000:
                self._bonus_cache.clear()
            self._bonus_cache[word] = b
        return b

    def _last_word(self, prefix) -> str:
        chars = []
        for k in reversed(prefix):
            t = self.id2tok.get(k, "")
            if t in _WORD_END:
                break
            chars.append(t)
        return "".join(reversed(chars))

    def decode(self, log_probs: np.ndarray, greedy_text: str = None) -> str:
        """log_probs: (T, V) log-softmax output of the CTC model."""
        blank = self.blank
        if not (log_probs.argmax(-1) != blank).any() or (greedy_text is not None and not greedy_text.strip()):
            return ""                           # the model heard nothing: never invent text
        beams = {(): (0.0, NEG_INF)}            # prefix -> (log p ending in blank, log p ending in letter)
        T = log_probs.shape[0]
        for t in range(T):
            lp = log_probs[t]
            lpb = float(lp[blank])
            if lpb > -0.001:                    # (almost) certainly blank: just extend every beam
                beams = {p: (_lae(pb, pnb) + lpb, NEG_INF) for p, (pb, pnb) in beams.items()}
                continue
            cands = [int(c) for c in np.nonzero(lp > self.prune)[0] if c != blank]
            nxt = {}

            def add(p, b_add, nb_add):
                ob, onb = nxt.get(p, (NEG_INF, NEG_INF))
                nxt[p] = (_lae(ob, b_add), _lae(onb, nb_add))

            for prefix, (pb, pnb) in beams.items():
                ptot = _lae(pb, pnb)
                add(prefix, ptot + lpb, NEG_INF)
                last = prefix[-1] if prefix else None
                for c in cands:
                    lc = float(lp[c])
                    new = prefix + (c,)
                    bonus = 0.0
                    if self.id2tok.get(c, "") in _WORD_END:
                        bonus = self.word_bonus(self._last_word(prefix))
                    if c == last:
                        add(new, NEG_INF, pb + lc + bonus)       # repeated letter needs a blank between
                        add(prefix, NEG_INF, pnb + lc)           # ...otherwise it collapses
                    else:
                        add(new, NEG_INF, ptot + lc + bonus)
            beams = dict(sorted(nxt.items(), key=lambda kv: -_lae(*kv[1]))[: self.beam])

        def final_score(item):
            prefix, (pb, pnb) = item
            return _lae(pb, pnb) + self.word_bonus(self._last_word(prefix))

        best = max(beams.items(), key=final_score)[0]
        out = []
        for k in best:
            t = self.id2tok.get(k, "")
            if t.startswith("[") or t.startswith("<"):
                continue
            out.append(" " if t == "|" else t)
        return "".join(out)


def level_audio(audio: np.ndarray, sr: int = 16000, target: float = 0.06, max_gain: float = 25.0,
                gate: float = 0.0006) -> np.ndarray:
    """
    Even out loud and quiet parts (e.g. a voice fading at the end of a word) before recognition.
    Gain is computed per 20 ms, smoothed, limited, and not applied to near-silence.
    """
    if len(audio) == 0:
        return audio
    hop = sr // 50
    n = int(math.ceil(len(audio) / hop))
    padded = np.pad(audio, (0, n * hop - len(audio)))
    rms = np.sqrt(np.mean(padded.reshape(n, hop) ** 2, axis=1)) + 1e-9
    gain = np.clip(target / rms, 1.0, max_gain)
    gain[rms < gate] = np.minimum(gain[rms < gate], 1.0 + (max_gain - 1.0) * 0.1)   # don't blow up noise
    k = 7                                                                             # ~140 ms smoothing
    gain = np.convolve(np.pad(gain, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
    per_sample = np.repeat(gain, hop)[: len(audio)]
    return np.clip(audio * per_sample, -1.0, 1.0).astype(np.float32)
