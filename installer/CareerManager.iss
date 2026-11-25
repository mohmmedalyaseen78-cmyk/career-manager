[Setup]
AppName=Career Manager
AppVersion=0.1.0
DefaultDirName={autopf}\Career Manager
DefaultGroupName=Career Manager
OutputDir=..\dist_installer
OutputBaseFilename=CareerManager-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "..\dist\CareerManager\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\Career Manager"; Filename: "{app}\CareerManager.exe"
Name: "{autodesktop}\Career Manager"; Filename: "{app}\CareerManager.exe"

[Run]
Filename: "{app}\CareerManager.exe"; Description: "Run Career Manager"; Flags: nowait postinstall skipifsilent
