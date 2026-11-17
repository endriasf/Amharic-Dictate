"""'Check Amharic spelling in Word' window: find, review and fix Amharic words in the open Word document."""

import tkinter as tk
from tkinter import ttk

import wordspell
from config import log_error


class SpellWindow:
    def __init__(self, app):
        self.app = app
        self.word = self.doc = self.rng = None
        self.items = []
        self.ignored = set()
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        w = self.win = tk.Toplevel(app.root)
        w.title("Amharic spelling — Microsoft Word")
        w.attributes("-topmost", True)
        w.geometry("640x430")
        family = app.text.cget("font").split(" ")[0].strip("{}") or "Ebrima"

        top = ttk.Frame(w, padding=(10, 8)); top.pack(fill="x")
        self.info = ttk.Label(top, text="", wraplength=600)
        self.info.pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Check again", command=self.scan).pack(side="right")

        body = ttk.Frame(w, padding=(10, 0)); body.pack(fill="both", expand=True)
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Not in the dictionary:").pack(anchor="w")
        self.lst = tk.Listbox(left, font=(family, 13), exportselection=False)
        self.lst.pack(fill="both", expand=True, pady=(2, 0))
        self.lst.bind("<<ListboxSelect>>", lambda e: self.on_pick())

        right = ttk.Frame(body, padding=(10, 0)); right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Suggestions:").pack(anchor="w")
        self.sug = tk.Listbox(right, font=(family, 13), height=6, exportselection=False)
        self.sug.pack(fill="x", pady=(2, 6))
        self.sug.bind("<Double-Button-1>", lambda e: self.change())
        ttk.Label(right, text="Change to:").pack(anchor="w")
        self.new = tk.Entry(right, font=(family, 13))
        self.new.pack(fill="x", pady=(2, 6))
        self.sug.bind("<<ListboxSelect>>", lambda e: self._use_suggestion())
        b = ttk.Frame(right); b.pack(fill="x")
        ttk.Button(b, text="Change all", command=self.change).pack(side="left")
        ttk.Button(b, text="Ignore", command=self.ignore).pack(side="left", padx=4)
        ttk.Button(b, text="★ Add to My words", command=self.add_word).pack(side="left")

        bottom = ttk.Frame(w, padding=10); bottom.pack(fill="x")
        ttk.Button(bottom, text="Remove Word's red lines from Amharic text",
                   command=self.mark).pack(side="left")
        self.status = ttk.Label(bottom, text="", foreground="#2a7")
        self.status.pack(side="left", padx=10)
        self.scan()

    # ------------------------------------------------------------------
    def _connect(self) -> bool:
        try:
            self.word, self.doc = wordspell.connect()
            self.rng, selected = wordspell.target_range(self.word, self.doc)
            self.scope = "the selected text" if selected else "the whole document"
            return True
        except Exception as e:
            self.info.config(text="Open a document in Microsoft Word first, then click Check again.")
            log_error(f"Word spelling: {e}")
            return False

    def scan(self):
        self.lst.delete(0, "end"); self.sug.delete(0, "end"); self.new.delete(0, "end")
        if not self._connect():
            return
        try:
            self.items = wordspell.unknown_words(self.rng, self.ignored)
        except Exception as e:
            self.info.config(text=f"Couldn't read the document: {e}")
            return
        for w, n, _ in self.items:
            self.lst.insert("end", f"{w}   ×{n}" if n > 1 else w)
        name = self.doc.Name
        self.info.config(text=(f"{len(self.items)} Amharic words to review in {self.scope} of “{name}”."
                               if self.items else f"No unknown Amharic words in {self.scope} of “{name}”."))
        if self.items:
            self.lst.selection_set(0)
            self.on_pick()

    def _current(self):
        sel = self.lst.curselection()
        return self.items[sel[0]] if sel else None

    def on_pick(self):
        item = self._current()
        self.sug.delete(0, "end"); self.new.delete(0, "end")
        if not item:
            return
        word, _, sugg = item
        for s in sugg:
            self.sug.insert("end", s)
        if sugg:
            self.sug.selection_set(0)
            self.new.insert(0, sugg[0])
        try:
            wordspell.show_word(self.word, self.rng, word)       # highlight it in Word
        except Exception:
            pass

    def _use_suggestion(self):
        sel = self.sug.curselection()
        if sel:
            self.new.delete(0, "end")
            self.new.insert(0, self.sug.get(sel[0]))

    def _remove_current(self):
        sel = self.lst.curselection()
        if not sel:
            return
        i = sel[0]
        self.items.pop(i)
        self.lst.delete(i)
        if self.items:
            self.lst.selection_set(min(i, len(self.items) - 1))
            self.on_pick()
        else:
            self.sug.delete(0, "end"); self.new.delete(0, "end")
            self.info.config(text="All done.")

    def change(self):
        item = self._current()
        new = " ".join(self.new.get().split())
        if not item or not new:
            return
        try:
            n = wordspell.replace_all(self.rng, item[0], new)
            self.status.config(text=f"Changed {n}× “{item[0]}” → “{new}”")
        except Exception as e:
            self.status.config(text=f"Couldn't change it: {e}", foreground="#a33")
            return
        self._remove_current()

    def ignore(self):
        item = self._current()
        if item:
            self.ignored.add(item[0])
            self._remove_current()

    def add_word(self):
        item = self._current()
        if not item or not self.app.cfg.get("profile"):
            return
        import voiceprofile as vp
        vp.add_my_word(self.app.cfg["profile"], item[0])
        self.app.apply_my_words()
        self.status.config(text=f"Added “{item[0]}” to My words")
        self._remove_current()

    def mark(self):
        if not self._connect():
            return
        try:
            wordspell.mark_amharic(self.rng)
            self.status.config(text=f"Word no longer marks Amharic words in {self.scope} as misspelled.")
        except Exception as e:
            self.status.config(text=f"Couldn't update the document: {e}", foreground="#a33")
