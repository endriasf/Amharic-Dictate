"""
Live dictation into Microsoft Word, kept in sync both ways.

The text being dictated lives in one stretch ("range") of the Word document, starting at the cursor:
- each change in the dictation box (new phrases, corrections, undo) is applied to that range, editing
  only the characters that changed, so anything typed elsewhere in the document is untouched;
- if the person edits the dictated text directly in Word, that is noticed and the dictation box
  is updated to match, so Word is never overwritten.

Uses Word's own automation interface (COM) on this computer only. All Word calls run on one
background thread, as COM requires.
"""

import queue
import threading
import time

WORD_WINDOW_CLASS = "OpusApp"          # Word's main window


def word_is_in_front() -> bool:
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, buf, 64)
        return buf.value == WORD_WINDOW_CLASS
    except Exception:
        return False


def _to_word(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r")


def _from_word(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n")


class WordSync:
    POLL_S = 0.4

    def __init__(self, on_user_edit, log=None, document=None):
        self.on_user_edit = on_user_edit       # called with the text after the person edited it in Word
        self.log = log or (lambda m: None)
        self._doc_override = document          # for tests
        self._jobs = queue.Queue()
        self._ready = threading.Event()
        self.ok = False
        self.error = ""
        self._away = False
        self._hold = False                     # while switching to a new spot: ignore box updates
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ---------------- called from the app
    def start(self, timeout=5.0) -> bool:
        self._thread.start()
        self._ready.wait(timeout)
        return self.ok

    def update(self, text: str):
        """The dictation box changed: make Word show the same text (latest request wins)."""
        if self.ok and not self._hold:
            self._jobs.put(("sync", text))

    def hold(self, on: bool):
        self._hold = on

    @property
    def cursor_away(self) -> bool:
        """The person clicked or typed somewhere else in Word since the last dictated words."""
        return self._away

    def new_passage(self, timeout=3.0) -> bool:
        """Continue dictating at Word's current cursor; the previous passage stays as normal text."""
        if not self.ok:
            return False
        done = queue.Queue()
        self._jobs.put(("move", done))
        try:
            return done.get(timeout=timeout)
        except queue.Empty:
            return False

    def finish(self, text: str, timeout=5.0) -> str:
        """Final sync; returns the text as it stands in Word (including the person's own edits)."""
        if not self.ok:
            return text
        done = queue.Queue()
        self._jobs.put(("finish", text, done))
        try:
            return done.get(timeout=timeout)
        except queue.Empty:
            return text

    def cancel(self, timeout=5.0):
        """Dictation cancelled: remove the dictated text from the document."""
        if not self.ok:
            return
        done = queue.Queue()
        self._jobs.put(("cancel", done))
        try:
            done.get(timeout=timeout)
        except queue.Empty:
            pass

    # ---------------- Word thread
    def _run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception as e:
            self.error = f"Word link unavailable ({e})"
            self._ready.set()
            return
        try:
            if self._doc_override is not None:
                self.doc = self._doc_override
                self.app = self.doc.Application
                pos = self.doc.Content.End - 1
            else:
                import win32com.client
                self.app = win32com.client.GetActiveObject("Word.Application")
                self.doc = self.app.ActiveDocument
                pos = self.app.Selection.End         # never overwrite selected text: dictate after it
            self._begin_at(pos)
            self.ok = True
        except Exception as e:
            self.error = f"Couldn't connect to Word ({e})"
            self.ok = False
        self._ready.set()
        if not self.ok:
            return
        try:
            self._loop()
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _begin_at(self, pos: int):
        prev = self.doc.Range(pos - 1, pos).Text if pos > 0 else ""
        self.lead = " " if prev and prev not in " \r\n\t\x0b(«" else ""
        nxt = self.doc.Range(pos, pos + 1).Text if pos < self.doc.Content.End - 1 else ""
        self.trail = " " if nxt and nxt not in " \r\n\t\x0b.,።፣፤፥?!)»" else ""   # dictating in front of a word
        self.rng = self.doc.Range(pos, pos)
        self.shown = ""                             # what we last put in Word (in Word form)
        self._away = False

    def _check_cursor(self):
        """Is Word's cursor still at our passage? (Clicking inside the passage counts as staying.)"""
        try:
            sel = self.app.Selection
            same_doc = sel.Document.FullName == self.doc.FullName
            inside = self.rng.Start <= sel.Start and sel.End <= self.rng.End
            self._away = not (same_doc and inside)
        except Exception as e:
            self.log(f"Word cursor check: {e}")

    def _cursor_to_end(self):
        """Keep Word's cursor right after the dictated words, as if they had been typed."""
        try:
            if not self._away and self.app.Selection.Document.FullName == self.doc.FullName:
                self.app.Selection.SetRange(self.rng.End, self.rng.End)
        except Exception as e:
            self.log(f"Word cursor: {e}")

    def _word_text(self, text: str) -> str:
        return (self.lead + _to_word(text) + self.trail) if text else ""

    def _current(self) -> str:
        return self.rng.Text or ""

    def _box_text(self, word_text: str) -> str:
        t = _from_word(word_text)
        if self.lead and t.startswith(self.lead):
            t = t[len(self.lead):]
        return t.strip(" ")

    def _loop(self):
        while True:
            try:
                job = self._jobs.get(timeout=self.POLL_S)
            except queue.Empty:
                job = None
            if job is not None:
                pending = [job]                     # coalesce: only the newest text matters
                while True:
                    try:
                        pending.append(self._jobs.get_nowait())
                    except queue.Empty:
                        break
                final = [j for j in pending if j[0] in ("finish", "cancel")]
                moves = [j for j in pending if j[0] == "move"]
                syncs = [j for j in pending if j[0] == "sync"]
                try:
                    if moves:                       # new passage at the cursor (any older syncs are stale)
                        sel = self.app.Selection
                        self.doc = sel.Document
                        self._begin_at(sel.End)
                        for j in moves:
                            j[1].put(True)
                        syncs = [j for j in syncs if pending.index(j) > pending.index(moves[-1])]
                    if syncs:
                        self._apply(syncs[-1][1])
                    if final:
                        j = final[0]
                        if j[0] == "finish":
                            self._apply(j[1])
                            j[2].put(self._box_text(self._current()))
                        else:
                            self.rng.Text = ""
                            j[1].put(True)
                        return
                except Exception as e:
                    self.log(f"Word sync: {e}")
                    for j in final:
                        j[-1].put(j[1] if j[0] == "finish" else True)
                    if final:
                        return
                continue
            # no request: did the person edit the dictated text in Word, or move the cursor away?
            self._check_cursor()
            try:
                cur = self._current()
                if cur != self.shown:
                    self.shown = cur
                    self.on_user_edit(self._box_text(cur))
            except Exception as e:
                self.log(f"Word sync check: {e}")
                return                              # document closed: stop syncing

    def _apply(self, text: str):
        new = self._word_text(text)
        cur = self._current()
        if cur != self.shown:                       # edited in Word since our last change: Word wins
            self.shown = cur
            self.on_user_edit(self._box_text(cur))
            return
        if new == cur:
            return
        # change only what differs (keeps the person's cursor and formatting elsewhere)
        p = 0
        while p < min(len(cur), len(new)) and cur[p] == new[p]:
            p += 1
        s = 0
        while s < min(len(cur), len(new)) - p and cur[len(cur) - 1 - s] == new[len(new) - 1 - s]:
            s += 1
        start = self.rng.Start
        part = self.doc.Range(start + p, start + len(cur) - s)
        self._check_cursor()                       # where is the person's cursor before we type?
        part.Text = new[p:len(new) - s]
        self.rng = self.doc.Range(start, start + len(new))
        self.shown = self._current()
        try:                                       # Amharic: keep Word's English speller off it
            from wordspell import mark_range_amharic
            mark_range_amharic(self.rng)
        except Exception:
            pass
        self._cursor_to_end()
