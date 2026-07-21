# firma-token-py

Prueba de firma digital PDF con token físico PKCS#11.

## Setup

```bash
pip install -r requirements.txt
```

## Paso 1 — detectar token y certificados

```bash
python token_info.py
# o con dll explícita:
python token_info.py C:\Windows\System32\eTPKCS11.dll
```

## Paso 2 — firmar un PDF

```bash
python sign_pdf.py entrada.pdf salida.pdf 1234
# con dll explícita:
python sign_pdf.py entrada.pdf salida.pdf 1234 C:\Windows\System32\eTPKCS11.dll
# con slot y label específicos:
python sign_pdf.py entrada.pdf salida.pdf 1234 C:\Windows\System32\eTPKCS11.dll 0 "Mi Certificado"
```

## DLLs comunes

| Token | DLL |
|-------|-----|
| SafeNet eToken | `eTPKCS11.dll` |
| Bit4id | `eps2003csp11.dll` |
| NetSign | `ngp11v211.dll` |

## Servicio de bandeja (demonio)

`server.py` es el servidor Flask de firma. Para distribuirlo como app de
bandeja que arranca al iniciar sesión, se empaqueta con `tray_app.py`. Detalle
completo en [BUILD.md](BUILD.md).

Correr suelto en desarrollo:

```bash
python tray_app.py      # levanta Flask + icono de bandeja
# o solo el server, sin bandeja:
python server.py
```

## Regenerar el instalador (Setup.exe)

Requiere, una sola vez: Python 3.10+ 64-bit e
[Inno Setup 6+](https://jrsoftware.org/isdl.php)
(`winget install --id JRSoftware.InnoSetup -e`).

Build completo (deps + icono + exe):

```bat
build.bat
```

Instalador todo-en-uno:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

> Ajustar la ruta de `ISCC.exe` según dónde quedó Inno Setup
> (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe` si se instaló para todos los usuarios).

Regeneración rápida tras cambiar el código (con deps ya instaladas):

```powershell
python make_icon.py
pyinstaller --noconfirm --clean firmador.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Artefactos:

- `dist\FirmadorToken.exe` — ejecutable único (sin Python en destino).
- `Output\FirmadorToken-Setup.exe` — **instalador a distribuir**.
