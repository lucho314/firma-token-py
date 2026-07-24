"""
Servicio de firma digital — Flask.
Lee BASE_URL y PORT desde .env.

POST /firmar   body: {"token": "..."}
GET  /health
"""

import io
import re
import json
import time
import uuid
import zipfile
import threading
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import sys
import requests
from dotenv import load_dotenv
import os

# Directorio de datos: junto al script en desarrollo; en %LOCALAPPDATA% cuando
# corre como .exe empaquetado (Program Files / carpeta de instalación puede ser
# de solo lectura para el usuario, y _MEIPASS es temporal y se borra al salir).
if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "FirmadorToken"
else:
    DATA_DIR = Path(__file__).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# .env por defecto en el primer arranque, así el usuario tiene qué editar.
# BASE_URL apunta al portal (backend de documentos); PORT es el puerto LOCAL
# donde escucha este servicio de firma (el navegador le pega a 127.0.0.1:PORT).
_env_file = DATA_DIR / ".env"
if not _env_file.exists():
    _env_file.write_text("BASE_URL=https://portalt.ater.gob.ar\nPORT=8765\n", encoding="utf-8")

# override=True: el .env manda siempre. Sin esto, una variable de entorno BASE_URL
# preexistente (heredada del proceso que lanza la app) pisa el archivo y el usuario
# edita el .env sin efecto.
load_dotenv(_env_file, override=True)

BASE_URL   = os.getenv("BASE_URL", "https://portalt.ater.gob.ar").rstrip("/")
PORT       = int(os.getenv("PORT", "8765"))
OUTPUT_DIR = DATA_DIR / "output"

print(f"Config   : {_env_file}")
OUTPUT_DIR.mkdir(exist_ok=True)

from flask import Flask, request, jsonify
from flask_cors import CORS
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from windows_cng import make_cng_signer, FirmanteNoAutorizadoError

app = Flask(__name__)
CORS(app)

# Registro de jobs de firma en memoria — el front hace polling a /firmar/estado/<job_id>
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Los jobs terminados se purgan para que el dict no crezca sin techo: la app puede
# quedar abierta días. El TTL sólo tiene que sobrevivir al último poll del front,
# que corta apenas ve un estado terminal.
JOB_TTL_S = 300

# Subida de firmados al backend
UPLOAD_URL       = f"{BASE_URL}/api/firmador/documentos-firmados"
UPLOAD_REINTENTOS = 5
UPLOAD_BACKOFF_S  = 2

print(f"BASE_URL : {BASE_URL}")
print(f"Puerto   : {PORT}")
print(f"Output   : {OUTPUT_DIR}")

# El signer se inicializa perezosamente (al firmar), no al arrancar — así el
# server levanta aunque el token no esté conectado, y el error se reporta como
# mensaje claro en el job en vez de crashear el arranque.
# Se cachea por CUIT esperado (clave None = sin verificación de firmante), porque
# el certificado del equipo es estable pero la firma puede exigir CUITs distintos.
_signers: dict[str | None, object] = {}
_signer_lock = threading.Lock()


class TokenNoDisponibleError(Exception):
    """No hay token/certificado de firma disponible en el equipo."""


def _get_signer(cuit_esperado: str | None = None):
    """
    Obtiene (o construye) el signer CNG para el CUIT esperado.
    Lanza FirmanteNoAutorizadoError si el token no corresponde a ese CUIT,
    o TokenNoDisponibleError si no hay ningún cert de firma en el equipo.
    """
    clave = re.sub(r"\D", "", cuit_esperado) if cuit_esperado else None
    with _signer_lock:
        if clave not in _signers:
            print(f"Inicializando signer CNG (CUIT {clave or 'sin filtro'})...")
            try:
                _signers[clave] = make_cng_signer(cuit_esperado=cuit_esperado)
            except FirmanteNoAutorizadoError:
                raise  # firmante equivocado — mensaje propio, no lo enmascares
            except Exception as e:
                raise TokenNoDisponibleError(str(e)) from e
        return _signers[clave]


# ── Firma un PDF en memoria ───────────────────────────────────────────────────

