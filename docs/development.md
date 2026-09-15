# Development Guide — iPhone Archive (`ibackup`)

How to set up the development environment, the libraries used, and how to run the
tests. **Keep this document up to date as the code evolves.**

Target platform: **Windows 10/11 (64-bit)**, Python **3.11+**.

Current evidence is offline core/CLI testing, not a validated Windows/iPhone
release. The GUI sketch was approved on 2026-09-11; the shell, theme and worker
are implemented offline. Live Windows Mica/chrome qualification is still
pending. See `progress.md` for evidence and remaining gates.

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
| `PySide6` | GUI shell/theme layer. **6.7+ required** for native `windows11` style and palette accent; explicit native color-scheme hints are used where available (Qt 6.8+). |
| `darkdetect` | Reserved dependency; live theme detection currently uses Qt hints and Windows preferences, without a listener thread. |
| `Pillow` + `pillow-heif` | Decode HEIC/HEIF and JPEG/PNG to generate the cached thumbnails in `.ibackup/thumbnails/`. |
| `av` (PyAV) | Extract video poster frames for the thumbnail cache. Its wheels bundle FFmpeg, so **no system FFmpeg install is needed** on Windows. Imported lazily: if it is missing, videos fall back to a placeholder instead of breaking image thumbnails. |
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

`pymobiledevice3` is pinned to **`11.10.4`**, whose async AFC API was inspected
during device hardening. Upgrades require adapter compatibility tests rather
than assuming API stability. The adapter's sync-shaped test clients are
fixtures, not proof of legacy-library support.
Real iOS album schema/WAL consistency and hash-to-unlink races remain hardware
validation items, with real AFC deletion gated.

## 4. Running the tests

**Run the tests after writing code for every module/todo** (see the workflow rule
in `plan.md` / `unit-tests.md`). With the venv active:

```powershell
pytest                              # whole suite
pytest tests\test_hashing.py        # a single file
pytest -k dedup                     # by keyword
pytest --cov=iphone_archive         # optional coverage

```

`tests/test_gui.py`, `tests/test_gui_theme.py`, `tests/test_gui_worker.py`,
`tests/test_gui_models.py`, `tests/test_gui_previews.py`,
`tests/test_gui_shell.py`, `tests/test_gui_gallery.py` and
`tests/test_gui_operations.py`
run headless: they set `QT_QPA_PLATFORM=offscreen` on import, so GUI tests need
no display and are part of the normal `pytest` run.
They skip automatically if PySide6 or pytest-qt is missing.
`tests/test_win32_effects.py` tests the guarded native API with mocks on any
host; this is not evidence of Windows rendering.

### Running the UI mock

A clickable mock of the whole interface lives in `docs/ui-sketch/mockup/`:

```powershell
python docs\ui-sketch\mockup\run_mock.py           # click through it
python docs\ui-sketch\mockup\capture_screens.py    # re-render the screenshots
```

It needs only `PySide6` (already a project dependency). It uses fake data,
imports nothing from `iphone_archive`, and is deliberately **excluded from
`ruff`, `mypy` and `pytest`** because it is a throwaway review artifact, not
application code. Rendered light/dark reference screens are in
`docs/ui-sketch/mockup/screens/`.
Ruff's `extend-exclude` explicitly excludes that directory, including when CI
runs `ruff check .` and `ruff format --check .`; application GUI code and tests
remain included.

The suite runs **offline** with a fake device and temporary archives — no real
iPhone required.

### Exercising the CLI without an iPhone

Set `IBACKUP_FAKE_DEVICE` to a folder of ordinary files and every phone-side
command (`import`, `device-info`, `scan-phone`, `reclaim`) uses that folder as a
stand-in device. `IBACKUP_ARCHIVE` sets the default archive root, so `--archive`
can be omitted. `IBACKUP_CONFIG_DIR` redirects the user settings file, which is
how the test suite stays isolated from your real profile (an autouse fixture in
`conftest.py` sets it for every test):

