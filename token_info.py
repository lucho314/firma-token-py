"""
Detecta token PKCS#11 o Windows-MY, lista slots/certificados.
Uso: python token_info.py [path_a_pkcs11.dll]
"""

import sys
import datetime
import os

# DLLs comunes en Argentina (eToken SafeNet, Bit4id, NetSign, etc.)
COMMON_LIBS = [
    r"C:\Windows\System32\eTPKCS11.dll",
    r"C:\Windows\System32\aetpkss1.dll",
    r"C:\Windows\System32\eps2003csp11.dll",
    r"C:\Windows\System32\ngp11v211.dll",
    r"C:\Windows\System32\pkcs11.dll",
    r"C:\Windows\SysWOW64\eTPKCS11.dll",
    r"C:\Windows\SysWOW64\aetpkss1.dll",
]


def find_library() -> str | None:
    for lib in COMMON_LIBS:
        if os.path.exists(lib):
            return lib
    return None


def list_via_pkcs11(lib_path: str) -> bool:
    """Retorna True si encontró tokens, False si debe caer a CNG."""
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    print(f"Backend: PKCS#11  |  Librería: {lib_path}")
    lib = pkcs11.lib(lib_path)

    slots = list(lib.get_slots(token_present=True))
    if not slots:
        print("PKCS#11: sin tokens visibles — probando Windows CNG...\n")
        return False

    print(f"\nSlots con token: {len(slots)}")
    for slot in slots:
        token = slot.get_token()
        print(f"\n{'='*50}")
        print(f"Slot:        {slot.slot_id}")
        print(f"Label:       {token.label.strip()}")
        print(f"Fabricante:  {token.manufacturer_id.strip()}")
        print(f"Modelo:      {token.model.strip()}")
        print(f"Serial:      {token.serial.strip()}")

        # Sesión sin PIN para leer certs públicos
        with token.open() as session:
            certs = list(session.get_objects({
                Attribute.CLASS: ObjectClass.CERTIFICATE,
            }))
            print(f"Certificados: {len(certs)}")

            for i, obj in enumerate(certs):
                try:
                    der  = bytes(obj[Attribute.VALUE])
                    cert = x509.load_der_x509_certificate(der, default_backend())
                    cn   = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
                    now  = datetime.datetime.now(datetime.timezone.utc)
                    print(f"\n  Cert [{i}]:")
                    print(f"    CN:       {cn[0].value if cn else 'N/A'}")
                    print(f"    Emisor:   {cert.issuer.rfc4514_string()}")
                    print(f"    Válido:   {cert.not_valid_before_utc.date()} -> {cert.not_valid_after_utc.date()}")
                    print(f"    Expirado: {'SÍ' if cert.not_valid_after_utc < now else 'NO'}")
                except Exception as e:
                    print(f"  Cert [{i}]: error — {e}")

    return True


def list_via_windows_cng():
    from windows_cng import list_cng_certs

    print("Backend: Windows CNG (Windows-MY keystore)")
    certs = list_cng_certs()

    if not certs:
        print("No se encontraron certificados de firma válidos en Windows-MY.")
        return

    print(f"\n{'='*50}")
    print(f"Certificados de firma: {len(certs)}")
    for i, c in enumerate(certs):
        print(f"\n  Cert [{i}]:")
        print(f"    CN:       {c['cn']}")
        print(f"    Emisor:   {c['issuer']}")
        print(f"    Válido:   {c['valid_from']} -> {c['valid_to']}")


def list_token_info(lib_path: str | None = None):
    if lib_path is None:
        lib_path = find_library()

    if lib_path:
        found = list_via_pkcs11(lib_path)
        if found:
            return
        # PKCS#11 cargó pero no vio tokens (SafeNet SAC lo intercepta) -> CNG
    else:
        print("DLL PKCS#11 no encontrada — usando Windows CNG.\n")

    list_via_windows_cng()


if __name__ == "__main__":
    lib = sys.argv[1] if len(sys.argv) > 1 else None
    list_token_info(lib)
