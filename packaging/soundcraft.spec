# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Soundcraft desktop bundle (macOS, Windows, Linux)."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(root / "src"))
from soundcraft.config import APP_VERSION  # noqa: E402

is_macos = sys.platform == "darwin"

datas = collect_data_files("soundcraft")
binaries = []
hiddenimports = [
    # uvicorn resolves these at runtime, so PyInstaller cannot see them.
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

# Providers register themselves on import and the registry imports them by
# name, so PyInstaller cannot see them. Collected rather than listed, so a new
# provider file cannot be forgotten here and break only the frozen build.
hiddenimports += collect_submodules("soundcraft.providers")

for package in ("webview", "fastapi", "starlette", "google.genai", "pydantic"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except (ImportError, ModuleNotFoundError):
        continue  # Optional dependency absent from this build environment.
    except Exception as e:
        # Anything else is a real problem: fail loudly rather than ship a
        # bundle that is quietly missing a dependency.
        raise SystemExit(f"Collecting {package} failed: {e}") from e
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# scripts/build_app.py converts icon.png to the right format and points here.
icon_env = os.environ.get("SOUNDCRAFT_ICON")
icon = icon_env if icon_env and Path(icon_env).is_file() else None

a = Analysis(
    [str(root / "packaging" / "run_app.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["soundcraft", "soundcraft.app", "soundcraft.server"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the bundle small: these ship with the [local] extra, not the app.
    excludes=["torch", "transformers", "tkinter", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Soundcraft",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=is_macos,
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
    upx=False,
    upx_exclude=[],
    name="Soundcraft",
)

if is_macos:
    app = BUNDLE(
        coll,
        name="Soundcraft.app",
        icon=icon,
        bundle_identifier="com.naotochan.soundcraft",
        info_plist={
            "CFBundleName": "Soundcraft",
            "CFBundleDisplayName": "Soundcraft",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
