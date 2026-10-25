# Packaging — Windows `ibackup-gui.exe`

Everything needed to freeze the desktop app into a Windows executable. This is
Phase 2 step 12 (`gui-packaging`); the CLI has its own, separate, not-yet-started
release milestone (`windows-cli-release` in `docs/todos.md`).

## Files

| File | Purpose |
|---|---|
| `ibackup.spec` | PyInstaller build spec. One-directory (**not** `--onefile`) windowed build of `run_gui.py`. Declares `pymobiledevice3` as a hidden import and lists `src/iphone_archive/gui/webassets/` (vendored Leaflet for the trip map) as `datas`, because it is read from disk at runtime rather than imported. |
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
actually worked. It is wired into the `windows-app` job in
`.github/workflows/build.yml`, which uploads the built app as the
`ibackup-gui-windows` artifact; `tests/test_packaging.py` covers the build inputs
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
- **Keep `gui/webassets/` in `datas`.** Without it the frozen app starts and
  passes the smoke test, but opening a map fails because `leaflet.js`/
  `leaflet.css` are missing. Keep Leaflet's `LICENSE` alongside it.

## Qt WebEngine (trip map)

The map (`gui/mapview.py`) uses `QtWebEngineWidgets`, so the build includes
Qt WebEngine via PyInstaller's PySide6 hooks: Chromium binaries,
`QtWebEngineProcess.exe` and its resources/locales. Expect a much larger
`dist\ibackup-gui\` than before 2026-10-10. Qt WebEngine is LGPL like the rest
of Qt but bundles Chromium's third-party licenses, which the release notice
set must include (ADR-0011, 2026-10-11 note).

No rebuild and smoke test after the map change is recorded in
`docs/progress.md`. `smoke_test.py` does not open a map, so after rebuilding,
also open **Map** on an album in the built app to confirm WebEngine and the
web assets load (tiles need network access).

## Not covered yet

Code signing, an installer, license/notice bundling (Qt, Qt WebEngine/
Chromium, Leaflet, OpenStreetMap attribution) and a clean-machine
(no-Python) install test belong to the release milestone, not to this step. The
artifact produced here is unsigned, so Windows SmartScreen will warn on first
run. `tests/test_packaging.py` does not yet assert the `webassets` `datas`
entry.