def _nombre_campo_libre(reader) -> tuple[str, int]:
    """
    Devuelve (nombre, indice) del próximo campo de firma libre 'SignatureN'.
    Permite acumular firmas: si el PDF ya trae la firma del primer profesional,
    el segundo agrega 'Signature2' en vez de chocar con 'Signature1'.
    """
    from pyhanko.sign.fields import enumerate_sig_fields
    existentes = {name for name, *_ in enumerate_sig_fields(reader)}
    n = 1
    while f"Signature{n}" in existentes:
        n += 1
    return f"Signature{n}", n


def _sign_pdf(pdf_bytes: bytes, cuit_esperado: str | None = None) -> bytes:
    signer = _get_signer(cuit_esperado)

    src    = io.BytesIO(pdf_bytes)
    reader = PdfFileReader(src, strict=False)

    # Nombre de campo único: soporta múltiples firmantes sobre el mismo documento.
    field_name, idx = _nombre_campo_libre(reader)
    # Cada firma visible se apila hacia arriba para no solaparse con la anterior.
    dy  = (idx - 1) * 60
    box = (50, 50 + dy, 300, 100 + dy)

    writer = IncrementalPdfFileWriter.from_reader(reader)

    out = io.BytesIO()
    signers.sign_pdf(
        writer,
        signature_meta=signers.PdfSignatureMetadata(field_name=field_name),
        signer=signer,
        new_field_spec=SigFieldSpec(
            sig_field_name=field_name,
            on_page=0,
            box=box,
        ),
        output=out,
    )
    return out.getvalue()


# ── Obtiene paquete pendiente de la API ───────────────────────────────────────

def _cuit_local() -> str | None:
    """
    CUIT del certificado del token conectado (el que se usará para firmar).
    Se envía al backend para que devuelva los documentos que le tocan a ESTE
    profesional. None si no hay token/cert conectado.
    """
    try:
        from windows_cng import list_cng_certs
        for c in list_cng_certs():
            if c.get("cuit"):
                return c["cuit"]
    except Exception as e:
        print(f"No se pudo leer el CUIT del token: {e}")
    return None


def _fetch_paquete(token: str, cuit: str | None = None) -> dict:
    url     = f"{BASE_URL}/api/firmador/documentos-pendientes"
    cuerpo  = {"Token": token}
    if cuit:
        cuerpo["Cuit"] = cuit
    payload = json.dumps(cuerpo).encode()
    req     = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return {
            "_raw":         raw,
            "_nuevo_token": resp.headers.get("X-Firmador-Token", ""),
            "_cantidad":    int(resp.headers.get("X-Firmador-Documentos", "0")),
            "_cuit":        resp.headers.get("X-Firmador-Cuit", ""),
        }


# ── Utilidades ────────────────────────────────────────────────────────────────

