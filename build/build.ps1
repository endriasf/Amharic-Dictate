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
  --add-data "assets\guide.html;assets" `
  --add-data "assets\logo_256.png;assets" `
  --add-data "assets\tray_*.png;assets" `
  --add-data "assets\wordmark_dark.png;assets" `
  --add-data "assets\mark_128.png;assets" `
  --add-data "assets\mark_light_128.png;assets" `
  --add-data "assets\wordmark_light.png;assets" `
  --hidden-import voiceprofile --hidden-import voice_training --hidden-import train_local `
  --hidden-import learning --hidden-import lmdecode --hidden-import wordsync --hidden-import cmdspot --hidden-import theme --hidden-import updater --hidden-import diagnose `
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
  $sizeMB = [int]((Get-ChildItem dist\AmharicDictate -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
  & $iscc "/DAppVersion=$version" "/DAppSizeMB=$sizeMB" build\installer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (needs version 6.7 or newer)" }
  Write-Host "Installer: build\Output\AmharicDictate-Setup-$version.exe"
} else {
  Write-Host "Inno Setup not found; skipping installer. App folder: dist\AmharicDictate"
}

# ---- Microsoft Store package (MSIX). Built only when the Store identity is set (Actions variables
# STORE_IDENTITY_NAME, STORE_PUBLISHER, STORE_PUBLISHER_NAME from Partner Center -> Product identity).
# Left unsigned on purpose: the Store signs it after certification.
if ($env:STORE_IDENTITY_NAME -and $env:STORE_PUBLISHER -and $env:STORE_PUBLISHER_NAME) {
  $pkg = "build\msix\pkg"
  if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
  New-Item -ItemType Directory -Force $pkg | Out-Null
  Copy-Item dist\AmharicDictate\* $pkg -Recurse
  Copy-Item build\msix\Assets $pkg -Recurse
  Copy-Item assets\guide.html "$pkg\Amharic Dictate guide.html"
  Copy-Item build\installer_license.txt "$pkg\LICENCES.txt"
  $manifest = (Get-Content build\msix\AppxManifest.xml -Raw -Encoding UTF8).
    Replace("{{IDENTITY_NAME}}", $env:STORE_IDENTITY_NAME).
    Replace("{{PUBLISHER}}", [System.Security.SecurityElement]::Escape($env:STORE_PUBLISHER)).
    Replace("{{PUBLISHER_NAME}}", [System.Security.SecurityElement]::Escape($env:STORE_PUBLISHER_NAME)).
    Replace("{{VERSION}}", "$version.0")
  Set-Content "$pkg\AppxManifest.xml" $manifest -Encoding UTF8
  $makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" |
              Sort-Object FullName -Descending | Select-Object -First 1
  if (-not $makeappx) { throw "makeappx.exe (Windows SDK) not found" }
  New-Item -ItemType Directory -Force build\Output | Out-Null
  & $makeappx.FullName pack /o /d $pkg /p "build\Output\AmharicDictate-$version.msix"
  if ($LASTEXITCODE -ne 0) { throw "MSIX packaging failed" }
  Write-Host "Store package: build\Output\AmharicDictate-$version.msix"
} else {
  Write-Host "Store identity not set; skipping the Microsoft Store package."
}
