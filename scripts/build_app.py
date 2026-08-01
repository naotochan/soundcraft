#!/usr/bin/env python3
"""Build a desktop bundle for the current platform.

    python scripts/build_app.py

Produces `dist/Soundcraft.app` + zip on macOS, `dist/Soundcraft/` + zip on
Windows and Linux. Builds are unsigned; the README explains what users see on
first launch.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

PLATFORM_TAG = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}
ARCH_TAG = {"x86_64": "x64", "AMD64": "x64", "arm64": "arm64", "aarch64": "arm64"}

MACOS_ICON_SIZES = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


def run(command: list[str]) -> None:
    print(f"  $ {' '.join(command)}")
    subprocess.run(command, check=True, cwd=ROOT)


def app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from soundcraft.config import APP_VERSION

    return APP_VERSION


def build_macos_icns(source: Path) -> Path | None:
    """Convert icon.png to .icns using the macOS-only sips/iconutil pair."""
    if not source.is_file() or not shutil.which("iconutil"):
        return None

    iconset = BUILD / "Soundcraft.iconset"
    icns = BUILD / "Soundcraft.icns"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True)

    for size, name in MACOS_ICON_SIZES:
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(source), "--out", str(iconset / name)],
            check=True,
            capture_output=True,
        )
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    return icns


def build_windows_ico(source: Path) -> Path | None:
    """Convert icon.png to .ico. Needs Pillow; skipped (with a note) without it."""
    if not source.is_file():
        return None
    try:
        from PIL import Image
    except ImportError:
        print("  ! Pillow is not installed — building without a custom icon.")
        print("    pip install pillow")
        return None

    ico = BUILD / "Soundcraft.ico"
    BUILD.mkdir(parents=True, exist_ok=True)
    sizes = [(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]
    Image.open(source).convert("RGBA").save(ico, format="ICO", sizes=sizes)
    return ico


def prepare_icon() -> Path | None:
    source = ROOT / "icon.png"
    system = platform.system()
    if system == "Darwin":
        return build_macos_icns(source)
    if system == "Windows":
        return build_windows_ico(source)
    return source if source.is_file() else None  # Linux: PyInstaller takes a PNG.


def zip_bundle(target: Path, archive: Path) -> None:
    archive.unlink(missing_ok=True)
    if platform.system() == "Darwin" and shutil.which("ditto"):
        # ditto preserves the bundle's symlinks and resource forks; zipfile does not.
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(target), str(archive)])
        return

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(target.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="Assume deps are present")
    parser.add_argument("--no-zip", action="store_true", help="Leave the bundle unarchived")
    args = parser.parse_args()

    system = platform.system()
    tag = PLATFORM_TAG.get(system)
    if tag is None:
        print(f"Unsupported platform: {system}", file=sys.stderr)
        return 1

    version = app_version()
    print(f"==> soundcraft {version} for {tag} ({platform.machine()})")

    if not args.skip_install:
        print("==> Installing build dependencies")
        run([sys.executable, "-m", "pip", "install", "-e", ".[app,lyria,build]", "-q"])

    print("==> Preparing the icon")
    icon = prepare_icon()
    if icon:
        print(f"  {icon.relative_to(ROOT)}")
        os.environ["SOUNDCRAFT_ICON"] = str(icon)

    print("==> PyInstaller")
    shutil.rmtree(DIST / "Soundcraft", ignore_errors=True)
    shutil.rmtree(DIST / "Soundcraft.app", ignore_errors=True)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        str(ROOT / "packaging" / "soundcraft.spec"),
    ])

    bundle = DIST / ("Soundcraft.app" if system == "Darwin" else "Soundcraft")
    if not bundle.exists():
        print(f"ERROR: {bundle} was not produced", file=sys.stderr)
        return 1

    print(f"\nBuilt: {bundle}")
    if not args.no_zip:
        # The architecture is part of the name: CI builds macOS twice (Intel and
        # Apple silicon) and merges the artifacts into one release directory, so
        # a shared name would silently drop one of them.
        arch = ARCH_TAG.get(platform.machine(), platform.machine())
        archive = DIST / f"Soundcraft-{version}-{tag}-{arch}.zip"
        print("==> Archiving")
        zip_bundle(bundle, archive)
        print(f"Built: {archive}")

    if system == "Darwin":
        print("\nThis build is unsigned. On first launch users must right-click")
        print("Soundcraft.app → Open → Open. After that, double-click works.")
    elif system == "Windows":
        print("\nThis build is unsigned. SmartScreen shows a warning on first run:")
        print("More info → Run anyway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
