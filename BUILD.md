# Empaquetado — instalador todo-en-uno (Windows)

Genera un único `FirmadorToken-Setup.exe` que el usuario descarga, instala con
doble clic (sin Python, sin dependencias), y que corre como app de bandeja
(system tray) arrancando al iniciar sesión.

## Arquitectura

- **`server.py`** — servidor Flask (firma). No se toca para correr suelto.
- **`tray_app.py`** — entry point del empaquetado: levanta Flask en un hilo
  daemon y muestra el icono de bandeja con menú (Probar API / Cerrar / ...).
- **`.exe`** generado con PyInstaller (`--onefile --windowed`): incluye Python y
  todas las libs. La máquina destino **no necesita Python**.
- **Instalador** con Inno Setup: copia el `.exe`, crea acceso directo y
  (opcional, tildado por defecto) el autostart en la carpeta de Inicio.

> No es un "Windows Service". Un servicio corre en *session 0*, aislado del
> escritorio: no puede mostrar icono en bandeja, y la firma CNG necesita el
> almacén de certificados **del usuario** (`CURRENT_USER`). Por eso es una app
> de bandeja con autostart al login.

## Requisitos de build (solo en la PC que compila)

1. Python 3.10+ (64-bit).
2. [Inno Setup 6+](https://jrsoftware.org/isdl.php) — para el instalador.
   Agregar `iscc.exe` al PATH (típico: `C:\Program Files (x86)\Inno Setup 6`).

## Pasos

```bat
build.bat
```

Hace: instala deps + PyInstaller, genera `firmador.ico`, y compila
`dist\FirmadorToken.exe`.

Luego el instalador:

```bat
iscc installer.iss
```

Produce `Output\FirmadorToken-Setup.exe`. **Ese** es el archivo que se sube al
servidor para que el usuario descargue.

## Qué hace el instalador

- Instala per-user en `%LOCALAPPDATA%\Programs\FirmadorToken` (**sin UAC/admin**).
- Accesos directos en menú Inicio (+ escritorio opcional).
- Autostart al iniciar sesión (tarea tildada por defecto).
- Desinstalador incluido; borra también los datos en `%LOCALAPPDATA%\FirmadorToken`.

## Datos en runtime (en la PC del usuario)

Todo en `%LOCALAPPDATA%\FirmadorToken\`:

- `.env` — se crea solo en el primer arranque (`BASE_URL`, `PORT`). Editable.
- `output\` — respaldo local de los PDF firmados.
- `firmador.log` — stdout/stderr (útil para soporte; accesible desde el menú "Ver log").

## Uso para el usuario final

1. Descarga e instala `FirmadorToken-Setup.exe`.
2. Aparece el icono azul "F" en la bandeja + globo "Servicio de firma iniciado".
3. Click derecho → **Probar API**, o **Cerrar servicio**.
4. Arranca solo en cada login (si dejó tildado el autostart).

## Firmar el ejecutable (recomendado)

Sin firma de código, SmartScreen puede advertir en la primera ejecución. Si
tienen un certificado de firma de código:

```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 dist\FirmadorToken.exe
```

(firmar el `.exe` antes de `iscc`, e idealmente también el `Setup.exe`).
