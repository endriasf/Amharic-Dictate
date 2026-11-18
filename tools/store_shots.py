"""Capture real screenshots of the app's windows for the Microsoft Store listing.
Opens the windows in test mode (no microphone, no model), photographs each one, saves PNGs to
store_shots/. Run with:  python tools/store_shots.py"""
import ctypes, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)        # real pixels, sharp captures
except Exception:
    pass
from PIL import ImageGrab
import app as A

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "store_shots")
os.makedirs(out, exist_ok=True)


def grab(win, name, settle=0.6):
    win.update(); time.sleep(settle); win.update()
    import ctypes.wintypes as wt
    r = wt.RECT()
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r))  # frame incl. title bar
    if r.right - r.left < 50:
        r.left, r.top = win.winfo_rootx(), win.winfo_rooty()
        r.right, r.bottom = r.left + win.winfo_width(), r.top + win.winfo_height()
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(os.path.join(out, name))
    print("saved", name)


app = A.App(ui_test=True)
root = app.root
# 1. start-up window
app._splash_profile.config(text="Voice profile: Andro  ✓ loaded")
app._splash_message("Step 3 of 4 — Loading the AI model and Andro's voice profile… (the longest step)")
for _ in range(15):                      # let the sound wave move
    root.update(); time.sleep(0.05)
grab(app._splash, "1_startup.png", 0.3)
app._close_splash(); root.update()
# 2. dictation box while dictating
app.active = True
app._show("● Listening… speak Amharic",
          "ዛሬ ስብሰባው በሰዓቱ ተጀምሮ ጥሩ ውይይት ተደርጓል። የሚቀጥለው ስብሰባ ሐሙስ ከጠዋቱ ሦስት ሰዓት ይሆናል።")
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.update(); root.geometry(f"+{(sw - root.winfo_width()) // 2}+{sh // 3}")
grab(root, "2_dictation.png")
app.active = False; root.withdraw()
# 3. settings
app.open_settings(); grab(app._settings_win, "3_settings.png", 0.8); app._settings_win.destroy()
# 4. voice profiles
app.open_training(); grab(app._train_win.win, "4_voice_profiles.png", 0.8); app._train_win.win.destroy()
root.destroy()
print("done:", out)
