"""
Fallback backend: Windows CNG (Windows-MY certificate store).
Usado cuando no hay DLL PKCS#11 disponible.
No requiere dependencias externas más allá de las ya declaradas.
"""

import sys
import ctypes
import ssl
import hashlib
import datetime
from typing import Optional

from cryptography import x509 as crypto_x509
from cryptography.hazmat.backends import default_backend

# ── Constantes CNG ────────────────────────────────────────────────────────────
CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG = 0x00040000
CRYPT_ACQUIRE_SILENT_FLAG          = 0x00000040
CERT_NCRYPT_KEY_SPEC               = 0xFFFFFFFF
BCRYPT_PAD_PKCS1                   = 0x00000002

_crypt32 = ctypes.windll.crypt32
_ncrypt  = ctypes.windll.ncrypt

# Declarar tipos explícitos — sin esto ctypes usa c_int (32-bit) y trunca punteros en 64-bit
_crypt32.CertOpenStore.argtypes  = [ctypes.c_uint, ctypes.c_ulong, ctypes.c_void_p,
                                     ctypes.c_ulong, ctypes.c_wchar_p]
_crypt32.CertOpenStore.restype   = ctypes.c_void_p

_crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_crypt32.CertEnumCertificatesInStore.restype  = ctypes.c_void_p

_crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_crypt32.CertCloseStore.restype  = ctypes.c_bool

_crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
    ctypes.c_void_p,                   # pCert
    ctypes.c_ulong,                    # dwFlags
    ctypes.c_void_p,                   # pvParameters
    ctypes.POINTER(ctypes.c_void_p),   # phCryptProvOrNCryptKey
    ctypes.POINTER(ctypes.c_ulong),    # pdwKeySpec
    ctypes.POINTER(ctypes.c_bool),     # pfCallerFreeProvOrNCryptKey
]
_crypt32.CryptAcquireCertificatePrivateKey.restype = ctypes.c_bool

_ncrypt.NCryptSignHash.argtypes = [
    ctypes.c_void_p,                   # hKey
    ctypes.c_void_p,                   # pPaddingInfo
    ctypes.c_char_p,                   # pbHashValue
    ctypes.c_ulong,                    # cbHashValue
    ctypes.c_char_p,                   # pbSignature
    ctypes.c_ulong,                    # cbSignature
    ctypes.POINTER(ctypes.c_ulong),    # pcbResult
    ctypes.c_ulong,                    # dwFlags
]
_ncrypt.NCryptSignHash.restype = ctypes.c_long  # SECURITY_STATUS


# ── Structs ───────────────────────────────────────────────────────────────────
class CERT_CONTEXT(ctypes.Structure):
    """Mapeo de CERT_CONTEXT de crypt32.dll (64-bit)."""
    _fields_ = [
        ("dwCertEncodingType", ctypes.c_ulong),
        ("pbCertEncoded",      ctypes.c_void_p),
        ("cbCertEncoded",      ctypes.c_ulong),
        ("pCertInfo",          ctypes.c_void_p),
        ("hCertStore",         ctypes.c_void_p),
    ]


class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", ctypes.c_wchar_p)]


# ── NCrypt: firmar hash ───────────────────────────────────────────────────────
def _ncrypt_sign_hash(nkey_handle: int, digest: bytes, digest_alg: str = "SHA256") -> bytes:
    padding_info = BCRYPT_PKCS1_PADDING_INFO(digest_alg)
    sig_size = ctypes.c_ulong(0)

    # Primera llamada: obtener tamaño del buffer
    status = _ncrypt.NCryptSignHash(
        nkey_handle,
        ctypes.byref(padding_info),
        digest, len(digest),
        None, 0,
        ctypes.byref(sig_size),
        BCRYPT_PAD_PKCS1,
    )
    if status != 0:
        raise OSError(f"NCryptSignHash (tamaño) HRESULT=0x{status & 0xFFFFFFFF:08X}")

    sig_buf = ctypes.create_string_buffer(sig_size.value)
    status = _ncrypt.NCryptSignHash(
        nkey_handle,
        ctypes.byref(padding_info),
        digest, len(digest),
        sig_buf, sig_size.value,
        ctypes.byref(sig_size),
        BCRYPT_PAD_PKCS1,
    )
    if status != 0:
        raise OSError(f"NCryptSignHash HRESULT=0x{status & 0xFFFFFFFF:08X}")

    return bytes(sig_buf.raw[:sig_size.value])


