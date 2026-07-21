"""
Firma un PDF con token PKCS#11 o Windows CNG (fallback).
Uso: python sign_pdf.py <input.pdf> <output.pdf> <pin> [pkcs11_dll] [slot] [cert_label]
     PIN ignorado en modo Windows CNG (Windows maneja el PIN del token).
"""

import sys
import os

from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

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


def sign_pdf(
    input_path:  str,
    output_path: str,
    pin:         str,
    lib_path:    str | None = None,
    slot:        int        = 0,
    cert_label:  str | None = None,
):
    if lib_path is None:
        lib_path = find_library()

    print(f"Firmando: {input_path}")

    sig_field_spec = SigFieldSpec(
        sig_field_name="Signature1",
        on_page=0,
        box=(50, 50, 300, 100),
    )
    meta = signers.PdfSignatureMetadata(field_name="Signature1")

    use_cng = True

    if lib_path:
        try:
            import pkcs11 as _pkcs11
            _lib = _pkcs11.lib(lib_path)
            _slots = list(_lib.get_slots(token_present=True))
            if _slots:
                use_cng = False
                print(f"Backend: PKCS#11  |  Librería: {lib_path}")
                from pyhanko.config.pkcs11 import PKCS11SignatureConfig
                from pyhanko.sign.pkcs11 import PKCS11SigningContext

                config = PKCS11SignatureConfig(
                    module_path=lib_path,
                    slot_no=slot,
                    user_pin=pin,
                    cert_label=cert_label,
                )
                with PKCS11SigningContext(config) as signer:
                    with open(input_path, "rb") as inf:
                        writer = IncrementalPdfFileWriter(inf)
                        with open(output_path, "wb") as outf:
                            signers.sign_pdf(
                                writer,
                                signature_meta=meta,
                                signer=signer,
                                new_field_spec=sig_field_spec,
                                output=outf,
                            )
            else:
                print("PKCS#11: sin tokens visibles — usando Windows CNG.")
        except Exception as e:
            print(f"PKCS#11 error ({e}) — usando Windows CNG.")

    if use_cng:
        from windows_cng import make_cng_signer
        signer = make_cng_signer(cn_filter=cert_label)
        from pyhanko.pdf_utils.reader import PdfFileReader
        with open(input_path, "rb") as inf:
            reader = PdfFileReader(inf, strict=False)
            writer = IncrementalPdfFileWriter.from_reader(reader)
            with open(output_path, "wb") as outf:
                signers.sign_pdf(
                    writer,
                    signature_meta=meta,
                    signer=signer,
                    new_field_spec=sig_field_spec,
                    output=outf,
                )

    print(f"PDF firmado: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python sign_pdf.py <input.pdf> <output.pdf> <pin> [pkcs11_dll] [slot] [cert_label]")
        sys.exit(1)

    sign_pdf(
        input_path  = sys.argv[1],
        output_path = sys.argv[2],
        pin         = sys.argv[3],
        lib_path    = sys.argv[4] if len(sys.argv) > 4 else None,
        slot        = int(sys.argv[5]) if len(sys.argv) > 5 else 0,
        cert_label  = sys.argv[6] if len(sys.argv) > 6 else None,
    )
