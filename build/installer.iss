; Inno Setup script (saved as UTF-8 with BOM so the Amharic tips compile correctly) — per-user install, no admin rights needed. Needs Inno Setup 6.7 or newer
; (dark style with a background image). Art: build/art (tools/make_installer_art.py, tools/make_logo.py).
#if Ver < EncodeVer(6, 7, 0)
  #error Inno Setup 6.7 or newer is required for this installer's design.
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppSizeMB
  #define AppSizeMB "1300"
#endif

[Setup]
AppId={{C0199516-7A55-464A-A36C-54B31DE0B193}
AppName=Amharic Dictate
AppVersion={#AppVersion}
AppPublisher=Endrias F. Abitte
AppCopyright=Copyright (c) 2026 Endrias F. Abitte
LicenseFile=installer_license.txt
DefaultDirName={localappdata}\Programs\AmharicDictate
DefaultGroupName=Amharic Dictate
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=AmharicDictate-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AmharicDictate.exe
Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
; ---- look: the app's dark green theme with the mesob logo
WizardStyle=modern dark hidebevels includetitlebar
WizardBackColor=#0F3D2A
WizardBackImageFile=art\background-100.png,art\background-150.png,art\background-200.png
WizardImageFile=art\welcome-100.png,art\welcome-150.png,art\welcome-200.png
WizardSmallImageFile=art\icon-100.png,art\icon-150.png,art\icon-200.png
; ---- pages: Welcome -> System check -> Licence (scroll, accept) -> Installing (percentage, size, tips) -> Finished
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes

[Messages]
WelcomeLabel1=Welcome
WelcomeLabel2=Free Amharic dictation for Windows, powered by Amharic Speech-to-Text EFA v1 — an AI speech model that runs entirely on your computer, with no internet needed.%n%nAmharic Dictate {#AppVersion} needs about {#AppSizeMB} MB of disk space. It installs for your Windows account only and doesn't need administrator rights.%n%nClick Next to continue.
FinishedHeadingLabel=Ready to dictate
FinishedLabel=Setup has finished installing Amharic Dictate and Amharic Speech-to-Text EFA v1.%n%nFind it in the Start menu or on your desktop.

[Files]
Source: "..\dist\AmharicDictate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer_license.txt"; DestDir: "{app}"; DestName: "LICENCES.txt"; Flags: ignoreversion
Source: "..\assets\guide.html"; DestDir: "{app}"; DestName: "Amharic Dictate guide.html"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"
Name: "{group}\Amharic Dictate guide"; Filename: "{app}\Amharic Dictate guide.html"
; No "Uninstall" shortcut: Windows 10/11 hide them on purpose. Uninstall from Settings → Apps → Installed apps,
; or right-click Amharic Dictate in the Start menu → Uninstall.
Name: "{userdesktop}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"

[Run]
Filename: "{app}\AmharicDictate.exe"; Description: "Launch Amharic Dictate"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM AmharicDictate.exe /F"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
type
  TMemoryStatusEx = record
    dwLength: DWORD;
    dwMemoryLoad: DWORD;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var Status: TMemoryStatusEx): BOOL;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';
function waveInGetNumDevs: Cardinal;
  external 'waveInGetNumDevs@winmm.dll stdcall';

const
  MinMemGB = 4;  RecMemGB = 8;           // memory: required / recommended
  RecFreeMB = 4096;                      // free disk recommended (app + voice profiles)

var
  CheckPage: TWizardPage;
  CheckLines: array of TNewStaticText;
  CheckSummary: TNewStaticText;
  CheckFailed: Boolean;
  ProgressText, TipText: TNewStaticText;
  Tips: array of String;

procedure AddCheck(const Mark, Text: String; Color: TColor);
var
  L: TNewStaticText;
  n: Integer;
begin
  n := GetArrayLength(CheckLines);
  SetArrayLength(CheckLines, n + 1);
  L := TNewStaticText.Create(CheckPage);
  L.Parent := CheckPage.Surface;
  L.Top := ScaleY(4 + n * 30);
  L.Left := 0;
  L.Font.Size := 10;
  L.Font.Name := 'Segoe UI Symbol';            // has the check, cross and warning marks
  L.Font.Color := Color;
  L.Caption := Mark + '   ' + Text;
  CheckLines[n] := L;
end;

// System check: Windows version, 64-bit, memory, free disk space, microphone.
// Blocks the install only for what the app can't run without; the rest are warnings.
procedure RunSystemCheck;
var
  V: TWindowsVersion;
  M: TMemoryStatusEx;
  MemGB: Integer;
  Free, Total: Int64;
  FreeMB: Int64;
  NeedMB: Integer;
  Good, Warn, Bad: TColor;
begin
  Good := $A8E07E;  Warn := $66CCFF;  Bad := $808AFF;   // BGR: green, amber, red
  CheckFailed := False;
  GetWindowsVersionEx(V);
  if V.Major >= 10 then AddCheck('✔', 'Windows 10 or 11', Good)
  else begin AddCheck('✖', 'Windows 10 or 11 is required', Bad); CheckFailed := True; end;

  if IsWin64 then AddCheck('✔', '64-bit Windows', Good)
  else begin AddCheck('✖', '64-bit Windows is required', Bad); CheckFailed := True; end;

  M.dwLength := 64;
  if GlobalMemoryStatusEx(M) then
  begin
    MemGB := Integer((M.ullTotalPhys + 536870912) div 1073741824);
    if MemGB >= RecMemGB then AddCheck('✔', Format('Memory: %d GB', [MemGB]), Good)
    else if MemGB >= MinMemGB then AddCheck('⚠', Format('Memory: %d GB — works, but 8 GB is recommended', [MemGB]), Warn)
    else begin AddCheck('✖', Format('Memory: %d GB — at least 4 GB is required', [MemGB]), Bad); CheckFailed := True; end;
  end;

  NeedMB := {#AppSizeMB} + 200;
  if GetSpaceOnDisk64(AddBackslash(ExtractFileDrive(ExpandConstant('{localappdata}'))), Free, Total) then
  begin
    FreeMB := Free div 1048576;
    if FreeMB >= RecFreeMB then AddCheck('✔', Format('Free disk space: %d GB', [Integer(FreeMB div 1024)]), Good)
    else if FreeMB >= NeedMB then AddCheck('⚠', Format('Free disk space: %d MB — about 4 GB is recommended', [Integer(FreeMB)]), Warn)
    else begin AddCheck('✖', Format('Free disk space: %d MB — %d MB is needed', [Integer(FreeMB), NeedMB]), Bad); CheckFailed := True; end;
  end;

  if waveInGetNumDevs > 0 then AddCheck('✔', 'Microphone found', Good)
  else AddCheck('⚠', 'No microphone found — connect one before you dictate', Warn);

  CheckSummary := TNewStaticText.Create(CheckPage);
  CheckSummary.Parent := CheckPage.Surface;
  CheckSummary.Top := ScaleY(4 + GetArrayLength(CheckLines) * 30 + 14);
  CheckSummary.Width := CheckPage.SurfaceWidth;
  CheckSummary.WordWrap := True;
  if CheckFailed then
    CheckSummary.Caption := 'This computer doesn''t meet the requirements above, so Amharic Dictate can''t be installed.'
  else
    CheckSummary.Caption := 'This computer is ready for Amharic Dictate. Click Next to continue.';
end;

procedure InitializeWizard;
begin
  CheckPage := CreateCustomPage(wpWelcome, 'System check', 'Checking that this computer can run Amharic Dictate and Amharic Speech-to-Text EFA v1.');
  RunSystemCheck;

  // Installing page: percentage and size copied, then a tip that changes as the install goes on.
  ProgressText := TNewStaticText.Create(WizardForm);
  ProgressText.Parent := WizardForm.InstallingPage;
  ProgressText.Left := WizardForm.ProgressGauge.Left;
  ProgressText.Top := WizardForm.ProgressGauge.Top + WizardForm.ProgressGauge.Height + ScaleY(10);
  ProgressText.Width := WizardForm.ProgressGauge.Width;
  ProgressText.Font.Size := 11;
  ProgressText.Font.Style := [fsBold];
  ProgressText.Caption := '';

  TipText := TNewStaticText.Create(WizardForm);
  TipText.Parent := WizardForm.InstallingPage;
  TipText.Left := WizardForm.ProgressGauge.Left;
  TipText.Top := ProgressText.Top + ScaleY(40);
  TipText.Width := WizardForm.ProgressGauge.Width;
  TipText.AutoSize := False;
  TipText.Height := ScaleY(90);
  TipText.WordWrap := True;
  TipText.Font.Name := 'Ebrima';                 // has Amharic letters and Latin
  TipText.Font.Size := 10;

  SetArrayLength(Tips, 10);
  Tips[9] := 'Amharic Dictate is powered by Amharic Speech-to-Text EFA v1, an AI speech model trained on more than 150 hours of Amharic speech. It turns your voice into text right on this computer.';
  Tips[0] := 'Tip:  Press Ctrl + Alt + Space in any program to start dictating. Press it again when you''re done.';
  Tips[1] := 'Tip:  Amharic Dictate runs in the system tray, next to the clock. If you don''t see its round icon, click the ^ arrow — you can drag the icon onto the taskbar to keep it visible.';
  Tips[2] := 'Tip:  Say "አራት ነጥብ" for ።, "ነጠላ ሰረዝ" for ፣ and "የጥያቄ ምልክት" for ?.  Say "አዲስ መስመር" for a new line.';
  Tips[3] := 'Tip:  Click any word in the dictation box to fix it, remove it, or pick a suggestion.';
  Tips[4] := 'Tip:  Dictating into Microsoft Word? Your words appear in the document as you speak, and fixes in either place stay in step.';
  Tips[5] := 'Tip:  Make it learn your voice: right-click the tray icon, choose Voice profiles, and read a few sentences.';
  Tips[6] := 'Tip:  Add names and special terms to My words so they''re always spelled your way.';
  Tips[7] := 'Amharic Speech-to-Text EFA v1 runs on this computer. Your voice and your text are never sent anywhere. Like any AI it can mishear words, so check important text.';
  Tips[8] := 'Need help later? Right-click the tray icon and choose How to use… for the full guide.';
  TipText.Caption := Tips[9];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CheckPage <> nil) and (CurPageID = CheckPage.ID) and CheckFailed then
  begin
    MsgBox('Amharic Dictate can''t be installed on this computer. See the list for what''s missing.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  Pct, DoneMB: Int64;
  n: Integer;
begin
  if MaxProgress <= 0 then Exit;
  Pct := (Int64(CurProgress) * 100) div MaxProgress;
  DoneMB := (Int64(CurProgress) * {#AppSizeMB}) div MaxProgress;
  ProgressText.Caption := Format('%d%%     %d MB of %d MB', [Integer(Pct), Integer(DoneMB), {#AppSizeMB}]);
  n := GetArrayLength(Tips);
  TipText.Caption := Tips[(Integer((Pct * n) div 101) + n - 1) mod n];    // starts with the AI tip
end;

// On uninstall: remove the "start with Windows" entry, and offer to delete the user's own data
// (settings, voice profiles, recordings, corrections). Silent uninstalls keep the data.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AmharicDictate');
    DataDir := ExpandConstant('{userappdata}\AmharicDictate');
    if DirExists(DataDir) and (not UninstallSilent) then
      if MsgBox('Also delete your Amharic Dictate settings, voice profiles and voice recordings?' + #13#10 + #13#10 +
                'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