# ── Listar certificados (sin deps extra, usa ssl built-in) ────────────────────
def list_cng_certs(cn_filter: str | None = None) -> list[dict]:
    """Lee Windows-MY via ssl.enum_certificates. No requiere pywin32."""
    now = datetime.datetime.now(datetime.timezone.utc)
    results = []

    for der, encoding, _trust in ssl.enum_certificates("MY"):
        if encoding != "x509_asn":
            continue
        try:
            cert = crypto_x509.load_der_x509_certificate(der, default_backend())
        except Exception:
            continue

        # Expirado
        if cert.not_valid_after_utc < now:
            continue

        # Requiere digitalSignature si existe KeyUsage
        try:
            ku = cert.extensions.get_extension_for_class(crypto_x509.KeyUsage)
            if not ku.value.digital_signature:
                continue
        except crypto_x509.ExtensionNotFound:
            pass

        cn_attrs = cert.subject.get_attributes_for_oid(crypto_x509.oid.NameOID.COMMON_NAME)
        cn = cn_attrs[0].value if cn_attrs else ""

        # Excluir certs de sistema/dev (mismo criterio que WindowsCngTokenManager.java)
        import re as _re
        _SKIP = ("localhost", "development", "asp.net", "your phone",
                 "microsoft", "ms-organization")
        cn_lower = cn.lower()
        if any(s in cn_lower for s in _SKIP):
            continue
        if _re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', cn_lower):
            continue
        # Excluir auto-firmados (subject == issuer) salvo que sea CA conocida
        if cert.issuer == cert.subject:
            continue

        if cn_filter and cn_filter.lower() not in cn.lower():
            continue

        results.append({
            "cn":         cn,
            "issuer":     cert.issuer.rfc4514_string(),
            "valid_from": cert.not_valid_before_utc.date(),
            "valid_to":   cert.not_valid_after_utc.date(),
            "der":        bytes(der),
        })

    return results


# ── Adquirir handle NCrypt para un certificado ───────────────────────────────
def _acquire_ncrypt_key(cert_der: bytes) -> int:
    """
    Abre Windows-MY, encuentra el certificado por DER exacto,
    y retorna el handle NCrypt de su clave privada.
    """
    CERT_STORE_PROV_SYSTEM_W       = 10
    CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000

    store = _crypt32.CertOpenStore(
        CERT_STORE_PROV_SYSTEM_W, 0, None,
        CERT_SYSTEM_STORE_CURRENT_USER, "MY"
    )
    if not store:
        raise OSError(f"CertOpenStore falló: error={ctypes.windll.kernel32.GetLastError()}")

    try:
        prev_ctx = None
        while True:
            ctx_ptr = _crypt32.CertEnumCertificatesInStore(store, prev_ctx)
            if not ctx_ptr:
                break
            prev_ctx = ctx_ptr

            ctx = ctypes.cast(ctx_ptr, ctypes.POINTER(CERT_CONTEXT)).contents
            der = ctypes.string_at(ctx.pbCertEncoded, ctx.cbCertEncoded)

            if der != cert_der:
                continue

            # Certificado encontrado — adquirir clave NCrypt
            nkey    = ctypes.c_void_p()
            keyspec = ctypes.c_ulong()
            freeit  = ctypes.c_bool()

            ok = _crypt32.CryptAcquireCertificatePrivateKey(
                ctx_ptr,
                CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG | CRYPT_ACQUIRE_SILENT_FLAG,
                None,
                ctypes.byref(nkey),
                ctypes.byref(keyspec),
                ctypes.byref(freeit),
            )
            if not ok:
                raise OSError(
                    f"CryptAcquireCertificatePrivateKey falló: "
                    f"error={ctypes.windll.kernel32.GetLastError()}"
                )
            if keyspec.value != CERT_NCRYPT_KEY_SPEC:
                raise RuntimeError(
                    "La clave usa CSP legacy — solo CNG (NCrypt) soportado en este fallback"
                )
            return nkey.value
    finally:
        _crypt32.CertCloseStore(store, 0)

    raise RuntimeError("Certificado no encontrado en Windows-MY")


# ── Signer para pyhanko ───────────────────────────────────────────────────────
def make_cng_signer(cn_filter: str | None = None):
    """
    Construye un pyhanko Signer usando Windows CNG.
    Si hay múltiples certs válidos, pregunta al usuario.
    """
    from asn1crypto import x509 as asn1_x509
    from pyhanko.sign.signers.pdf_cms import Signer as PyhankSigner
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    certs = list_cng_certs(cn_filter)
    if not certs:
        raise RuntimeError("No hay certificados de firma válidos en Windows-MY")

    if len(certs) > 1 and sys.stdin is not None and sys.stdin.isatty():
        print("\nCertificados disponibles en Windows-MY:")
        for i, c in enumerate(certs):
            print(f"  [{i}] {c['cn']}  (válido hasta {c['valid_to']})")
        idx = int(input("Seleccionar índice: "))
    else:
        # Sin consola interactiva (servicio / app de bandeja empaquetada): usar el
        # primero. input() bloquearía para siempre sin stdin.
        idx = 0

    chosen      = certs[idx]
    cert_der    = chosen["der"]
    nkey_handle = _acquire_ncrypt_key(cert_der)

    _DIGEST_ALG_MAP = {
        "sha256": "SHA256", "sha384": "SHA384",
        "sha512": "SHA512", "sha1":   "SHA1",
    }

    class _CngSigner(PyhankSigner):
        @property
        def signing_cert(self):
            return asn1_x509.Certificate.load(cert_der)

        @property
        def cert_registry(self):
            return SimpleCertificateStore()

        async def async_sign_raw(
            self, data: bytes, digest_algorithm: str, dry_run: bool = False
        ) -> bytes:
            if dry_run:
                return b"\x00" * 256  # placeholder tamaño RSA-2048
            norm = digest_algorithm.lower().replace("-", "")
            digest = hashlib.new(norm, data).digest()
            alg    = _DIGEST_ALG_MAP.get(norm, "SHA256")
            return _ncrypt_sign_hash(nkey_handle, digest, alg)

    print(f"Backend: Windows CNG  |  Cert: {chosen['cn']}")
    return _CngSigner()
