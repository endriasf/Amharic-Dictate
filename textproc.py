"""
Amharic text post-processing for dictation output.

  clean_text        strip model artifacts (tags, '|' delimiters), tidy spaces
  apply_commands    spoken punctuation / line breaks  ("አራት ነጥብ" -> ።)
  numbers_to_digits spoken numbers -> digits           ("ሁለት መቶ ሀምሳ" -> 250)
  finish_phrase     full pipeline for one finalized phrase
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Homophone folding (used only for MATCHING; the output keeps original spelling)
# --------------------------------------------------------------------------
_SERIES = {0x1210: 0x1200, 0x1280: 0x1200, 0x1220: 0x1230, 0x12D0: 0x12A0, 0x1340: 0x1338}
_FOLD = {s + i: d + i for s, d in _SERIES.items() for i in range(7)}
_FOLD.update({0x1203: 0x1200, 0x12A3: 0x12A0})          # ሃ->ሀ, ኣ->አ
_FOLD.update({k: _FOLD.get(v, v) for k, v in _FOLD.items()})


_SOUNDALIKE = {}
for _cp in range(0x1200, 0x1380):
    _SOUNDALIKE.setdefault(_FOLD.get(_cp, _cp), []).append(chr(_cp))


def homophone_variants(word: str, limit: int = 8) -> list:
    """Other spellings that sound the same (ሀ/ሐ/ኀ/ሃ, ሰ/ሠ, አ/ዐ/ኣ/ዓ, ጸ/ፀ), changing one letter at a time."""
    out = []
    for i, ch in enumerate(word):
        group = _SOUNDALIKE.get(_FOLD.get(ord(ch), ord(ch)), [])
        for alt in group:
            if alt != ch:
                v = word[:i] + alt + word[i + 1:]
                if v not in out:
                    out.append(v)
                if len(out) >= limit:
                    return out
    return out


def fold(word: str) -> str:
    return unicodedata.normalize("NFC", word).translate(_FOLD)


_TAG_RE = re.compile(r"<[^>]*>|\[[^\]]*\]")
_SPACE_RE = re.compile(r"[ \t]+")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = _TAG_RE.sub(" ", text)
    text = text.replace("|", " ")
    return _SPACE_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------
# Spoken commands
# --------------------------------------------------------------------------
# Multi-word phrases are used on purpose so normal speech rarely triggers them.
DELETE_WORD = "\x08"            # internal marker: remove the previous word
QUOTE_TOGGLE = "\x0e"           # internal marker: « or », whichever closes/opens the current quote
OPENERS = ("(", "«")
CLOSERS = (")", "»")

COMMANDS = [
    ("ያንን ሰርዝ", DELETE_WORD),   # "delete that" -> removes the last word
    ("ቅንፍ ክፈት", "("), ("ቅንፍ ክፍት", "("),
    ("ቅንፍ ዝጋ", ")"), ("ቅንፍ ዝጋው", ")"),
    ("ጥቅስ ክፈት", "«"), ("ጥቅስ ክፍት", "«"),
    ("ጥቅስ ዝጋ", "»"), ("ጥቅስ ዝጋው", "»"),
    ("ትእምርተ ጥቅስ", QUOTE_TOGGLE), ("ትምህርት ጥቅስ", QUOTE_TOGGLE), ("ትምርተ ጥቅስ", QUOTE_TOGGLE),
    ("አራት ነጥብ", "።"),        # full stop
    ("አራትነጥብ", "።"),
    ("አት ነጥብ", "።"),          # common mis-hearing of አራት ነጥብ
    ("ነጠላሰረዝ", "፣"),
    ("ነጠላ ሰረዝ", "፣"),        # comma
    ("ድርብ ሰረዝ", "፤"),        # semicolon
    ("የጥያቄ ምልክት", "?"),
    ("ቃለ አጋኖ", "!"),
    ("ቃል አጋኖ", "!"),
    ("ቃለአጋኖ", "!"),
    ("ቃለ አጋነ", "!"),
    ("አጋኖ ምልክት", "!"),
    ("አዲስ አንቀጽ", "\n\n"),
    ("አዲስ መስመር", "\n"),
]
_COMMANDS = [(tuple(fold(w) for w in phrase.split()), out) for phrase, out in COMMANDS]
_PUNCT = set("።፣፤፥፦?!") | set(CLOSERS)


def _close(word: str, target: str) -> bool:
    """Same word, or (for words of 3+ letters) one letter off — the model often mishears one syllable."""
    if word == target:
        return True
    if len(target) < 3 or abs(len(word) - len(target)) > 1:
        return False
    prev = list(range(len(target) + 1))
    for i, a in enumerate(word, 1):
        cur = [i] + [0] * len(target)
        for j, b in enumerate(target, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b))
        prev = cur
    return prev[-1] <= 1


def _skel(word: str) -> str:
    """Consonant skeleton: every Ge'ez letter reduced to its base form (ሳ→ሰ, ዘ/ዝ→ዘ, ሩ→ረ…).
    Speech models often get the consonant right but the vowel wrong."""
    out = []
    for ch in word:
        cp = ord(ch)
        if 0x1200 <= cp <= 0x135A:
            out.append(chr(0x1200 + (cp - 0x1200) // 8 * 8))
        else:
            out.append(ch)
    return "".join(out)


def _close_cmd(word: str, target: str) -> bool:
    """Command-word match: one letter off, or the same consonants with different vowels."""
    return _close(word, target) or (len(target) >= 2 and _skel(word) == _skel(target))


def _matches(words, pattern) -> bool:
    return len(words) == len(pattern) and all(_close_cmd(w, p) for w, p in zip(words, pattern))


def _matches_joined(word: str, pattern) -> bool:
    """A two-word command the model wrote as one word: ድርብሳረዝ, ነጠላሰረዝ, አራትነጥብ…"""
    if len(pattern) < 2:
        return False
    joined = "".join(pattern)
    return (len(joined) >= 5 and _close(word, joined)) or _skel(word) == _skel(joined)


_FOUR_RE = re.compile(r"4(ራት|ት)?")       # the model sometimes writes አራት as "4", "4ት" or "4ራት"


_JOINED_STOP_RE = re.compile(r"^(?:(?:አራ?ት?|ኣራት|4(?:ራ?ት)?)[ነመ][ጥጢጣ]?[ብቡ]|4(?:ራ?ት)?ጥ?ብ)$")   # አራትነጥብ, 4ነጥብ, 4ብ…
# a full stop said at the very end, with "ነጥብ" cut off as you stop talking: "... ነው 4"
_TRAILING_FOUR_RE = re.compile(r"(?:^|\s)4(?:ራ?ት)?\s*$")


_FOURISH = {fold(x) for x in ("አራት", "አራ", "አት", "አ", "ራት", "ኣራት", "አረት", "አራቱ")}
_STOPISH = {fold(x) for x in ("ነጥብ", "ብ", "ጥብ", "ነጥ", "ነብ", "ነጥቡ", "ነጢብ", "መጥብ", "ነጥፍ", "ነጥባ")}


def _is_four(w: str) -> bool:
    fw = fold(w)
    return fw in _FOURISH or bool(_FOUR_RE.fullmatch(w)) or _close(fw, fold("አራት"))


def _is_stop(w: str) -> bool:
    fw = fold(w.rstrip("።"))
    return fw in _STOPISH or _close_cmd(fw, fold("ነጥብ"))


_SEMI_FIRST = {fold(x) for x in ("ድርብ", "ድብ", "ድ", "ድር", "ድርቡ")}
_COMMA_FIRST = {fold(x) for x in ("ነጠላ", "ጠላ", "ነጠ", "ነጣላ")}


def _is_sereze(w: str) -> bool:
    fw = fold(w)
    return _close_cmd(fw, fold("ሰረዝ")) or fw in {fold("ረዝ"), fold("ሰረ"), fold("ሳረዝ"), fold("ሳረስ")}


def apply_commands(text: str) -> str:
    text = " ".join("።" if _JOINED_STOP_RE.match(fold(w)) else w for w in text.split(" "))
    # "አራት ነጥብ" as the model often hears it: "አ ነጥብ", "4 ብ", "አራ ጥብ"…
    ws, merged, i = text.split(" "), [], 0
    while i < len(ws):
        if i + 1 < len(ws) and ws[i] and _is_four(ws[i]) and _is_stop(ws[i + 1]):
            merged.append("።"); i += 2
        elif i + 1 < len(ws) and fold(ws[i]) in _SEMI_FIRST and _is_sereze(ws[i + 1]):
            merged.append("፤"); i += 2
        elif i + 1 < len(ws) and fold(ws[i]) in _COMMA_FIRST and _is_sereze(ws[i + 1]):
            merged.append("፣"); i += 2
        else:
            merged.append(ws[i]); i += 1
    text = " ".join(merged)
    words = text.split()
    folded = [fold("አራት") if _FOUR_RE.fullmatch(w) else fold(w) for w in words]
    out, i = [], 0
    while i < len(words):
        for pattern, symbol in _COMMANDS:
            n = len(pattern)
            if _matches(folded[i:i + n], pattern):
                out.append(symbol)
                i += n
                break
        else:
            for pattern, symbol in _COMMANDS:
                if _matches_joined(folded[i], pattern):
                    out.append(symbol)
                    break
            else:
                out.append(words[i])
            i += 1
    return join_tokens(out)


def join_tokens(tokens) -> str:
    """Join words, attaching punctuation to the previous word and handling newlines."""
    s = ""
    for t in tokens:
        if t == DELETE_WORD:
            s = s.rstrip(" ") + t + " "
        elif t in OPENERS or t == QUOTE_TOGGLE:
            if s and not s.endswith(("\n", " ") + OPENERS):
                s += " "
            s += t
        elif t in _PUNCT:
            s = s.rstrip(" ")
            if not s.endswith(t):              # model may already have added the same mark
                s += t
        elif t.startswith("\n"):
            s = s.rstrip(" ") + t
        else:
            if s and not s.endswith(("\n", " ") + OPENERS + (QUOTE_TOGGLE,)):
                s += " "
            s += t
    return s.strip(" ")


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------
def _f(d):
    return {fold(k): v for k, v in d.items()}


UNITS = _f({"አንድ": 1, "ሁለት": 2, "ሶስት": 3, "ሦስት": 3, "አራት": 4, "አምስት": 5,
            "ስድስት": 6, "ሰባት": 7, "ስምንት": 8, "ዘጠኝ": 9})
TEN = _f({"አስር": 10, "አሥር": 10})
TEEN_PREFIX = _f({"አስራ": 10, "አሥራ": 10})
TENS = _f({"ሀያ": 20, "ሃያ": 20, "ሰላሳ": 30, "ሠላሳ": 30, "አርባ": 40, "ሀምሳ": 50, "ሃምሳ": 50,
           "አምሳ": 50, "ስልሳ": 60, "ስድሳ": 60, "ሰባ": 70, "ሰማንያ": 80, "ዘጠና": 90})
HUNDRED = _f({"መቶ": 100})
SCALES = _f({"ሺ": 1000, "ሺህ": 1000, "ሚሊዮን": 1_000_000, "ቢሊዮን": 1_000_000_000})


def _kind(w):
    for kind, table in (("unit", UNITS), ("ten", TEN), ("teen", TEEN_PREFIX), ("tens", TENS),
                        ("hundred", HUNDRED), ("scale", SCALES)):
        if w in table:
            return kind, table[w]
    return None, None


# which token kinds may follow the previous one inside a single number
_ALLOWED = {
    None:      {"unit", "ten", "teen", "tens", "hundred", "scale"},
    "unit":    {"hundred", "scale"},
    "ten":     {"hundred", "scale"},
    "teen":    {"unit"},
    "tens":    {"unit", "hundred", "scale"},
    "hundred": {"unit", "ten", "teen", "tens", "scale"},
    "scale":   {"unit", "ten", "teen", "tens", "hundred"},
}


def _value(tokens):
    total, current = 0, 0
    for kind, v in tokens:
        if kind in ("unit", "ten", "teen", "tens"):
            current += v
        elif kind == "hundred":
            current = (current or 1) * 100
        elif kind == "scale":
            total += (current or 1) * v
            current = 0
    return total + current


_NUM_PREFIXES = ["እስከ", "ለ", "በ", "ከ", "የ"]
_ELIDED_UNITS = _f({"ንድ": 1, "ራት": 4, "ምስት": 5})        # ሃያራት = ሃያ + አራት (አ dropped)
_ORD_SUFFIXES = ("ኛዎቹ", "ኛዋ", "ኛው", "ኛ")


def _parse_number_token(w: str):
    """
    Read one token as part of a number. Returns (prefix, [(kind, value), ...], suffix) or None.
    Handles ሃያ, ለሃያ, ሃያአራት/ሃያራት, አራተኛ (4th -> 4ኛ), አራቱ (-> 4ቱ), and digits 20/4.
    """
    if w.isdigit():
        n = int(w)
        if 1 <= n <= 9:
            return "", [("unit", n)], ""
        if 20 <= n <= 90 and n % 10 == 0:
            return "", [("tens", n)], ""
        return None
    m = re.fullmatch(r"([2-9])(\D+)", w)                 # "2አራት" (ሃያ heard as 2) -> 24
    if m:
        u = UNITS.get(fold(m.group(2)))
        if u:
            return "", [("tens", int(m.group(1)) * 10), ("unit", u)], ""
    f = fold(w)
    for pre in [""] + _NUM_PREFIXES:
        if pre and not f.startswith(pre):
            continue
        rest = f[len(pre):]
        if not rest:
            continue
        kind, v = _kind(rest)
        if kind:
            return pre, [(kind, v)], ""
        for tw, tv in TENS.items():                      # tens + unit written together
            if rest.startswith(tw) and len(rest) > len(tw):
                r2 = rest[len(tw):]
                u = UNITS.get(r2) or _ELIDED_UNITS.get(r2)
                if u:
                    return pre, [("tens", tv), ("unit", u)], ""
        for suf in _ORD_SUFFIXES:                        # ordinals: አራተኛ -> 4ኛ, ሃያኛ -> 20ኛ
            if rest.endswith(suf) and len(rest) > len(suf):
                stem = rest[: -len(suf)]
                for cand in (stem, stem[:-1] + _base6(stem[-1]), stem + "ት"):
                    kind, v = _kind(cand)
                    if kind:
                        return pre, [(kind, v)], suf
        last6 = rest[:-1] + _base6(rest[-1])             # fused ending: አራቱ (the four) -> 4ቱ
        if last6 != rest:
            kind, v = _kind(last6)
            if kind:
                return pre, [(kind, v)], rest[-1]
    return None


def numbers_to_digits(text: str) -> str:
    """Convert spoken number sequences to digits. Single small numbers ("አንድ ሰው") stay as words."""
    words = text.split(" ")
    out, group, raw = [], [], []
    state = {"prefix": "", "suffix": ""}

    def flush():
        if group:
            if group[-1][0] == "teen" and not state["suffix"]:     # dangling "አስራ" is not a number
                out.extend(raw)
            else:
                val = _value(group)
                if val >= 10 or len(group) >= 2:
                    num = f"{val:,}" if val >= 10_000 else str(val)
                    out.append(state["prefix"] + num + state["suffix"])
                else:
                    out.extend(raw)
        group.clear(); raw.clear()
        state["prefix"], state["suffix"] = "", ""

    for w in words:
        parsed = _parse_number_token(w) if w else None
        if parsed is None:
            flush(); out.append(w); continue
        prefix, parts, suffix = parsed
        prev = group[-1][0] if group else None
        if prefix or parts[0][0] not in _ALLOWED[prev]:
            flush()
        if not group:
            state["prefix"] = prefix
        group.extend(parts); raw.append(w)
        if suffix:                                       # a suffixed word ends the number
            state["suffix"] = suffix
            flush()
    flush()
    return " ".join(out)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
_MODEL_PUNCT_RE = re.compile(r"[።፣፤፥፦፧?!]")


def finish_phrase(text: str, cfg: dict) -> str:
    text = clean_text(text)
    # the model sometimes writes the spoken "አራት ነጥብ" as "4።" / "አ።": keep that as the user's command
    text = re.sub(r"(?:^|(?<=\s))(?:4|አ|አራ|አራት)\s*።", " አራት ነጥብ ", text).strip()
    if cfg.get("voice_commands", True) and len(text.split()) > 1:
        text = _TRAILING_FOUR_RE.sub(" አራት ነጥብ", text).strip()
    if cfg.get("voice_commands", True) and len(text.split()) == 1:
        w = text.strip()
        fw = fold(w)
        if fw != fold("አ") and (_FOUR_RE.fullmatch(w) or _close_cmd(fw, fold("አራት")) or fw == fold("አራ")
                                or fw in _STOPISH - {fold("ብ")} or _close_cmd(fw, fold("ነጥብ"))):
            text = "አራት ነጥብ"           # "አራት … ነጥብ" said with a pause in the middle
    if not cfg.get("model_punctuation", False):
        # the model guesses ። etc. on its own; by default only spoken commands add punctuation
        text = _SPACE_RE.sub(" ", _MODEL_PUNCT_RE.sub(" ", text)).strip()
    if not text:
        return ""
    if cfg.get("voice_commands", True):
        text = apply_commands(text)
    if cfg.get("numbers_to_digits", True):
        text = "\n".join(numbers_to_digits(line) for line in text.split("\n"))
    if cfg.get("auto_period", False) and text and text[-1] not in _PUNCT and not text.endswith("\n"):
        text += "።"
    return text


def join_phrases(phrases) -> str:
    s = ""
    for p in phrases:
        if not p:
            continue
        if s and not s.endswith(("\n",) + OPENERS) and not p.startswith(("\n",) + tuple(_PUNCT)):
            s += " "
        s += p
    return s


# --------------------------------------------------------------------------
# Dictionary (amharic_words.tsv: word<TAB>frequency) — suggestions + spelling fixes
# --------------------------------------------------------------------------
import os as _os

_LEX = None
_USER_WORDS = {}          # "My words" of the active profile: word -> frequency it replaced (None if new)
USER_FREQ = 5000          # as common as everyday words, so the decoder and spell-check prefer them
LEX_VERSION = 0           # bumped when My words change (decoder caches check it)
_ETH_LETTERS = [chr(c) for c in range(0x1200, 0x135B)]


def lexicon() -> dict:
    global _LEX
    if _LEX is None:
        _LEX = {}
        path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "amharic_words.tsv")
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    w, _, n = line.rstrip("\n").partition("\t")
                    if w:
                        _LEX[w] = int(n or 1)
        except OSError:
            pass
    return _LEX


def set_user_words(words):
    """Install the active profile's "My words" into the dictionary (replacing any previous list)."""
    global LEX_VERSION
    lex = lexicon()
    for w, old in _USER_WORDS.items():
        if old is None:
            lex.pop(w, None)
        else:
            lex[w] = old
    _USER_WORDS.clear()
    for phrase in words:
        for w in phrase.split():
            w = w.strip("።፣፤፥፦?!«»()")
            if len(w) >= 2 and w not in _USER_WORDS:
                _USER_WORDS[w] = lex.get(w)
                lex[w] = max(lex.get(w, 0), USER_FREQ)
    LEX_VERSION += 1


