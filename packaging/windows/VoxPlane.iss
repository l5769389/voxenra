; Build with scripts/build_windows.ps1. Requires Inno Setup 6.6 or newer.
#ifndef SourceDir
  #error SourceDir must point to the frozen application directory.
#endif
#ifndef AssetsDir
  #error AssetsDir must point to generated installer assets.
#endif
#ifndef OutputDir
  #error OutputDir is required.
#endif
#ifndef AppVersion
  #error AppVersion is required.
#endif

[Setup]
AppId={{EA2DF9C6-5DC1-4CC3-913B-DB87DB5D0B5E}
AppName=VoxPlane
AppVersion={#AppVersion}
AppPublisher=Jun Liu
VersionInfoVersion={#AppVersion}
; Keep the registered installation (including custom paths) during upgrades.
; Fresh installs use VoxPlane; the stable AppId keeps one uninstall entry.
UsePreviousAppDir=yes
DefaultDirName={localappdata}\Programs\VoxPlane
DefaultGroupName=VoxPlane
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern dynamic
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
SetupIconFile={#AssetsDir}\app.ico
WizardSmallImageFile={#AssetsDir}\wizard-logo.png
UninstallDisplayIcon={app}\VoxPlane.exe
InfoBeforeFile=install-notes.txt
OutputDir={#OutputDir}
OutputBaseFilename=VoxPlane-{#AppVersion}-windows-x64-setup
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zh"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Replace the installer-owned Qt runtime so removed plugins do not survive upgrades.
Type: filesandordirs; Name: "{app}\_internal\PySide6"
; Retire only the previous brand's executable and installer-owned shortcuts.
Type: files; Name: "{app}\Voxenra.exe"
Type: files; Name: "{autoprograms}\Voxenra.lnk"
Type: files; Name: "{autodesktop}\Voxenra.lnk"
Type: files; Name: "{app}\DICOMVision.exe"
Type: files; Name: "{autoprograms}\DICOMVision.lnk"
Type: files; Name: "{autodesktop}\DICOMVision.lnk"

[Icons]
Name: "{autoprograms}\VoxPlane"; Filename: "{app}\VoxPlane.exe"; IconFilename: "{app}\VoxPlane.exe"; AppUserModelID: "com.junliu.voxplane"
Name: "{autodesktop}\VoxPlane"; Filename: "{app}\VoxPlane.exe"; IconFilename: "{app}\VoxPlane.exe"; AppUserModelID: "com.junliu.voxplane"; Tasks: desktopicon

[Run]
Filename: "{app}\VoxPlane.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
en.DesktopIcon=Create a desktop shortcut
zh.DesktopIcon=创建桌面快捷方式
en.AdditionalIcons=Shortcuts:
zh.AdditionalIcons=快捷方式：
en.LaunchApp=Launch VoxPlane
zh.LaunchApp=启动 VoxPlane

; No wildcard uninstall cleanup: never remove user DICOM files, logs or settings.