```powershell
$env:IBACKUP_ARCHIVE = "$PWD\scratch\arch"
$env:IBACKUP_FAKE_DEVICE = "$PWD\scratch\fakephone"
# Create/populate scratch\fakephone with disposable test files first.
ibackup init .\scratch\arch
ibackup import -v
ibackup list
```

Use a project-local test scratch directory if system temporary directories are
prohibited. Fake-device confirmed reclaim is destructive to the in-memory
fixture for that invocation; it is not a hardware deletion validation.
Settings are isolated by the test fixture; never use personal media as a fixture.

## 5. Running the app during development

```powershell
ibackup --help                      # CLI (console entry point)
# or, without console scripts:
python -m iphone_archive.cli --help
```

The desktop interface has its own entry point:

```powershell
ibackup-gui                         # GUI (gui-scripts entry point)
# or, without console scripts:
python -m iphone_archive.gui.application
```

It is being built in the twelve steps listed in `plan.md` §2b, so it currently
opens the window shell without archive features wired up yet.
The worker backbone is installed but lazy: launching the shell does not start
archive work, select an archive or connect a phone.

Set `ibackup config set theme system` (or `light` / `dark`) before launching.
The GUI reads this preference at startup; system theme/accent changes are
applied live. Windows accessibility/transparency preferences are polled every
two seconds on the GUI thread because Qt 6.7 lacks those notifications.
High-contrast mode removes scoped QSS and releases explicit color-scheme
overrides; no background listener thread or archive service is involved.

### Using the GUI worker from later views

`MainWindow.worker` is the GUI-thread-owned `WorkerController`. Connect its
signals before submitting requests. `worker_open(path, create=False)` explicitly
opens an archive; pass `create=True` to initialize one. Switch archives by
submitting `close_archive` before the next open. The archive-scoped dispatcher
requires an open session for `app_service_*` calls; standalone settings/device
screens and archive-selection controls remain later GUI steps.

`worker_submit("app_service_list_assets", {"limit": 128, "offset": 0})` returns
a request ID. Parameters and DTO results are recursively detached; live
widgets, SQLite connections, services, sources and caller-owned progress handles
are rejected. Device-using calls construct and close their source on the worker;
tests inject a context-manager factory rather than a GUI-created device.

| Signal | Payload |
|---|---|
| `result_ready` | `WorkerResult(request_id, operation, value, cancelled=False)` |
| `cancelled` | `WorkerResult` with acknowledged cancellation and any partial result |
| `failed` | `WorkerFailure` with request ID, operation, error type/message and traceback text; ID 0 denotes shutdown failure |
| `progress_changed` | Request ID and the latest immutable `ProgressEvent` |
| `request_submitted` | Request ID and operation; synchronous GUI-side notification after acceptance, used to invalidate model scopes before any reply is delivered |
| `stopped` | The thread has finished and been joined (also emitted for shutdown before first use) |

Delivery to the controller is explicitly queued onto the GUI thread. At most 32
requests can remain outstanding; overflow raises instead of dropping work.
Progress is coalesced to one outstanding notification per request, with the
existing last-256 history retained. `worker_cancel(request_id)` sets the shared
Event immediately, without relying on the busy worker's event loop. Cancellation
is not rollback: pending work is skipped, running work stops only at service
checkpoints, and a completed operation is not relabelled cancelled.

Window close calls nonblocking `worker_shutdown()` and remains alive until
`stopped`. The application also shuts down and joins in `finally` if `app.quit()`
bypasses window close. `worker_wait(timeout_ms)` is for teardown after shutdown;
a timeout warns and leaves the thread alive. Final process exit waits for safe
completion, even if a device call has not returned; never use `QThread.terminate()`.
Expected operation failures preserve the session. Unexpected failures release
it and fail pending requests without replay; a request after `stopped` starts a
fresh worker and must explicitly reopen the archive.

