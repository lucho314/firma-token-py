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
; Si el servicio está corriendo, el .exe queda lockeado y la actualización falla
; en silencio. Restart Manager detecta el lock y lo cierra; el mutex (lo crea
; tray_app.py) es el respaldo por si RM no llega a verlo. No relanzamos desde RM:
; ya lo hace la entrada de [Run] al terminar.
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

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

[UninstallRun]
; Antes de borrar archivos: si el servicio quedó abierto, cerrarlo.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExe}"; Flags: runhidden; RunOnceId: "CerrarFirmador"

[UninstallDelete]
; Datos de la app (log, output, .env) viven en LOCALAPPDATA\FirmadorToken.
Type: filesandordirs; Name: "{localappdata}\FirmadorToken"

[Code]
const
  MutexApp = 'FirmadorTokenSingleInstance';

function ServicioCorriendo(): Boolean;
begin
  Result := CheckForMutexes(MutexApp);
end;

{ Cierra el servicio si está corriendo. False = el usuario dijo que no, o no murió. }
function CerrarServicio(): Boolean;
var
  ResultCode, Intento: Integer;
begin
  Result := True;
  if not ServicioCorriendo() then
    Exit;

  if MsgBox('El servicio de firma está corriendo y hay que cerrarlo para poder actualizarlo.'
            + #13#13 + '¿Cerrarlo ahora? (se vuelve a abrir solo al terminar la instalación)',
            mbConfirmation, MB_YESNO) <> IDYES then begin
    Result := False;
    Exit;
  end;

  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExe}', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);

  { taskkill vuelve antes de que el proceso termine de morir: esperar al mutex. }
  for Intento := 1 to 20 do begin
    if not ServicioCorriendo() then
      Break;
    Sleep(250);
  end;

  Result := not ServicioCorriendo();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CerrarServicio() then
    Result := 'El servicio de firma sigue abierto, así que la actualización no se puede aplicar.'
              + #13#13 + 'Cerralo con click derecho en el icono de la bandeja (junto al reloj) '
              + '→ "Cerrar servicio", y volvé a ejecutar el instalador.';
end;
