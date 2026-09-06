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
| `Pillow` + `pillow-heif` | Decode HEIC/HEIF and JPEG/PNG to generate the cached thumbnails in `.ibackup/thumbnails/`. |
| `typer` | CLI argument parsing, subcommands, and help text. |
| (stdlib) `sqlite3`, `hashlib`, `pathlib`, `json` | Catalog, hashing, paths, sidecars. |

### Dev / test libraries

| Library | Purpose |
|---|---|
| `pytest` | Test runner. |
| `pytest-qt` | GUI widget tests (Qt). |
| `pytest-cov` | Coverage measurement (enforced by CI, see §9). |
| `hypothesis` | Property-based tests for `name_safety` and hashing. |
| `ruff` | Linter + formatter (run via pre-commit and CI). |
| `mypy` | Static type checking (`--strict` on `core/` + `catalog/`). |
| `pre-commit` | Git hook runner (lint/format/type checks before each commit). |
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

### Exercising the CLI without an iPhone

Set `IBACKUP_FAKE_DEVICE` to a folder of ordinary files and every phone-side
command (`import`, `device-info`, `scan-phone`, `reclaim`) uses that folder as a
stand-in device. `IBACKUP_ARCHIVE` sets the default archive root, so `--archive`
can be omitted:

```powershell
$env:IBACKUP_ARCHIVE = "C:\temp\arch"
$env:IBACKUP_FAKE_DEVICE = "C:\temp\fakephone"
ibackup init C:\temp\arch
ibackup import -v
ibackup list
```

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
- **Conventional Commits** for messages (`feat:`, `fix:`, `docs:`, `test:`,
  `chore:`, `refactor:`…) so the project story is readable in git history.
- Record every significant decision as an ADR under `docs/adr/` (see its README).

## 9. Quality gates: pre-commit and CI

**Pre-commit hooks** run the fast checks locally before every commit. Enable once
per clone:

```powershell
pip install pre-commit
pre-commit install                  # installs the git hook
pre-commit run --all-files          # run against the whole tree on demand
```

Configured in `.pre-commit-config.yaml` (added during scaffold): `ruff` (lint +
format), `mypy`, and hygiene hooks (trailing whitespace, end-of-file, large-file
guard, merge-conflict check).

**Continuous integration** runs on a **`windows-latest`** GitHub Actions runner
(`.github/workflows/ci.yml`, added during scaffold) on every push / PR:

1. set up Python 3.11, create the venv, `pip install -e ".[dev]"`;
2. `ruff check` + `ruff format --check`;
3. `mypy` (`--strict` on `core/` and `catalog/`);
4. `pytest` (GUI headless via `QT_QPA_PLATFORM=offscreen`) with
   `--cov=iphone_archive`;
5. **coverage gate:** fail the build if total coverage drops below the configured
   threshold (target ~85%, with `core/` + `catalog/` held highest).

The same commands can be run locally before pushing to reproduce CI results.
