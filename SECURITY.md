# Security

Amharic Dictate is built to keep what you say on your computer.

## How the app protects you
- **Offline:** the installed app never connects to the internet. The speech model is built in, and
  model libraries are forced into offline mode. The app opens no network ports.
- **Microphone:** opened only while you are dictating or recording a voice-profile sentence, and
  closed straight after.
- **Clipboard:** dictated text is marked so Windows keeps it out of clipboard history and cloud
  clipboard sync.
- **Your data:** settings, voice profiles, recordings and corrections stay in your own Windows user
  folder (`%APPDATA%\AmharicDictate`). Dictation history is off by default; learning from corrections
  is off until you turn it on. Uninstalling offers to delete all of it.
- **Safe model files:** models load from `safetensors` files (data only, no code). Voice-profile
  add-ons load with PyTorch's restricted `weights_only` mode, and imported profiles accept only the
  app's own file types, with size limits and path checks.
- **Build checks:** every installer build checks the bundled libraries for known vulnerabilities
  (pip-audit) and publishes a SHA-256 checksum, so you can verify your download.

## Verify your download
In PowerShell: `Get-FileHash .\AmharicDictate-Setup-<version>.exe -Algorithm SHA256`
and compare with `SHA256SUMS.txt` on the release page.

## Reporting a problem
Please report security issues privately through GitHub: the repository's **Security** tab →
**Report a vulnerability**. Please don't open a public issue for security problems.

Maintainer: Endrias F. Abitte
