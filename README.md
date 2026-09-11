# iPhone Archive (`ibackup`)

A **Windows-targeted** photo archive project (CLI implemented; GUI in progress) that creates a permanent,
**append-only** archive of photos and videos from a USB-connected iPhone. Media
is stored as **plain files in album folders**, browsable in File Explorer
without the app. The archive — not the phone — is the source of truth.

> Status: **offline core-hardening complete**. Core and CLI implementations have
> offline fake-device tests; that is not real-iPhone or Windows release
> validation. The GUI sketch was approved on 2026-09-11; `ibackup-gui` opens a
> themed window shell, without archive operations yet. Mica is an opt-in
> Windows probe; normal launches use solid backgrounds. No downloadable Windows
> release is available. See [`docs/progress.md`](docs/progress.md)
> for validation evidence and remaining gates.

The GUI worker foundation now serializes archive work off the UI thread, with
cooperative cancellation and safe shutdown. Operation controls and gallery
models are still under development.

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
| [`docs/ui-sketch/`](docs/ui-sketch/README.md) | Approved GUI wireframes and clickable reference mock. |

## Quick start (developers)

See [`docs/development.md`](docs/development.md) for full details.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Quick start (users)

From a source installation (see the developer setup above). Use a disposable
archive and non-destructive checks until the Windows/iPhone validation matrix
passes; do not rely on this project as your only backup.

```powershell
ibackup init D:\iphone-archive
ibackup import --archive D:\iphone-archive
ibackup verify --archive D:\iphone-archive
```

See [`docs/readme-user.md`](docs/readme-user.md) for the full command reference.

## Tech stack

- Python 3.11+ · Typer (CLI) · PySide6 (GUI, in progress) · `pymobiledevice3`
  (iPhone/AFC) · SQLite · Pillow + `pillow-heif` (HEIC thumbnails) ·
  pytest / hypothesis / pytest-qt · ruff · mypy · PyInstaller.

## License

MIT.

Bundled dependencies retain their own licenses. A future Qt/icon distribution
must satisfy the notice and redistribution obligations in
[`ADR-0011`](docs/adr/0011-licensing-and-gui-contract-addendum.md).
