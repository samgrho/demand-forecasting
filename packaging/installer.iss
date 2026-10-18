; Inno Setup script for the desktop app. Built by packaging\build.ps1, which
; passes /DAppVersion=<version from app/__init__.py>.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Hotel Demand Forecaster"
#define AppExe "HotelDemandForecaster.exe"

[Setup]
AppId={{8C1F6E2A-3B5D-4E8F-9A71-2D4C6B8E0F13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
; Per-user install: no administrator rights needed.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=HotelDemandForecaster-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove the previous build's libraries so upgrades don't leave stale modules behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\HotelDemandForecaster\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Settings (%APPDATA%\HotelDemandForecaster) and the cache
; (%LOCALAPPDATA%\HotelDemandForecaster) are kept on uninstall so a reinstall
; keeps the user's contact email and Ticketmaster key.

[Code]
const
  WebView2Key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    MsgBox('This app shows its window with the Microsoft Edge WebView2 Runtime, which was not found.' + #13#10 + #13#10 +
           'It is built into Windows 11. On Windows 10, install it free from Microsoft (search "WebView2 Runtime") before starting the app.',
           mbInformation, MB_OK);
end;