### Using the paged models from later views

`MainWindow.models` owns `assets`, `albums` and the shared `selection`
(`QItemSelectionModel`). The window constructs them without opening an archive
or loading rows. After a successful worker open, call `fetchMore()` on a model
when `canFetchMore()` permits it. `rowCount()` and `data()` read cached metadata
only; no SQLite access or thumbnail decoding occurs on the GUI thread.

`AssetScope()` lists active assets; `AssetScope("album", album_id)`,
`AssetScope("unsorted")` and `AssetScope("recycled")` choose other scopes through
`asset_model_set_scope()`. Pages default to 128 rows (configurable 1-512), with
one extra lookahead row to determine whether another page exists. Each model
has at most one outstanding request; already fetched metadata remains cached
until reset. This bounds individual queries, not total metadata after browsing
an entire library. The thumbnail cache is a separate step.

Connect `loading_changed`, `error_changed` and `page_loaded` for view updates.
Failures stop automatic paging; `model_retry()` retries the same offset.
Accepted archive mutations reset models and invalidate selections before any
reply is delivered; fetching resumes only after all such requests finish.
Reentrant Qt insert/reset callbacks cannot fetch or submit stale selections.

Use `asset_model_selection(indexes)` to capture an immutable snapshot, then
`asset_model_selection_parameters(snapshot)` immediately before submitting a
copy-scoped service mutation. This returns explicit `asset_ids` and `file_ids`;
never omit the file IDs to turn an album selection into an asset-wide action.
Snapshot validation rejects changed archives, generations and scopes. For proxy
views, capture `QPersistentModelIndex(index)` while each index is current and
pass those persistent indexes, not ordinary proxy indexes retained over resets.

Targeted validation, using the existing venv and dependencies:

```powershell
pytest tests/test_gui_models.py tests/test_gui_worker.py tests/test_gui.py tests/test_gallery.py tests/test_albums.py tests/test_service.py
```

### Using the preview loader from later views

`MainWindow.previews` is a `PreviewLoader`. Call
`previews_entry(sha256, relative_path)` from a delegate or view with the values
already carried by an asset row (`AssetRole.SHA256` and one entry of
`AssetRole.PATHS`). It never touches the disk on the GUI thread: it returns a
ready entry with a `QPixmap`, a failed entry with an error to paint as a
placeholder, or a pending entry, scheduling one background render.

Previews deliberately bypass the service worker. That worker holds the archive
lock and serialises the catalog, so routing tiles through it would blank the
grid during an import and flood its 32-slot queue while scrolling. Pool threads
receive the archive root, the hash and a relative path only; never a connection,
service, device or widget.

Connect `preview_ready(sha256, size)` and `preview_failed(sha256, size, error)`
and repaint the affected tiles. After scrolling, call
`previews_cancel_stale(visible_and_prefetched_hashes)` so work for tiles that
left the viewport is dropped before it starts. Use `previews_set_size()` when
the `thumbnail_size` setting changes and `previews_retry()` to forget failures.
The window rebinds `previews_set_archive()` whenever the open archive changes,
which clears the cache because identical hashes resolve to different files in a
different archive.

Targeted validation, using the existing venv and dependencies:

```powershell
pytest tests/test_gui_previews.py tests/test_thumbnails.py tests/test_gui.py
```

### Extending the shell with new views and commands

`MainWindow.shell` is an `ArchiveShell`. It owns the navigation pane, the page
stack, the command bar and the status line, and deliberately owns no archive
data: counters come from `app_service_stats`, album rows are pumped out of the
shared paged album model, and both are re-read when the models' mutation
barriers clear. Never query the catalog from a shell method - submit through
the worker like `shell_refresh` does.

To add a page, add a `NavigationView` to `LIBRARY_VIEWS` (or emit an album key
through `navigation_album_key`) and map it in `VIEW_SCOPES` so selecting it
points the shared asset model at the right scope. `shell_page()` creates the
page lazily; replace its placeholder body in the step that implements the view.

