"""
Amharic spelling for Microsoft Word, using Amharic Dictate's own dictionary.

Word has no Amharic spell checker, so it checks Amharic text with the English one and underlines
every word. This module:
- marks Amharic text as Amharic and excluded from (English) proofing, so the false red lines go away;
- finds Amharic words the app's dictionary doesn't know (plus "My words"), with suggestions;
- fixes them directly in the document.
"""

import re

AMHARIC_LANG_ID = 1118                 # wdAmharic
_WORD_RE = re.compile(r"[ሀ-ፚ]+")           # Ge'ez letters only (no punctuation/numerals)
_WILDCARD_AMHARIC = "[ሀ-ፚ]{1,}"


def connect():
    """The active Word document (raises if Word or a document isn't open)."""
    import win32com.client
    word = win32com.client.GetActiveObject("Word.Application")
    return word, word.ActiveDocument


def target_range(word, doc):
    """The selected text if there is a selection, otherwise the whole document."""
    sel = word.Selection
    try:
        if sel.Document.FullName == doc.FullName and sel.End > sel.Start:
            return doc.Range(sel.Start, sel.End), True
    except Exception:
        pass
    return doc.Content, False


_RUN_RE = re.compile(r"[\u1200-\u137C]+(?:[ \u00A0]+[\u1200-\u137C]+)*")   # Amharic words + spaces between


def _spans(rng, regex):
    """(range, text) for each regex match, mapped onto document positions. Positions in Range.Text
    normally line up with the document; where they don't (fields, tables), the match is located
    with Word's own Find instead."""
    text = rng.Text or ""
    base = rng.Start
    doc = rng.Document
    for m in regex.finditer(text):
        r = doc.Range(base + m.start(), base + m.end())
        if r.Text != m.group(0):
            r = None
            probe = doc.Range(base + max(0, m.start() - 50), rng.End)
            f = probe.Find
            f.ClearFormatting(); f.Text = m.group(0); f.MatchWildcards = False; f.Forward = True; f.Wrap = 0
            if f.Execute():
                r = probe
        if r is not None:
            yield r, m.group(0)


def mark_amharic(rng) -> int:
    """Tag Amharic text in the range as Amharic and not checked by Word's (English) speller.
    English and other text keeps its language and spell check. Returns how many stretches changed."""
    n = 0
    for r, _ in list(_spans(rng, _RUN_RE)):
        mark_range_amharic(r)
        n += 1
    return n


def mark_range_amharic(rng) -> None:
    """For text Amharic Dictate itself wrote (all of it is dictated Amharic)."""
    try:
        rng.LanguageID = AMHARIC_LANG_ID
        rng.NoProofing = True
    except Exception:
        pass


def unknown_words(rng, ignore=()):
    """Amharic words in the range that the dictionary doesn't know: [(word, count, [suggestions])]."""
    from textproc import is_known_word, is_user_word, misspelling_fix, suggest
    counts = {}
    for w in _WORD_RE.findall(rng.Text or ""):
        counts[w] = counts.get(w, 0) + 1
    out = []
    for w, n in counts.items():
        if w in ignore or len(w) < 2 or is_known_word(w) or is_user_word(w):
            continue
        sugg = []
        fix = misspelling_fix(w)
        if fix and fix != w:
            sugg.append(fix)
        for s in suggest(w):
            if s != w and s not in sugg:
                sugg.append(s)
        out.append((w, n, sugg[:8]))
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


def _occurrences(rng, word):
    """Whole-word occurrences (not part of a longer Amharic word)."""
    rx = re.compile(r"(?<![\u1200-\u135A])" + re.escape(word) + r"(?![\u1200-\u135A])")
    return list(_spans(rng, rx))


def show_word(word_app, rng, text) -> bool:
    """Select the first place the word occurs so the person can see it in the document."""
    occ = _occurrences(rng, text)
    if occ:
        occ[0][0].Select()
        return True
    return False


def replace_all(rng, old, new) -> int:
    """Replace every whole-word occurrence of old with new inside the range. Returns how many."""
    occ = _occurrences(rng, old)
    for r, _ in reversed(occ):                      # from the end, so earlier positions stay valid
        r.Text = new
        mark_range_amharic(r)
    return len(occ)