def is_user_word(word: str) -> bool:
    return word in _USER_WORDS


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def _near_user_word(core: str):
    """A "My words" entry this unknown word is very likely meant to be (one letter off, or a sound-alike)."""
    if len(core) < 3 or not _USER_WORDS:
        return None
    fc = fold(core)
    for w in tuple(_USER_WORDS):
        if abs(len(w) - len(core)) <= 1 and len(w) >= 3 and (fold(w) == fc or _edit_distance(w, core) <= 1):
            return w
    return None


def _edit1_known(word: str, lex: dict) -> list:
    """Dictionary words one letter away (change, drop or add one letter)."""
    out = set()
    for i in range(len(word) + 1):
        if i < len(word):
            d = word[:i] + word[i + 1:]
            if d in lex:
                out.add(d)
            for ch in _ETH_LETTERS:
                v = word[:i] + ch + word[i + 1:]
                if v in lex:
                    out.add(v)
        for ch in _ETH_LETTERS:
            v = word[:i] + ch + word[i:]
            if v in lex:
                out.add(v)
    out.discard(word)
    return list(out)


def suggest(word: str, model_alts=(), limit: int = 6) -> list:
    """Ranked replacements: the model's own alternatives and sound-alike spellings first, then common near words."""
    lex = lexicon()
    scored = {}
    for v in model_alts:
        if v != word:
            scored[v] = max(scored.get(v, 0), 3 * lex.get(v, 0) + 2)        # always offered
    for v in homophone_variants(word, limit=50):
        if v in lex:
            scored[v] = max(scored.get(v, 0), 2 * lex[v] + 1)
    if lex:
        for v in _edit1_known(word, lex):
            scored[v] = max(scored.get(v, 0), lex[v])
    if not lex:                                                          # no dictionary: unranked sound-alikes
        for v in homophone_variants(word):
            scored.setdefault(v, 0)
    return [w for w, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]


