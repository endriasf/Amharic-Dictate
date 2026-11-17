"""Test Amharic spelling for Word in a hidden Word document (nothing of yours is opened or changed)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pythoncom, win32com.client
import wordspell

pythoncom.CoInitialize()
results = []
def check(name, cond):
    results.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, flush=True)

word = win32com.client.DispatchEx("Word.Application")
word.Visible = False
try:
    doc = word.Documents.Add()
    doc.Content.Text = "Hello world. ሰላም ኢትዮጰያ እንዴት ነህ። Good morning."
    doc.Content.LanguageID = 1033
    wordspell.mark_amharic(doc.Content)
    def lang_of(text):
        r = doc.Content.Duplicate
        f = r.Find; f.Text = text; f.MatchWildcards = False
        return (r.LanguageID, bool(r.NoProofing)) if f.Execute() else None   # Word gives -1 for True
    print("Amharic word:", lang_of("ሰላም"))
    check("Amharic word tagged Amharic, no proofing", lang_of("ሰላም") == (1118, True))
    check("English kept English with spell check on", lang_of("Hello") == (1033, False))
    check("English after Amharic still checked", lang_of("morning") == (1033, False))
    check("text unchanged", doc.Content.Text.rstrip("\r") == "Hello world. ሰላም ኢትዮጰያ እንዴት ነህ። Good morning.")
    items = wordspell.unknown_words(doc.Content)
    words = [w for w, _, _ in items]
    print("unknown:", items)
    check("unknown word found", "ኢትዮጰያ" in words and "ኢትዮጵያ" in dict((w, s) for w, _, s in items)["ኢትዮጰያ"])
    check("known words not listed", "ሰላም" not in words and "እንዴት" not in words)
    check("English not listed", not any(w.isascii() for w in words))
    n = wordspell.replace_all(doc.Content, "ኢትዮጰያ", "ኢትዮጵያ")
    check("change all replaced 1", n == 1)
    check("text fixed in document", doc.Content.Text.rstrip("\r") == "Hello world. ሰላም ኢትዮጵያ እንዴት ነህ። Good morning.")
    check("fixed word is tagged Amharic", lang_of("ኢትዮጵያ") == (1118, True))
    doc.Content.Text = "ኢትዮጰያ ኢትዮጰያ። ኢትዮጰያው\rSecond paragraph ኢትዮጰያ"
    n = wordspell.replace_all(doc.Content, "ኢትዮጰያ", "ኢትዮጵያ")
    check("whole words only, all occurrences", n == 3 and doc.Content.Text.rstrip("\r") == "ኢትዮጵያ ኢትዮጵያ። ኢትዮጰያው\rSecond paragraph ኢትዮጵያ")
    doc.Close(SaveChanges=0)
finally:
    word.Quit()
print(f"\n{sum(results)}/{len(results)} passed")
