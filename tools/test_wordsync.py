"""Test the live Word link with a hidden Word document (nothing of yours is opened or changed)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pythoncom, win32com.client
from wordsync import WordSync

pythoncom.CoInitialize()
word = win32com.client.DispatchEx("Word.Application")        # separate hidden Word, closed at the end
word.Visible = False
doc = word.Documents.Add()
doc.Content.Text = "Before text."
doc.Activate()
word.Selection.SetRange(doc.Content.End - 1, doc.Content.End - 1)   # cursor at the end, like a real start
edits = []
results = []
def check(name, cond):
    results.append(cond); print(("PASS " if cond else "FAIL ") + name, flush=True)
def body():
    return doc.Content.Text.rstrip("\r")
# the link runs on its own thread: give it the document through a marshalled stream
stream = pythoncom.CoMarshalInterThreadInterfaceInStream(pythoncom.IID_IDispatch, doc._oleobj_)
class Doc:   # unmarshal inside the link's thread on first use
    def __init__(self, stream): self.stream, self.obj = stream, None
    def __getattr__(self, name):
        if self.obj is None:
            self.obj = win32com.client.Dispatch(pythoncom.CoGetInterfaceAndReleaseStream(self.stream, pythoncom.IID_IDispatch))
        return getattr(self.obj, name)
link = WordSync(lambda t: edits.append(t), print, document=Doc(stream))
check("connects to Word", link.start())
link.update("ሰላም"); time.sleep(1.0)
check("first phrase appears", body() == "Before text. ሰላም")
link.update("ሰላም እንዴት ነህ።"); time.sleep(1.0)
check("next phrase appended", body() == "Before text. ሰላም እንዴት ነህ።")
link.update("ሰላም እንዴት ነሽ።"); time.sleep(1.0)
check("correction changes only that word", body() == "Before text. ሰላም እንዴት ነሽ።")
doc.Range(0, 0).InsertBefore("Title\r")                  # person types above the dictated text
link.update("ሰላም እንዴት ነሽ። ደህና ነኝ"); time.sleep(1.0)
check("typing elsewhere is kept", body() == "Title\rBefore text. ሰላም እንዴት ነሽ። ደህና ነኝ")
r = doc.Content.Find
ok = r.Execute("ደህና", False, False, False, False, False, True, 1, False, "በጣም ደህና", 1)   # person edits dictated text in Word
time.sleep(1.5)
check("edit in Word reaches the box", bool(edits) and edits[-1] == "ሰላም እንዴት ነሽ። በጣም ደህና ነኝ")
link.update("ሰላም እንዴት ነሽ። በጣም ደህና ነኝ። አመሰግናለሁ"); time.sleep(1.0)
check("dictating after a Word edit keeps the edit", body() == "Title\rBefore text. ሰላም እንዴት ነሽ። በጣም ደህና ነኝ። አመሰግናለሁ")
sel = word.Selection
check("Word's cursor follows the dictation", sel.Start == len(body()))
check("cursor at passage: not away", link.cursor_away is False)
sel.SetRange(0, 0)                                          # person clicks at the top of the document
time.sleep(1.0)
check("click elsewhere is noticed", link.cursor_away is True)
link.hold(True); link.update(""); moved = link.new_passage(); link.hold(False)
check("new passage starts at the click", moved)
link.update("አዲስ"); time.sleep(1.0)
check("next words go to the new spot, old passage kept",
      body() == "አዲስ Title\rBefore text. ሰላም እንዴት ነሽ። በጣም ደህና ነኝ። አመሰግናለሁ")
link.update("አዲስ ርዕስ"); time.sleep(1.0)
check("new passage keeps growing there", body().startswith("አዲስ ርዕስ Title\r"))
final = link.finish("አዲስ ርዕስ")
check("finish returns Word's text", final == "አዲስ ርዕስ")
link2_stream = pythoncom.CoMarshalInterThreadInterfaceInStream(pythoncom.IID_IDispatch, doc._oleobj_)
link2 = WordSync(lambda t: None, print, document=Doc(link2_stream)); link2.start()
link2.update("ይህ ይሰረዛል"); time.sleep(1.0); link2.cancel()
check("cancel removes dictated text", body() == "አዲስ ርዕስ Title\rBefore text. ሰላም እንዴት ነሽ። በጣም ደህና ነኝ። አመሰግናለሁ")
print("ALL PASSED" if all(results) else "SOME FAILED")
doc.Close(False)
if word.Documents.Count == 0 and not word.Visible:    # only quit the hidden Word this test started
    word.Quit()