To add a command, add a `CommandSpec` in `gui/commands.py` naming the service
operation it performs. A test fails if a command names an operation the worker
does not accept, which is what keeps the GUI from drifting away from the CLI.
Set `requires_archive`/`requires_phone` rather than disabling buttons by hand,
and put secondary verbs in the overflow menu with `overflow=True`.

Phone presence has no cheap probe: the only device call enumerates the whole
library, which took about 36 seconds on the test iPhone. The state therefore
stays `unknown` until a device operation succeeds or fails, and unknown keeps
commands enabled rather than blocking the user.

Icons are drawn by `gui/icons.py` in the caller's colour, so add a glyph there
instead of bundling an image; unknown glyph names raise rather than drawing a
blank icon.

Targeted validation, using the existing venv and dependencies:

```powershell
pytest tests/test_gui_shell.py tests/test_gui_models.py tests/test_gui.py tests/test_gui_theme.py
```

### Extending the gallery and the viewer

`ArchiveShell` hosts one `AssetGallery`, because there is one shared
`AssetModel`. `shell_apply_state` re-parents it into the page being shown and
must release the previous host, or the old page keeps a dangling reference.

`AssetGrid` is icon mode with extended selection and a rubber band. Tiles are
painted by `TileDelegate`, never built as widgets, so a 200 000-asset archive
costs only what is on screen. `TileDelegate.paint` must stay I/O-free: call
`previews_entry()` and paint whatever it returns. It also swallows that call's
`ValueError`, because an exception raised during Qt painting is extremely
disruptive.

Selection verbs live in `SELECTION_ACTIONS` and are gated per scope by
`VIEW_ACTIONS` in `gui/shell.py`; the selection bar and the context menu are
both generated from that table so they cannot drift apart. Add a verb in one
place. `shell_gallery_action` captures the selection **on the GUI thread, at
click time**, as an `AssetSelection` of exact asset and file IDs bound to the
model generation, so an operation started later acts on the copies the user
actually saw and a reset in between is refused rather than silently retargeted.

Two constraints worth keeping:

- Never scan every loaded row to find what is visible. `grid_anchor_row()`
  probes the viewport with `indexAt` and walks outward until the first tile
  past the area; the full scan measured 37.6 ms at 20 000 rows, twice per
  scroll event, which defeats the point of a paged model.