def _finalizar_job(job_id: str, estado: str, error: str | None = None,
                   detalle: str | None = None) -> None:
    """Marca un job como terminado y sella la hora, para que luego pueda purgarse.
    'error' es el mensaje amigable; 'detalle' es la causa técnica (para soporte)."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["estado"] = estado
        job["error"] = error
        job["detalle"] = detalle
        job["fin"] = time.time()


def _purgar_jobs() -> None:
    """Borra los jobs terminados hace más de JOB_TTL_S. Los activos no se tocan."""
    limite = time.time() - JOB_TTL_S
    with _jobs_lock:
        vencidos = [jid for jid, j in _jobs.items() if j.get("fin") and j["fin"] < limite]
        for jid in vencidos:
            del _jobs[jid]
    if vencidos:
        print(f"Jobs purgados: {len(vencidos)}")


def _limpiar_output() -> None:
    """Borra todo lo que haya en output/ para arrancar cada ciclo limpio."""
    for f in OUTPUT_DIR.iterdir():
        if f.is_file():
            try:
                f.unlink()
            except OSError as e:
                print(f"No se pudo borrar {f}: {e}")


def _leer_manifest(zf: zipfile.ZipFile) -> dict:
    """Lee manifest.json del ZIP -> {nombre_archivo: id}. Vacío si no existe."""
    if "manifest.json" not in zf.namelist():
        return {}
    try:
        data = json.loads(zf.read("manifest.json").decode("utf-8"))
        return {item["archivo"]: item["id"] for item in data}
    except Exception as e:
        print(f"manifest.json inválido: {e}")
        return {}


def _subir_firmados(token: str, firmados: list[dict]) -> None:
    """
    Sube los PDF firmados al backend con reintentos.
    firmados: lista de {"id": int, "nombre": str, "bytes": bytes}.
    Lanza RuntimeError si se agotan los reintentos.
    """
    files = [
        (str(doc["id"]), (doc["nombre"], doc["bytes"], "application/pdf"))
        for doc in firmados
    ]

    ultimo_error = None
    for intento in range(1, UPLOAD_REINTENTOS + 1):
        try:
            resp = requests.post(
                UPLOAD_URL,
                data={"token": token},
                files=files,
                timeout=60,
            )
            if resp.status_code == 200:
                print(f"Subida OK (intento {intento}): {resp.text}")
                return
            ultimo_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            ultimo_error = str(e)

        print(f"Subida fallida (intento {intento}/{UPLOAD_REINTENTOS}): {ultimo_error}")
        if intento < UPLOAD_REINTENTOS:
            time.sleep(UPLOAD_BACKOFF_S)

    raise RuntimeError(ultimo_error or "Error desconocido al subir")


# ── Procesa paquete en background: deszip → firma → guarda → sube ─────────────

def _procesar_job(job_id: str, zip_bytes: bytes, cuit_firmante: str | None = None) -> None:
    """Firma cada PDF del ZIP, lo guarda de respaldo y sube los firmados al backend."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        firmados = []  # {"id", "nombre", "bytes"} por documento

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            manifest = _leer_manifest(zf)
            pdfs = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            print(f"PDFs en zip: {pdfs} | manifest: {manifest}")

            for nombre in pdfs:
                pdf_bytes    = zf.read(nombre)
                signed_bytes = _sign_pdf(pdf_bytes, cuit_firmante)

                stem     = Path(nombre).stem
                out_name = f"{stem}_firmado_{ts}.pdf"
                out_path = OUTPUT_DIR / out_name
                out_path.write_bytes(signed_bytes)  # respaldo local
                print(f"  Firmado -> {out_path}")

                doc_id = manifest.get(nombre)
                if doc_id is not None:
                    firmados.append({"id": doc_id, "nombre": nombre, "bytes": signed_bytes})

                with _jobs_lock:
                    job = _jobs[job_id]
                    job["firmados"].append(out_name)
                    job["procesados"] += 1

        # Subida al backend (solo si hubo manifest para correlacionar ids)
        if firmados:
            with _jobs_lock:
                token = _jobs[job_id]["nuevo_token"]
                _jobs[job_id]["estado"] = "subiendo"
            try:
                _subir_firmados(token, firmados)
            except Exception:
                print(traceback.format_exc())
                _finalizar_job(
                    job_id, "error",
                    "No se pudieron enviar los documentos al servidor. Reintente más tarde.",
                )
                return
        else:
            print("Sin manifest.json — se omite la subida al backend.")

        _finalizar_job(job_id, "completado")
        print(f"Job {job_id} completado.")

    except FirmanteNoAutorizadoError as e:
        print(f"Firmante no autorizado: {e}")
        _finalizar_job(
            job_id, "error",
            "El token conectado no corresponde al firmante de estos documentos. "
            "Verificá que sea el dispositivo del profesional habilitado.",
        )

    except TokenNoDisponibleError:
        print("No hay token/certificado de firma disponible.")
        _finalizar_job(
            job_id, "error",
            "No se detectó un token de firma conectado. "
            "Conectá el dispositivo y volvé a intentar.",
        )

    except Exception as e:
        print(traceback.format_exc())
        detalle = f"{type(e).__name__}: {e}"

        # Documento que ya trae una firma en el mismo campo: el backend devolvió como
        # pendiente un PDF ya firmado. Mensaje específico en vez del genérico.
        if "appears to be filled already" in str(e):
            mensaje = ("Uno de los documentos ya estaba firmado (el servidor lo devolvió "
                       "como pendiente). No se firmó nada. Avisá a soporte.")
        else:
            mensaje = "Error al firmar los documentos."

        _finalizar_job(job_id, "error", mensaje, detalle=detalle)


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.post("/firmar")
def firmar():
    data  = request.get_json(force=True, silent=True) or {}
    token = data.get("token") or data.get("Token", "")

    if not token:
        return jsonify({"error": "Falta campo 'token'"}), 400

    print(f"Token recibido: {token[:20]}...")

    # Cada ciclo arranca limpio — borrar firmados de intentos previos
    _limpiar_output()
    _purgar_jobs()

    try:
        # CUIT con el que firmar. Si el front lo indica (el usuario eligió un cert
        # entre varios), se respeta; si no, se autodetecta el del token conectado.
        # Se envía al backend para que devuelva sólo los documentos que le tocan a
        # ESE profesional (titular o interviniente), y es el cert con el que se firma.
        cuit_req = data.get("cuit") or data.get("Cuit")
        cuit = re.sub(r"\D", "", cuit_req) if cuit_req else _cuit_local()
        print(f"CUIT a firmar: {cuit or 'no detectado'} "
              f"({'elegido por el usuario' if cuit_req else 'autodetectado'})")

        # Descarga sincrónica del ZIP (rápido) — la firma va en background
        paquete     = _fetch_paquete(token, cuit)
        zip_bytes   = paquete["_raw"]
        nuevo_token = paquete["_nuevo_token"]
        cantidad    = paquete["_cantidad"]
        print(f"Zip recibido: {len(zip_bytes)} bytes | {cantidad} documento(s) | "
              f"firma con CUIT: {cuit or 'sin filtro'}")

        job_id = uuid.uuid4().hex
        with _jobs_lock:
            _jobs[job_id] = {
                "estado":      "procesando",
                "total":       cantidad,
                "procesados":  0,
                "firmados":    [],
                "nuevo_token": nuevo_token,
                "cuit":        cuit,
                "error":       None,
                "detalle":     None,   # causa técnica si falla (para soporte)
                "fin":         None,   # timestamp al terminar; lo usa _purgar_jobs
            }

        hilo = threading.Thread(
            target=_procesar_job, args=(job_id, zip_bytes, cuit), daemon=True
        )
        hilo.start()

        return jsonify({"job_id": job_id, "total": cantidad})

    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")
        print(f"API error {e.code}: {detalle}")

        # El backend manda {"message": "..."} en los 4xx; usar ese texto si viene.
        mensaje_api = detalle
        try:
            mensaje_api = json.loads(detalle).get("message") or detalle
        except Exception:
            pass

        if e.code == 403:
            # El CUIT del token no es firmante habilitado del trámite.
            return jsonify({"error": mensaje_api}), 403
        if e.code == 404:
            return jsonify({"error": "No hay documentos pendientes de firma."}), 404
        return jsonify({"error": f"API respondió {e.code}", "detalle": detalle}), 502

    except urllib.error.URLError as e:
        print(f"No se pudo conectar a {BASE_URL}: {e.reason}")
        return jsonify({"error": f"No se pudo conectar a {BASE_URL}", "detalle": str(e.reason)}), 502

    except Exception:
        print(traceback.format_exc())
        return jsonify({"error": "Error interno al firmar"}), 500


@app.get("/firmar/estado/<job_id>")
def firmar_estado(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Job no encontrado"}), 404
        return jsonify(dict(job))


@app.get("/certificados")
def certificados():
    """
    Lista los certificados de firma válidos del equipo, para que el front deje
    elegir cuál usar cuando hay más de uno. No expone el DER ni la clave: sólo
    los datos necesarios para mostrarlos.
    """
    try:
        from windows_cng import list_cng_certs
        certs = [
            {
                "cn":           c.get("cn"),
                "cuit":         c.get("cuit"),
                "valido_hasta": str(c.get("valid_to")) if c.get("valid_to") else None,
            }
            for c in list_cng_certs()
        ]
        return jsonify({"certificados": certs})
    except Exception as e:
        print(f"No se pudieron listar certificados: {e}")
        return jsonify({"error": "No se pudieron leer los certificados del equipo.",
                        "detalle": str(e)}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok", "base_url": BASE_URL})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
