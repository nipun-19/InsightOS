; Inno Setup Script for InsightOS
; This script is prepared for the Windows installer pass. It is intentionally
; kept simple and does not assume repository-local paths or a dev environment.

#ifndef PackageDir
#define PackageDir "D:\projects\Insight_OS\dist\Phase6E-1.0.0-verify-20261023\InsightOS"
#endif

[Setup]
AppName=InsightOS
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\InsightOS
DefaultGroupName=InsightOS
OutputBaseFilename=InsightOS-1.0.0-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
AppendDefaultDirName=yes
CreateAppDir=yes
UninstallDisplayName=InsightOS
UninstallFilesDir={app}

[Files]
Source: "{#PackageDir}\InsightOS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PackageDir}\*"; DestDir: "{app}"; Excludes: "InsightOS.exe"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\InsightOS\InsightOS"; Filename: "{app}\InsightOS.exe"
Name: "{userdesktop}\InsightOS"; Filename: "{app}\InsightOS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\InsightOS.exe"; Description: "Launch InsightOS"; Flags: nowait postinstall skipifsilent

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(
      HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'InsightOS');
end;
