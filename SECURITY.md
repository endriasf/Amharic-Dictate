# Security

Amharic Dictate is built to keep what you say on your computer.

## How the app protects you
- **Offline:** dictation never uses the internet. The speech model is built in, and model libraries
  are forced into offline mode. The app opens no network ports.
- **Update check (can be turned off):** the only connection the app makes is, at most once a day, an
  HTTPS request to the GitHub API for this project's latest release number
  (`api.github.com/repos/endriasf/Amharic-Dictate/releases/latest`). No voice, text, profile or
  identifying data is sent. The app never downloads or runs an update by itself; it only opens the
  project's own releases page when you choose **Download update…**.
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

