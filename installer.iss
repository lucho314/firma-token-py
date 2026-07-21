; Firmador Token — instalador todo-en-uno (Inno Setup 6+)
; Compilar:  iscc installer.iss   ->  Output\FirmadorToken-Setup.exe
; Instala per-user (sin UAC), agrega autostart al iniciar sesión.

#define MyAppName    "Firmador Token"
#define MyAppVersion "1.0.0"
#define MyAppExe     "FirmadorToken.exe"
#define MyAppPublisher "ATER"

[Setup]
AppId={{8F3A2C10-4B77-4E2A-9D1E-firmadortoken01}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user: no requiere admin ni UAC.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\FirmadorToken
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=FirmadorToken-Setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=firmador.ico
UninstallDisplayIcon={app}\{#MyAppExe}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "autostart"; Description: "Iniciar automáticamente al iniciar sesión en Windows"; GroupDescription: "Inicio:"
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "dist\FirmadorToken.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example";           DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExe}"
Name: "{group}\Desinstalar {#MyAppName}";  Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}";        Filename: "{app}\{#MyAppExe}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Iniciar {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Datos de la app (log, output, .env) viven en LOCALAPPDATA\FirmadorToken.
Type: filesandordirs; Name: "{localappdata}\FirmadorToken"
