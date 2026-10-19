; ============================================================
;  智卷 · Inno Setup 安装包脚本
;  构建：python build.py --installer      （需要先有 dist\智卷\ 目录版）
;  依赖：Inno Setup 6   winget install JRSoftware.InnoSetup
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "智卷"
#define MyAppExeName "智卷.exe"
#define MyAppPublisher "Snowly17"
#define MyAppURL "https://github.com/Snowly17/zhijuan"
#define MyAppId "{{8C1B7F2E-6A4D-4F5B-9E3A-2D7C4B1A9F60}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\ZhiJuan
DefaultGroupName=智卷
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=zhijuan-{#MyAppVersion}-win64-setup
SetupIconFile=static\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
; 数据存在 %APPDATA%\智卷，卸载时不动它，重装后题库/成绩还在

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\智卷\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
