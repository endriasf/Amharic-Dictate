"""Amharic Dictate colours: neutral dark windows with the logo's green as the accent."""

BG = "#1E2220"           # windows: neutral charcoal
FIELD = "#16191A"        # text areas, lists, entry fields, title strips
BTN = "#2B302E"          # buttons
BTN_HOVER = "#363D3A"
ACCENT = "#288C5A"       # the green: main action (Done), selected tab, ticks
ACCENT_HI = "#5CC08A"    # progress, level meter
BORDER = "#3A413E"
SELECT = "#2C5E45"       # selected text / list rows (muted green)
TEXT = "#F2F4F3"
MUTED = "#C2C9C5"        # secondary text
DIM = "#8B9490"          # hints
DANGER_BTN = "#5A2D2D"
DANGER = "#FF8A80"       # error text
WARNING = "#FFCC66"
SUCCESS = "#7EE0A8"
INFO = "#4FC3F7"
CHIP = "#2F3A35"         # suggestion chips


def apply(root):
    """Style all ttk widgets and classic Tk widgets for every window of the app."""
    from tkinter import ttk
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                lightcolor=BG, darkcolor=BG, troughcolor=FIELD, focuscolor=ACCENT_HI,
                selectbackground=SELECT, selectforeground=TEXT, insertcolor=TEXT)
    s.map(".", foreground=[("disabled", DIM)])
    s.configure("TButton", background=BTN, foreground=TEXT, bordercolor=BORDER, padding=(10, 4))
    s.map("TButton", background=[("disabled", BG), ("pressed", ACCENT), ("active", BTN_HOVER)],
          bordercolor=[("focus", ACCENT_HI)])
    s.configure("Accent.TButton", background=ACCENT)
    s.map("Accent.TButton", background=[("disabled", BG), ("active", ACCENT_HI)])
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, background=BG, foreground=TEXT, indicatorbackground=FIELD, indicatorforeground=TEXT)
        s.map(w, background=[("active", BG)], indicatorbackground=[("selected", ACCENT), ("pressed", BTN)])
    s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT)
    s.configure("TCombobox", fieldbackground=FIELD, background=BTN, foreground=TEXT, arrowcolor=TEXT)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
          selectbackground=[("readonly", FIELD)])
    s.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=TEXT, background=BTN)
    s.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    s.configure("TNotebook.Tab", background=FIELD, foreground=MUTED, padding=(12, 5), bordercolor=BORDER)
    s.map("TNotebook.Tab", background=[("selected", BTN)], foreground=[("selected", TEXT)],
          bordercolor=[("selected", ACCENT)])
    s.configure("TLabelframe", background=BG, bordercolor=BORDER)
    s.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    s.configure("Horizontal.TProgressbar", background=ACCENT_HI, troughcolor=FIELD, bordercolor=BORDER)
    s.configure("Horizontal.TScale", background=BTN, troughcolor=FIELD)
    s.configure("TScrollbar", background=BTN, troughcolor=FIELD, arrowcolor=TEXT, bordercolor=BORDER)
    s.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT)
    s.configure("TSeparator", background=BORDER)
    root.configure(bg=BG)
    for cls, opts in {"Toplevel": {"background": BG}, "Frame": {"background": BG},
                      "Label": {"background": BG, "foreground": TEXT},
                      "Listbox": {"background": FIELD, "foreground": TEXT, "selectBackground": SELECT,
                                  "selectForeground": TEXT, "highlightThickness": 0, "borderWidth": 0},
                      "Text": {"background": FIELD, "foreground": TEXT, "insertBackground": TEXT,
                               "selectBackground": SELECT},
                      "Entry": {"background": FIELD, "foreground": TEXT, "insertBackground": TEXT},
                      "Canvas": {"background": BG, "highlightThickness": 0},
                      "Menu": {"background": FIELD, "foreground": TEXT, "activeBackground": SELECT,
                               "activeForeground": TEXT}}.items():
        for k, v in opts.items():
            root.option_add(f"*{cls}.{k}", v)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)


def dark_title_bar(win):
    """Ask Windows 10/11 for a dark title bar on this window (ignored elsewhere)."""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):                      # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
    except Exception:
        pass
