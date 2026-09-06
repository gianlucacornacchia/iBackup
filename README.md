# iPhone Archive (`ibackup`)

A **Windows** desktop application (CLI **and** GUI) that creates a permanent,
**append-only** archive of photos and videos from a USB-connected iPhone. Media
is stored as **plain files in album folders**, browsable in File Explorer
without the app. The archive — not the phone — is the source of truth.

> Status: **Phase 1 complete** — the core engine and the full `ibackup` CLI are
> implemented and tested (179 tests, 91% coverage). The GUI is next and is
> **blocked on UI-sketch approval**. See `docs/plan.md` for the build plan and
> `docs/progress.md` for current status.

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/readme-user.md`](docs/readme-user.md) | End-user guide (install, commands, browsing). |
| [`docs/specifications.md`](docs/specifications.md) | Functional & technical specification. |
| [`docs/structure.md`](docs/structure.md) | Architecture & module layout. |
| [`docs/user-stories.md`](docs/user-stories.md) | User stories & acceptance criteria. |
| [`docs/unit-tests.md`](docs/unit-tests.md) | Test plan. |
| [`docs/development.md`](docs/development.md) | Dev environment, libraries, running tests. |
| [`docs/plan.md`](docs/plan.md) | Consolidated implementation plan. |
| [`docs/todos.md`](docs/todos.md) | Build checklist with dependencies/status. |
| [`docs/progress.md`](docs/progress.md) | Resumable progress log (update as you work). |
| [`docs/ui-sketch/`](docs/ui-sketch/README.md) | GUI wireframes — **awaiting approval** before any GUI code. |

## Quick start (developers)

See [`docs/development.md`](docs/development.md) for full details.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Quick start (users)

```powershell
ibackup init D:\iphone-archive
ibackup import --archive D:\iphone-archive
ibackup verify --archive D:\iphone-archive
```

See [`docs/readme-user.md`](docs/readme-user.md) for the full command reference.

## Tech stack

- Python 3.11+ · Typer (CLI) · PySide6 (GUI, pending) · `pymobiledevice3`
  (iPhone/AFC) · SQLite · Pillow + `pillow-heif` (HEIC thumbnails) ·
  pytest / hypothesis / pytest-qt · ruff · mypy · PyInstaller.

## License

MIT.
