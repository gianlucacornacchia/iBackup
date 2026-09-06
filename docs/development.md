# Development Guide — iPhone Archive (`ibackup`)

How to set up the development environment, the libraries used, and how to run the
tests. **Keep this document up to date as the code evolves.**

Target platform: **Windows 10/11 (64-bit)**, Python **3.11+**.

## 1. Prerequisites

- Python 3.11 or newer (64-bit) on the PATH.
- Apple **iTunes** or **"Apple Devices"** installed — provides the Apple Mobile
  Device USB driver used by `pymobiledevice3` to talk to the iPhone.
- Git.
- (For device testing) an iPhone + USB cable; unlock and **Trust** the PC.

## 2. Create and activate a virtual environment

**All development is done inside a Python virtual environment** (`.venv/`, which
is git-ignored). Never install project dependencies into the global interpreter.

PowerShell (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned
python -m pip install --upgrade pip
```

cmd.exe:

```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

Deactivate with `deactivate`. Recreate at any time by deleting `.venv/` and
repeating the steps above.

## 3. Install dependencies

Dependencies are declared in `pyproject.toml`. With the venv active:

```powershell
pip install -e ".[dev]"          # editable install + dev extras
```

### Runtime libraries

| Library | Purpose |
|---|---|
| `pymobiledevice3` | USB/AFC access to the iPhone (enumerate/pull/delete media, read `Photos.sqlite`). |
| `PySide6` | Qt GUI (thumbnail grid, multi-select, dialogs, threading). |
| `pillow-heif` (+ `Pillow`) | Decode HEIC/HEIF to generate cached thumbnails. |
| (stdlib) `sqlite3`, `hashlib`, `pathlib`, `json`, `argparse` | Catalog, hashing, paths, sidecars, CLI. |

### Dev / test libraries

| Library | Purpose |
|---|---|
| `pytest` | Test runner. |
| `pytest-qt` | GUI widget tests (Qt). |
| `pytest-cov` | Optional coverage. |
| `PyInstaller` | Build the portable Windows `.exe`. |

> Keep the tables above in sync with `pyproject.toml` whenever dependencies
> change.

## 4. Running the tests

**Run the tests after writing code for every module/todo** (see the workflow rule
in `plan.md` / `unit-tests.md`). With the venv active:

```powershell
pytest                              # whole suite
pytest tests\test_hashing.py        # a single file
pytest -k dedup                     # by keyword
pytest --cov=iphone_archive         # optional coverage

# GUI tests run headless via Qt's offscreen platform:
$env:QT_QPA_PLATFORM="offscreen"; pytest tests\test_gui.py
```

The suite runs **offline** with a fake device and temporary archives — no real
iPhone required.

## 5. Running the app during development

```powershell
ibackup --help                      # CLI (console entry point)
ibackup-gui                         # GUI (once implemented + sketch approved)
# or, without console scripts:
python -m iphone_archive.cli --help
```

## 6. Project layout

See `structure.md` for the full module map. Source lives under
`src/iphone_archive/`, tests under `tests/`.

## 7. Building the Windows executable

```powershell
pip install pyinstaller
pyinstaller packaging\ibackup.spec   # spec added during the packaging todo
```

## 8. Conventions

- Follow the repository coding rules (snake_case, 4-space indent, module-prefixed
  public functions, docstrings). See project instructions.
- No business logic in `cli.py` / `gui/` — call the `service/` layer.
- Update the relevant docs (`development.md`, `readme-user.md`, `structure.md`,
  `unit-tests.md`, `progress.md`) as part of each change.
