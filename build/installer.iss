; Inno Setup script — per-user install, no admin rights needed.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{C0199516-7A55-464A-A36C-54B31DE0B193}
AppName=Amharic Dictate
AppVersion={#AppVersion}
AppPublisher=Endrias F. Abitte
AppCopyright=Copyright (c) 2026 Endrias F. Abitte
LicenseFile=..\LICENSE
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
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\AmharicDictate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"
Name: "{group}\Uninstall Amharic Dictate"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Amharic Dictate"; Filename: "{app}\AmharicDictate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AmharicDictate.exe"; Description: "Launch Amharic Dictate"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM AmharicDictate.exe /F"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
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

