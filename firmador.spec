# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm --clean firmador.spec  ->  dist\FirmadorToken.exe
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# pyhanko y su cadena criptográfica traen submódulos/datos que PyInstaller no
# detecta solo (se importan de forma dinámica). collect_all los arrastra.
for pkg in ("pyhanko", "pyhanko_certvalidator", "asn1crypto",
            "oscrypto", "cryptography", "pkcs11", "pystray", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all({pkg}) omitido: {e}")

hiddenimports += collect_submodules("pyhanko")
hiddenimports += [
    "flask", "flask_cors", "requests", "dotenv",
    "pystray._win32", "windows_cng",
]

block_cipher = None

a = Analysis(
    ["tray_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="FirmadorToken",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # --windowed: sin ventana de consola (demonio)
    disable_windowed_traceback=False,
    icon="firmador.ico",
)