- Never use a bare `QTimer.singleShot` bound to a method of a destroyable
  object. Use a child timer (like the grid's `pump_timer`) so the timer dies
  with its owner; a deferred call into a destroyed model or worker aborts the
  process.

The viewer owns a **second** `PreviewLoader` at `VIEWER_PREVIEW_SIZE` with a
tiny cache. Sharing the grid's loader would either evict every tile on each open
or scale a 256 px thumbnail up. `ViewerDialog` sets `WA_DeleteOnClose`, and
closes itself on `modelReset` because "row 12" then means a different asset.

Offscreen tests must not call `QMenu.exec`; it hangs the suite in a modal loop.
Build the menu with `gallery_build_menu()` and assert on it.

Targeted validation, using the existing venv and dependencies:

```powershell
pytest tests/test_gui_gallery.py tests/test_gui_shell.py tests/test_gui_previews.py tests/test_gui_models.py
```

### Adding a new operation surface

`MainWindow` routes every verb. A long operation goes through
`main_window_start`, which submits one request and hands the accepted request ID
to an `OperationDialog`; a short read goes through `main_window_start_quiet`,
which reports a single status line. Both funnel into `main_window_submit`, so a
refused request - a full queue, a worker shutting down - is reported as "could
not start" and held on screen rather than raising into Qt.

To add an operation: put a `CommandSpec` in `gui/commands.py`, list the key in
`DIALOG_COMMANDS` or `QUIET_COMMANDS`, and add a summary builder to
`SUMMARY_BUILDERS` in `gui/operations.py`. An operation with no builder still
reports completion rather than raising, because that text is produced while the
user is waiting for a result.

Rules that are easy to get wrong here:

- **Never hand-list which operations can be cancelled.** Only a service method
  that takes a `ProgressHandle` ever observes the cancel event.
  `operations_cancellable()` derives the set from the real signatures; a
  hand-written set already drifted once, and the failure mode is a Cancel button
  that silently does nothing.
- **Clear an owner's reference to a self-deleting dialog on `destroyed`, not
  `finished`** - `finished` does not fire on every close path. Bind the identity
  (a request ID or token) at connect time, because the object is destroyed one
  event-loop turn *after* it closes and may already have been replaced; an
  unconditional handler will then orphan the live dialog.
- **A hidden operation's summary must be sticky.** The status bar is the only
  place it is reported, and the mutation that produced it makes the shell re-read
  its counters, which would otherwise overwrite it immediately.
- **Show dialogs; never `exec` them.** A nested modal loop inside a GUI that owns
  a worker thread, a preview pool and a paged model can process a reply in the
  middle of another operation, and it hangs the offscreen suite. Because prompts
  are non-blocking, re-check an `AssetSelection` with
  `asset_model_selection_parameters` when the user confirms, not when the prompt
  was shown.
- **Quiesce the preview pools before deleting anything they read.** They
  deliberately bypass the service worker, so "Clear previews" would otherwise
  unlink files three pool threads have open - a sharing violation on Windows.

Targeted validation, using the existing venv and dependencies:

```powershell
pytest tests/test_gui_operations.py tests/test_gui_shell.py tests/test_gui_gallery.py tests/test_gui_worker.py
```

### Running the Windows Mica probe

Normal launches retain opaque client painting. On Windows 11 22H2+ only:

```powershell
python -m iphone_archive.gui.application --mica-probe
```

This explicit experiment enables translucent Qt painting and requests a DWM
client-frame extension plus Mica. It retains the system title bar (no frameless
flag). Success HRESULTs are not visual proof: verify wallpaper tint behind
content, readable text, resize/maximize/snap edges, rounded corners and dark
caption in both themes. Also exercise high contrast, transparency off and
battery saver; the fallback must be solid/readable, not black or transparent.
Record the Windows build, Qt version, screenshots and DWM logs before enabling
this painting path by default. On Windows 10/older builds, unsupported effects
fall back; the probe command is rejected off Windows. It has **not** been
visually validated on this Linux development host.

## 6. Project layout

See `structure.md` for the full module map. Source lives under
`src/iphone_archive/`, tests under `tests/`.

## 7. Building the Windows executable

**Scheduled release work, not an available installer/download.** There is no
PyInstaller spec in this remediation. The packaging milestone must first add a
CLI-only recipe, then document its actual build command and run it on Windows.
Do not invoke a nonexistent `packaging/ibackup.spec`.

A Linux build is not a Windows executable. Record clean-machine launch/help/
offline-import smoke tests, artifact version and dependency/license notices
before advertising a release. GUI bundling waits for implementation/qualification;
review Qt LGPL replacement/relinking obligations and icon notices (ADR-0011).
MSIX/signing are release decisions, not currently provided deliverables.

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
3. `mypy --strict` on the scope declared in the checked-in workflow/tool configuration;
4. `pytest` (GUI headless via `QT_QPA_PLATFORM=offscreen`) with
   `--cov=iphone_archive`;
5. **coverage gate:** fail the build if total coverage drops below the configured
   threshold. Read `pyproject.toml`/workflow for the current value rather than
   treating an old percentage as evidence.

The workflow is configured, not proof of an observed successful Windows run.
Record real execution results in `progress.md`. See `unit-tests.md` for device,
recovery, worker-ownership and release checks that unit coverage cannot replace.
