"""Turn an error into a plain explanation of what went wrong and what to do about it.
The full technical details still go to the log for support; people see only the explanation."""
import errno


def _text(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}".lower()


def explain(e: BaseException, doing: str = "") -> tuple:
    """(what happened, what to do) for an error that happened while `doing` ("dictating",
    "loading", "hotkey", "word", "recording")."""
    t = _text(e)
    name = type(e).__name__

    # ---- microphone
    if name in ("NoMicrophone",):
        return "Can't use the microphone", str(e)
    if "portaudio" in t or "sounddevice" in t or "querying device" in t or "invalid device" in t:
        if "-9996" in t or "querying device -1" in t or "invalid device" in t:
            return ("No microphone found", "Plug in or enable a microphone or headset (Settings → System → Sound → "
                    "Input). On a remote desktop, turn on microphone redirection.")
        if "-9985" in t or "unavailable" in t or "busy" in t or "-9999" in t:
            return ("The microphone is busy", "Another program may be using it exclusively. Close apps like "
                    "Teams or Zoom calls, or turn off \"Allow applications to take exclusive control\" in the "
                    "microphone's properties (Control Panel → Sound → Recording).")
        return ("Can't use the microphone", "Check that it's enabled in Settings → System → Sound → Input, and that "
                "Settings → Privacy & security → Microphone → \"Let desktop apps access your microphone\" is on.")

    # ---- memory and disk
    if isinstance(e, MemoryError) or "out of memory" in t or "can't allocate memory" in t or "not enough memory" in t \
            or "defaultcpuallocator" in t:
        return ("This computer ran out of memory", "Close some programs (especially browsers with many tabs) and try "
                "again. Amharic Dictate needs about 3 GB of free memory.")
    if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOSPC or "no space left" in t \
            or "disk is full" in t or "not enough space" in t:
        return ("The disk is full", "Free some space on drive C: (empty the Recycle Bin, delete old downloads), then "
                "try again.")
    if isinstance(e, PermissionError) or "access is denied" in t or "permission denied" in t:
        return ("Windows blocked access to a file", "Antivirus or folder permissions may be blocking Amharic "
                "Dictate's settings folder. Restart the app; if it keeps happening, allow Amharic Dictate in your "
                "antivirus.")

    # ---- the speech model
    if doing == "loading":
        if "safetensors" in t or "no such file" in t or "not found" in t or "corrupt" in t or "unexpected eof" in t \
                or "config.json" in t or "incomplete" in t:
            return ("The speech model files are missing or damaged", "Reinstall Amharic Dictate (your voice "
                    "profiles and settings are kept).")
        return ("The speech model couldn't start", "Restart Amharic Dictate. If it keeps happening, restart the "
                "computer, then reinstall the app if needed (your profiles are kept).")

    # ---- keyboard shortcut
    if doing == "hotkey" or "hotkey" in t or "keyboard" in t:
        return ("That keyboard shortcut can't be used", "It may be invalid or taken by another program. Open "
                "Settings and choose a different shortcut, for example Ctrl + Alt + D.")

    # ---- Word, clipboard, typing
    if "com_error" in t or "pywintypes" in t or "rpc server" in t or "call was rejected" in t:
        return ("Couldn't reach Microsoft Word", "Word may be busy or showing a dialog box. Close any open dialog in "
                "Word and try again — your text is kept in the dictation box.")
    if "clipboard" in t or "pyperclip" in t or "openclipboard" in t:
        return ("Another program is holding the clipboard", "Try again in a moment. Your text is kept in the "
                "dictation box: you can also use ⧉ Copy.")

    return ("Something went wrong", "Try again. If it keeps happening, restart Amharic Dictate. (For support, the "
            "details are in the tray menu → Troubleshooting → Open technical log.)")
