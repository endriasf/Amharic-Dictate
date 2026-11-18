; Inno Setup script — per-user install, no admin rights needed. Needs Inno Setup 6.7 or newer
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
WizardImageFile=
WizardSmallImageFile=art\icon-100.png,art\icon-150.png,art\icon-200.png
; ---- pages: Welcome -> Licence (scroll, accept) -> Installing (percentage, size) -> Finished
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes

[Messages]
WelcomeLabel1=Welcome to Amharic Dictate
WelcomeLabel2=Free, offline Amharic dictation for Windows.%n%nAmharic Dictate {#AppVersion} needs about {#AppSizeMB} MB of disk space. It installs for your Windows account only and doesn't need administrator rights.%n%nClick Next to continue.

[Files]
Source: "..\dist\AmharicDictate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer_license.txt"; DestDir: "{app}"; DestName: "LICENCES.txt"; Flags: ignoreversion
Source: "..\assets\guide.html"; DestDir: "{app}"; DestName: "Amharic Dictate guide.html"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"
Name: "{group}\Amharic Dictate guide"; Filename: "{app}\Amharic Dictate guide.html"
Name: "{group}\Uninstall Amharic Dictate"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"

[Run]
Filename: "{app}\AmharicDictate.exe"; Description: "Launch Amharic Dictate"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM AmharicDictate.exe /F"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
var
  ProgressText: TNewStaticText;

// Installing page: show the percentage and how much has been copied, under the progress bar.
procedure InitializeWizard;
begin
  ProgressText := TNewStaticText.Create(WizardForm);
  ProgressText.Parent := WizardForm.InstallingPage;
  ProgressText.Left := WizardForm.ProgressGauge.Left;
  ProgressText.Top := WizardForm.ProgressGauge.Top + WizardForm.ProgressGauge.Height + ScaleY(10);
  ProgressText.Width := WizardForm.ProgressGauge.Width;
  ProgressText.Font.Size := 11;
  ProgressText.Caption := '';
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  Pct, DoneMB: Int64;
begin
  if MaxProgress <= 0 then Exit;
  Pct := (Int64(CurProgress) * 100) div MaxProgress;
  DoneMB := (Int64(CurProgress) * {#AppSizeMB}) div MaxProgress;
  ProgressText.Caption := Format('%d%%    %d MB of %d MB', [Integer(Pct), Integer(DoneMB), {#AppSizeMB}]);
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
