# Builds dist\AmharicDictate\ (PyInstaller) and, if Inno Setup is installed,
# build\Output\AmharicDictate-Setup-<version>.exe
# Run from the repo root:   powershell -ExecutionPolicy Bypass -File build\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path config.py -Pattern 'APP_VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building AmharicDictate $version"

python -m pip install --upgrade pip setuptools pyinstaller
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt

# Speech model shipped inside the app (set MODEL_SOURCE to a Hugging Face model id or a local folder)
$modelArgs = @()
if ($env:MODEL_SOURCE) {
  Write-Host "Bundling speech model: $env:MODEL_SOURCE"
  python tools\prepare_bundled_model.py --source $env:MODEL_SOURCE --out build\model
  if ($LASTEXITCODE -ne 0) { throw "Preparing the bundled model failed" }
  $modelArgs = @("--add-data", "build\model;model")
} else {
  Write-Host "No MODEL_SOURCE set: the app will download its model on first launch"
}

$meta = "transformers","tokenizers","huggingface-hub","safetensors","regex","requests","httpx",
        "packaging","filelock","numpy","tqdm","pyyaml","torch"
# only packages that are actually installed (library versions change which ones are needed)
$meta = $meta | Where-Object { python -c "import importlib.metadata as m; m.distribution('$_')" 2>$null; $LASTEXITCODE -eq 0 }
$metaArgs = $meta | ForEach-Object { "--copy-metadata"; $_ }

pyinstaller --noconfirm --clean --windowed `
  --name AmharicDictate `
  --icon assets\icon.ico `
  --collect-submodules transformers `
  --collect-data transformers `
  --hidden-import pystray._win32 `
  --add-data "amharic_words.tsv;." `
  --add-data "training_sentences.txt;." `
  --hidden-import voiceprofile --hidden-import voice_training --hidden-import train_local `
  --hidden-import learning --hidden-import lmdecode --hidden-import wordsync --hidden-import wordspell --hidden-import spell_window `
  --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes `
  --exclude-module torchvision --exclude-module torchaudio `
  --exclude-module tensorflow --exclude-module jax --exclude-module flax `
  @metaArgs @modelArgs `
  app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Smoke test the frozen app
$report = Join-Path $env:TEMP "amharicdictate-selftest.txt"
$p = Start-Process -FilePath dist\AmharicDictate\AmharicDictate.exe -ArgumentList "--selftest", $report -Wait -PassThru
Get-Content $report
if ($p.ExitCode -ne 0) { throw "Self-test failed" }

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
  & $iscc "/DAppVersion=$version" build\installer.iss
  Write-Host "Installer: build\Output\AmharicDictate-Setup-$version.exe"
} else {
  Write-Host "Inno Setup not found; skipping installer. App folder: dist\AmharicDictate"
}
