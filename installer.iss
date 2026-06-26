; installer.iss — 流光 Inno Setup 安装脚本
; 用法: iscc installer.iss

[Setup]
AppName=流光
AppVersion=1.2.0
AppPublisher=LiuGuang
AppPublisherURL=https://github.com/liuguang/liuguang
DefaultDirName={autopf}\流光
DefaultGroupName=流光
OutputDir=dist\installer
OutputBaseFilename=流光-Windows-Setup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "associatefiles"; Description: "关联 .lgp 项目文件"; GroupDescription: "文件关联:"

[Files]
Source: "dist\流光.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs skipifsourcedirnotexists
Source: "themes\*"; DestDir: "{app}\themes"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\流光"; Filename: "{app}\流光.exe"
Name: "{autodesktop}\流光"; Filename: "{app}\流光.exe"; Tasks: desktopicon

[Registry]
; .lgp 文件关联
Root: HKA; Subkey: "Software\Classes\.lgp"; ValueType: string; ValueName: ""; ValueData: "LiuGuangProject"; Flags: uninsdeletevalue; Tasks: associatefiles
Root: HKA; Subkey: "Software\Classes\LiuGuangProject"; ValueType: string; ValueName: ""; ValueData: "流光项目文件"; Flags: uninsdeletekey; Tasks: associatefiles
Root: HKA; Subkey: "Software\Classes\LiuGuangProject\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\流光.exe,0"; Tasks: associatefiles
Root: HKA; Subkey: "Software\Classes\LiuGuangProject\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\流光.exe"" ""%1"""; Tasks: associatefiles

[Run]
Filename: "{app}\流光.exe"; Description: "启动流光"; Flags: nowait postinstall
