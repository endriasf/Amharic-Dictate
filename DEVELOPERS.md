# Amharic Dictate — developer guide

MIT licence (see LICENSE).

## Run from source (Windows)
```
setup.bat     one time: creates .venv, installs CPU PyTorch and requirements.txt
start.bat     start the app
restart.bat   stop and start it again
```
When run from source, the app downloads a speech model from Hugging Face on first launch
(by default Ethio-ASR, which is licensed for non-commercial use only). Released installers use the
built-in *Amharic Speech-to-Text EFA* model instead.

## Build the installer (GitHub Actions)
1. Open the repository's **Actions** tab → **Build Windows installer** → **Run workflow**.
2. In **model_source**, enter the Hugging Face ID of the speech model to package inside the app
   (for example `Abittee/amharic-speech-to-text-efa-v1`). Leave it empty to build an app that
   downloads its model on first launch.
3. When the run finishes, download **AmharicDictate-Setup** from the run's *Artifacts*.
4. To publish a GitHub Release, push a version tag, for example `git tag v2.3.0 && git push --tags`.

The build (`build/build.ps1`) runs PyInstaller, self-tests the app, prepares the built-in model at
half precision with author metadata (`tools/prepare_bundled_model.py`), and builds the installer
with Inno Setup (`build/installer.iss`). To build locally, install Inno Setup 6 and run
`powershell -ExecutionPolicy Bypass -File build\build.ps1` (set `MODEL_SOURCE` to bundle a model).

## Code layout
| File | Purpose |
|---|---|
| `app.py` | Tray icon, dictation box, buttons, hotkeys, pasting, About |
| `engine.py` | Model loading, voice detection, live and final transcription, editing state |
| `lmdecode.py` | Dictionary-guided decoding, volume levelling |
| `textproc.py` | Voice commands, numbers, dictionary, spell-check, suggestions, My words |
| `voiceprofile.py` | Voice profiles and the per-person LoRA add-on |
| `voice_training.py` | Voice profiles window (setup reading, training, My words, learning) |
| `train_local.py` | Trains a voice profile on the user's PC |
| `learning.py` | Learning from corrections |
| `settings_ui.py`, `config.py` | Settings window and `%APPDATA%\AmharicDictate\config.json` |
| `tools/train_amharic_ctc.py` | Trains a full speech model (see `cloud/README_CLOUD.md`) |
| `tools/amharic_asr_benchmark.py` | Compares models on recordings |

## Train a speech model on a cloud GPU
See [cloud/README_CLOUD.md](cloud/README_CLOUD.md). The model card template for publishing is
`cloud/MODEL_CARD_TEMPLATE.md`.

## Known limits
- Text can't be typed into programs running as Administrator unless Amharic Dictate also runs
  elevated.
- No automatic punctuation yet: use voice commands or the punctuation buttons.

## User guide
The app's offline guide (tray → How to use…, Start menu → Amharic Dictate guide) is `assets/guide.html`, built from the user part of README.md. After editing README.md run `python tools/make_guide.py` (needs `pip install markdown`) and commit both files.
