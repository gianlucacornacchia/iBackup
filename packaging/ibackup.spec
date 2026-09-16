# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the desktop app, ``ibackup-gui``.

One-directory (not ``--onefile``) build: PySide6/Qt ship as separate DLL/.pyd
files next to the frozen interpreter instead of merged into a single binary.
That keeps the LGPL "relink/replace the library" right intact (ADR-0011 item
3) - a user can, in principle, drop in a different compatible Qt build. Do not
switch this to ``--onefile`` without re-checking that obligation first.

Build from the repo root with the project's own venv (see packaging/README.md
for the full workflow, including the required smoke test):

    .venv\\Scripts\\pyinstaller packaging\\ibackup.spec --noconfirm

Output lands in ``dist/ibackup-gui/``, with ``ibackup-gui.exe`` at its root.
CLI packaging is a separate, not-yet-started milestone (`windows-cli-release`
in docs/todos.md); this spec only freezes the GUI entry point.
"""

from pathlib import Path

block_cipher = None

# PyInstaller sets SPECPATH to this file's own directory (packaging/).
PACKAGING_DIR = Path(SPECPATH).resolve()
ROOT = PACKAGING_DIR.parent
SRC = ROOT / "src"

a = Analysis(
    [str(PACKAGING_DIR / "run_gui.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],
    # pymobiledevice3 and its plugin-style dependents (e.g. click command
    # groups) are only reached indirectly through iphone_archive.device at
    # runtime, which static import analysis can miss; keep the whole package.
    hiddenimports=["pymobiledevice3"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ibackup-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(PACKAGING_DIR / "icon.ico"),
    version=str(PACKAGING_DIR / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ibackup-gui",
)
