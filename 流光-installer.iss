; 流光 v1.2.0 Windows 安装程序脚本
; ============================================================
; 使用方法：
;   1. 下载并安装 Inno Setup 6: https://jrsoftware.org/isdl.php
;   2. 双击打开本文件 流光-installer.iss
;   3. 按 Ctrl+F9 编译，或在菜单 Build → Compile
;   4. 生成的安装程序位于: Output\流光-Setup-v1.2.0.exe
;
; 命令行编译（推荐，可加入自动化）:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" 流光-installer.iss
; ============================================================

#define MyAppName "流光"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "流光"
#define MyAppURL "https://github.com/CHEN-DIAN94/All-round-Conversion-Tool"
#define MyAppExeName "流光.exe"

[Setup]
AppId={{B6F3A2E1-5C7D-4E8A-9F01-3A2B4C5D6E7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=流光-Setup-v1.2.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
DisableDirPage=no
AllowUNCPath=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加图标:"
Name: "desktopicon\common"; Description: "所有用户"; GroupDescription: "附加图标:"
Name: "desktopicon\user"; Description: "仅当前用户"; GroupDescription: "附加图标:"; Flags: exclusive unchecked
Name: "associate"; Description: "关联文件类型（双击视频/音频/图片用流光打开）"; GroupDescription: "其他任务:"

[Files]
; 主程序
Source: "dist\流光.exe"; DestDir: "{app}"; Flags: ignoreversion
; FFmpeg 引擎
Source: "bin\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
; 图标
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{#SourcePath}\icon.ico'))

[Icons]
; 开始菜单
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式（按用户选择）
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon\common; IconFilename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon\user; IconFilename: "{app}\{#MyAppExeName}"

[Run]
; 安装后可选启动
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent runwithoutas

[UninstallDelete]
; 清理用户数据（可选，注释掉则保留设置）
; Type: filesandordirs; Name: "{localappdata}\LiuGuang"

[Registry]
; 关联文件类型（仅当选中关联任务时）
Root: HKCR; Subkey: "流光.video"; ValueType: string; ValueName: ""; ValueData: "视频文件"; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: "流光.video\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate
Root: HKCR; Subkey: "流光.video\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate
; 注册扩展名
Root: HKCR; Subkey: ".mp4\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".mkv\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".avi\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".mov\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".mp3\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".wav\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".flac\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".jpg\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate
Root: HKCR; Subkey: ".png\OpenWithList\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: ""; Flags: uninsdeletekey; Tasks: associate

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