def autocorrect(text: str, min_freq: int = 5):
    """
    Fix spellings the dictionary doesn't know when a sound-alike spelling is a common word
    (e.g. ሠላም/ሰላም, ፀሐይ/ጸሐይ). Returns (text, {new_word: original_word}).
    """
    lex = lexicon()
    if not lex:
        return text, {}
    changes = {}
    out = []
    for token in text.split(" "):
        core = token.rstrip("።፣፤፥፦?!")
        tail = token[len(core):]
        if core and ord(core[0]) >= 0x1200 and "\n" not in core:
            own = lex.get(core, 0)
            best = max((v for v in homophone_variants(core, limit=60) if lex.get(v, 0) >= min_freq),
                       key=lambda v: lex[v], default=None)
            # unknown spelling, or a rare one when a sound-alike spelling is far more common
            if best and (own == 0 or lex[best] >= max(20, 30 * own)):
                changes[best] = core
                token = best + tail
            elif own == 0 and not _stem_known(core, lex):
                near = _near_user_word(core)           # one letter off one of "My words"
                if near:
                    changes[near] = core
                    token = near + tail
        out.append(token)
    return " ".join(out), changes


# --------------------------------------------------------------------------
# Spell check: is this a known word (allowing common Amharic prefixes/suffixes)?
# --------------------------------------------------------------------------
_PREFIXES = sorted(["የ", "በ", "ለ", "ከ", "እንደ", "ስለ", "ወደ", "እስከ", "ስ", "ሲ", "እየ", "ያ", "የሚ", "የማ", "ለማ",
                    "በማ", "ከማ", "እና", "ም", "ሊ", "ማ"], key=len, reverse=True)
