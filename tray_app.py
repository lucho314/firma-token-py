"""
Firmador Token — app de bandeja (system tray).

Levanta el servidor Flask (server.py) en un hilo daemon y muestra un icono en la
barra de notificaciones de Windows con:
  - notificación (globo) al iniciar,
  - menú click derecho: Probar API / abrir /health / abrir carpeta / Cerrar.

Pensado para arrancar al iniciar sesión (autostart), sin ventana de consola
(PyInstaller --windowed). En ese modo Windows deja stdout/stderr en None, así que
lo primero es redirigir a un log en disco antes de importar nada que imprima.
"""

import os
import sys

# ── Log a archivo cuando corre empaquetado y sin consola ──────────────────────
_LOG_DIR = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "FirmadorToken")
os.makedirs(_LOG_DIR, exist_ok=True)

if getattr(sys, "frozen", False) or sys.stdout is None:
    _log = open(os.path.join(_LOG_DIR, "firmador.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _log
    sys.stderr = _log

import ctypes
import threading
import webbrowser

import requests
from PIL import Image, ImageDraw, ImageFont
import pystray

# Importar server DESPUÉS de redirigir stdout (server.py imprime al importarse).
from server import app, PORT, OUTPUT_DIR, DATA_DIR, BASE_URL

HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
APP_TITLE  = "Firmador Token"

# Mutex de instancia única. Sirve para dos cosas:
#   1) evitar dos procesos peleando por el puerto (el segundo Flask no bindea y
#      el icono queda vivo pero sin API),
#   2) que el instalador (AppMutex en installer.iss) sepa que el servicio está
#      corriendo y lo cierre antes de reemplazar el .exe.
# Sin prefijo => namespace de la sesión, que es lo que corresponde a una
# instalación per-user: no molesta si otro usuario de la misma PC lo tiene abierto.
MUTEX_NAME          = "FirmadorTokenSingleInstance"
ERROR_ALREADY_EXISTS = 183
_mutex_handle       = None  # global: si se libera, se cierra el mutex


# ── Instancia única ───────────────────────────────────────────────────────────

def _tomar_instancia_unica() -> bool:
    """True si esta es la única instancia; False si ya hay otra corriendo."""
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not _mutex_handle:
        print(f"No se pudo crear el mutex ({kernel32.GetLastError()}); sigo igual.")
        return True
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


# ── Icono ─────────────────────────────────────────────────────────────────────

def _crear_icono() -> Image.Image:
    """Icono generado en runtime (círculo azul con una 'F'). Evita shippear .png."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((3, 3, size - 3, size - 3), fill=(21, 101, 192, 255))
    try:
        font = ImageFont.truetype("segoeui.ttf", 38)
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), "F", fill="white", font=font, anchor="mm")
    return img


# ── Servidor en hilo ──────────────────────────────────────────────────────────

def _run_server() -> None:
    # use_reloader=False: el reloader re-ejecuta el proceso y rompe en hilo/empaquetado.
    try:
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)
    except Exception:
        import traceback
        traceback.print_exc()


# ── Acciones del menú ─────────────────────────────────────────────────────────

def _probar_api(icon, item) -> None:
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.ok:
            icon.notify(f"API OK en puerto {PORT}\n{r.json()}", APP_TITLE)
        else:
            icon.notify(f"API respondió HTTP {r.status_code}", APP_TITLE)
    except Exception as e:
        icon.notify(f"La API no responde: {e}", APP_TITLE)


def _abrir_health(icon, item) -> None:
    webbrowser.open(HEALTH_URL)


def _abrir_output(icon, item) -> None:
    os.startfile(OUTPUT_DIR)  # type: ignore[attr-defined]


def _abrir_log(icon, item) -> None:
    os.startfile(os.path.join(_LOG_DIR, "firmador.log"))  # type: ignore[attr-defined]


def _cerrar(icon, item) -> None:
    icon.notify("Cerrando el servicio de firma...", APP_TITLE)
    icon.stop()
    # El server corre en hilo daemon; os._exit corta todo sin esperar.
    os._exit(0)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Arrancando {APP_TITLE} | puerto {PORT} | backend {BASE_URL} | datos {DATA_DIR}")

    if not _tomar_instancia_unica():
        print("Ya hay una instancia corriendo; salgo.")
        return

    threading.Thread(target=_run_server, daemon=True).start()

    icon = pystray.Icon(
        "firmador_token",
        icon=_crear_icono(),
        title=f"{APP_TITLE} — puerto {PORT}",
        menu=pystray.Menu(
            pystray.MenuItem("Probar API", _probar_api, default=True),
            pystray.MenuItem("Abrir /health en el navegador", _abrir_health),
            pystray.MenuItem("Abrir carpeta de firmados", _abrir_output),
            pystray.MenuItem("Ver log", _abrir_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar servicio", _cerrar),
        ),
    )

    def _on_ready(ic) -> None:
        ic.visible = True
        ic.notify(f"Servicio de firma iniciado en el puerto {PORT}.", APP_TITLE)

    icon.run(setup=_on_ready)


if __name__ == "__main__":
    main()
