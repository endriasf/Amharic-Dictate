# Amharic Dictate v1.0 — offline Amharic dictation for Windows

Press a hotkey, speak Amharic, and the text appears in whatever you're working in:
Word, Outlook, Teams, a browser, any text box. Speech is processed **on the PC**; after the
one-time model download, no internet is needed.

## For users (installer)
1. Run `AmharicDictate-Setup-1.0.0.exe` (no admin rights needed).
2. On first launch, the speech model downloads once (0.5–2.5 GB). A green mic icon appears in the tray.
3. Click into any text box, press **Ctrl+Alt+Space**, speak, then press it again.

| Say | You get |
|---|---|
| አራት ነጥብ | ። |
| ነጠላ ሰረዝ | ፣ |
| ድርብ ሰረዝ | ፤ |
| የጥያቄ ምልክት | ? |
| ቃለ አጋኖ | ! |
| አዲስ መስመር | new line |
| አዲስ አንቀጽ | new paragraph |
| ሁለት መቶ ሀምሳ | 250 (number words become digits; a lone small number like "አንድ ሰው" stays as words) |

Tray icon → **Settings** for: push-to-talk, hotkey, type-as-you-speak, model, start with Windows.
Icon colors: grey = loading, green = ready, red = listening.

## For developers
```
setup.bat          one-time: creates .venv, installs CPU PyTorch + requirements
start.bat          run from source
build\build.ps1    build dist\AmharicDictate\ and the installer (needs Inno Setup 6)
```
**Build in the cloud:** push this folder to GitHub → Actions → *Build Windows installer* →
*Run workflow*. Download the installer from the run's artifacts. Push a tag such as `v1.0.0`
to publish it as a GitHub Release.

| File | Purpose |
|---|---|
| `app.py` | tray, overlay, hotkeys, paste |
| `engine.py` | model loading, voice detection, live transcription |
| `textproc.py` | punctuation commands, numbers, clean-up |
| `settings_ui.py` / `config.py` | settings window, `%APPDATA%\AmharicDictate\config.json` |
| `tools/amharic_asr_benchmark.py` | compare models on your recordings |
| `tools/train_amharic_ctc.py` | train your own model (see `tools/README_TRAINING.md`) |

## Known limits
- Can't paste into apps running as Administrator unless Amharic Dictate also runs elevated.
- No automatic punctuation model yet; use the spoken commands or the "add ። after each phrase" option.
- The default Ethio-ASR models are **CC-BY-NC 4.0 (non-commercial)**. Before charging for the app,
  switch to your own trained model (tools/) or another commercially licensed model.
- Installer size is ~300–400 MB because it bundles PyTorch.

## Amharic dictionary
`amharic_words.tsv` (109,769 words with frequencies) powers suggestions and sound-alike spelling fixes.
Sources: Leipzig Corpora Collection, amh_wikipedia_2016_30K and amh_wikipedia_2021_30K (CC BY 4.0;
D. Goldhahn, T. Eckart & U. Quasthoff, LREC 2012), and the GNU Aspell Amharic word list by Daniel Yacob /
Ge'ez Frontier Foundation (public domain). Keep this attribution when distributing the app.
