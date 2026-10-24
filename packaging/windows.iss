; Inno Setup 6 script. Built by packaging\build_windows.ps1 (passes /DAppVersion=x.y.z).
; Installs per user (no admin rights), with a normal uninstaller in Settings -> Apps.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{A0B59BED-4B28-4EAF-A93D-84D8057D060C}
AppName=DiBeKho
AppVersion={#AppVersion}
AppPublisher=DiBeKho
DefaultDirName={localappdata}\Programs\DiBeKho
DefaultGroupName=DiBeKho
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DiBeKho-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DiBeKho.exe
SetupIconFile=..\resources\dibekho.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; Vietnamese.isl is not shipped with Inno Setup; it can be added from the unofficial translations later.
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\DiBeKho\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\DiBeKho"; Filename: "{app}\DiBeKho.exe"
Name: "{autodesktop}\DiBeKho"; Filename: "{app}\DiBeKho.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DiBeKho.exe"; Description: "{cm:LaunchProgram,DiBeKho}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the tiny per-machine config (workspace path + language)
Type: files; Name: "{userappdata}\DiBeKho\config.json"
Type: dirifempty; Name: "{userappdata}\DiBeKho"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // Data is kept by default. Only the default workspace location is offered for deletion.
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userdocs}\DiBeKho');
    if DirExists(DataDir) then
      if MsgBox('Xoá luôn thư mục dữ liệu DiBeKho?' + #13#10 + DataDir + #13#10#13#10 +
                'Chọn "No" để giữ lại (khuyên dùng).' + #13#10 +
                'Also delete the DiBeKho data folder? Choose "No" to keep it (recommended).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
