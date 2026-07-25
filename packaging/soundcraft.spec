# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Soundcraft.app (macOS)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
root = Path(SPECPATH).resolve().parent

datas = collect_data_files("soundcraft")
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "webview",
]

for pkg in ("webview", "fastapi", "starlette", "google.genai", "pydantic"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

icon_path = root / "build" / "Soundcraft.icns"
icon = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(root / "packaging" / "run_app.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["soundcraft", "soundcraft.app", "soundcraft.server"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Soundcraft",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Soundcraft",
)

app = BUNDLE(
    coll,
    name="Soundcraft.app",
    icon=icon,
    bundle_identifier="com.naotochan.soundcraft",
    info_plist={
        "CFBundleName": "Soundcraft",
        "CFBundleDisplayName": "Soundcraft",
        "CFBundleShortVersionString": "0.4.0",
        "CFBundleVersion": "0.4.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
        },
    },
)
