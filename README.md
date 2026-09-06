# iPhone Archive (`ibackup`)

A **Windows** desktop application (CLI **and** GUI) that creates a permanent,
**append-only** archive of photos and videos from a USB-connected iPhone. Media
is stored as **plain files in album folders**, browsable in File Explorer
without the app. The archive — not the phone — is the source of truth.

> Status: **Phase 0 (documentation)**. No application code yet. See
> `docs/plan.md` for the build plan and `docs/progress.md` for current status.

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

## Quick start (developers)

See [`docs/development.md`](docs/development.md) for full details.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Quick start (users)

See [`docs/readme-user.md`](docs/readme-user.md).

## Tech stack

- Python 3.11+ · PySide6 (GUI) · `pymobiledevice3` (iPhone/AFC) ·
  SQLite · `pillow-heif` (HEIC thumbnails) · pytest / pytest-qt · PyInstaller.

## License

TBD.
