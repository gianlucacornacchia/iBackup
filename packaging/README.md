# Packaging — Windows `ibackup-gui.exe`

Everything needed to freeze the desktop app into a Windows executable. This is
Phase 2 step 12 (`gui-packaging`); the CLI has its own, separate, not-yet-started
release milestone (`windows-cli-release` in `docs/todos.md`).

## Files

| File | Purpose |
|---|---|
| `ibackup.spec` | PyInstaller build spec. One-directory (**not** `--onefile`) windowed build of `run_gui.py`. |
| `run_gui.py` | Entry-point shim for PyInstaller's import analysis; calls the same `application_main()` as the installed `ibackup-gui` script. |
| `make_icon.py` | Regenerates `icon.ico` from the GUI's own drawn glyph. Run only when the glyph changes. |
| `icon.ico` | Committed multi-resolution app icon (16-256 px). |
| `version_info.txt` | Windows version resource embedded in the `.exe`. |
| `smoke_test.py` | Launches the built `.exe` and fails if it dies or logs a traceback. |

## Build

From the repo root, on Windows, in the project venv:

```powershell
.\.venv\Scripts\pyinstaller packaging\ibackup.spec --noconfirm
.\.venv\Scripts\python packaging\smoke_test.py dist\ibackup-gui\ibackup-gui.exe
```

The build writes `dist\ibackup-gui\`, with `ibackup-gui.exe` at its root and Qt
next to it in `_internal\`. Both `build\` and `dist\` are git-ignored.

**A build is not done until the smoke test passes.** PyInstaller reports success
for executables that crash instantly on a missing DLL or hidden import, so the
smoke test - a real launch of the real artifact under
`QT_QPA_PLATFORM=offscreen` - is the check that answers whether packaging
actually worked. It is wired into the `package` job in
`.github/workflows/ci.yml`; `tests/test_packaging.py` covers the build inputs
and the smoke test's own logic, not the (minutes-long) build.

## Rules that must not be broken silently

- **Keep the one-directory layout.** Qt/PySide6 is LGPL, and shipping its DLLs
  as separate files preserves the user's right to replace them (ADR-0011
  item 3). Switching to `--onefile` changes that obligation and needs a fresh
  licensing decision first.
- **Keep the icon self-drawn.** `icon.ico` is rendered from
  `iphone_archive.gui.icons`, so no third-party icon set or its redistribution
  terms enter the project (ADR-0011 item 4).
- **Bump `version_info.txt` with `project.version`.** There is no automatic
  sync; `tests/test_packaging.py` fails if the two drift apart.
- **Do not fork the entry point.** `run_gui.py` must stay a one-line call into
  `iphone_archive.gui.application:application_main`.

## Not covered yet

Code signing, an installer, license/notice bundling and a clean-machine
(no-Python) install test belong to the release milestone, not to this step. The
artifact produced here is unsigned, so Windows SmartScreen will warn on first
run.