_SUFFIXES = sorted(["ን", "ም", "ና", "ው", "ዋ", "ዎች", "ዎቹ", "ዎቻቸው", "ኦች", "ች", "ቹ", "ቸው", "ችን", "ቻችን",
                    "ሽ", "ህ", "ሁ", "ኝ", "ኛ", "ኛው", "ኛዋ", "ውን", "ዋን", "ቸውን", "ቱ", "ቷ", "ቶች", "ነት", "ዊ", "ውም",
                    "ንም", "ስ", "ማ", "ሳ", "ቸ", "ልኝ", "ልህ", "ልሽ", "ለት", "ላት", "ላቸው", "ባት", "በት", "በኝ"],
                   key=len, reverse=True)


def _base6(ch: str) -> str:
    """Same consonant in 6th order (no vowel): ቱ -> ት, ሩ -> ር. Suffixes often fuse into the last letter."""
    cp = ord(ch)
    if 0x1200 <= cp < 0x1358:
        return chr(cp - (cp - 0x1200) % 8 + 5)
    return ch


def _stem_known(w: str, lex: dict, depth: int = 0) -> bool:
    if len(w) < 2:
        return False
    if w in lex:
        return True
    if depth >= 2:
        return False
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            stem = w[: -len(suf)]
            if _stem_known(stem, lex, depth + 1) or _stem_known(stem[:-1] + _base6(stem[-1]), lex, depth + 1):
                return True
    # fused vowel on the last letter, e.g. ቤቱ (ቤት + ው), ልጁ (ልጅ + ው)
    if _base6(w[-1]) != w[-1] and (w[:-1] + _base6(w[-1])) in lex:
        return True
    for pre in _PREFIXES:
        if w.startswith(pre) and len(w) - len(pre) >= 2 and _stem_known(w[len(pre):], lex, depth + 1):
            return True
    return False


def is_known_word(word: str) -> bool:
    """True if the word (or its stem) is in the dictionary. Non-Amharic tokens and numbers count as known."""
    lex = lexicon()
    core = word.strip("።፣፤፥፦?!")
    if not lex or not core or any(not (0x1200 <= ord(c) < 0x1400) for c in core):
        return True
    return _stem_known(core, lex)


def misspelling_fix(word: str, min_freq: int = 3):
    """
    If the word looks misspelled, return the most likely correct dictionary word, else None.
    Flags only unknown words that are one letter away from a reasonably common word,
    so correct but rare forms (many Amharic verb forms) are left alone.
    """
    if is_known_word(word):
        return None
    lex = lexicon()
    core = word.strip("።፣፤፥፦?!")
    if len(core) < 2:
        return None
    best = max((v for v in _edit1_known(core, lex) if lex[v] >= min_freq), key=lambda v: lex[v], default=None)
    return best
