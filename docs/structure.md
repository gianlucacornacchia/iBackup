# iPhone Archive — Project Structure

Status: Draft for review (Phase 0 documentation)

## 1. Repository layout

```
ibackup/
  pyproject.toml                 # packaging, dependencies, entry point, tool config
  README.md                      # short project README (points to docs/)
  docs/
    specifications.md
    readme-user.md
    user-stories.md
    structure.md                 # this file
    unit-tests.md
  src/
    iphone_archive/
      __init__.py
      cli.py                     # command entry points (thin adapter over service/)
      config.py                  # settings & archive-root resolution
      logging_setup.py           # logging configuration
      service/                   # headless application API for both frontends (CLI + GUI)
        __init__.py
        app_service.py           # facade: import, verify, dedup, albums, browse,
                                 #   select, mark-for-delete, move, delete, reclaim
        progress.py              # progress-reporting + cancellation interfaces
        results.py               # UI-agnostic result / DTO types
        selection.py             # multi-select operations; move/delete of many items
        marks.py                 # mark-for-delete queue (staged, explicit-commit)
      device/
        __init__.py
        device_manager.py        # detect/pair device, device info
        afc_client.py            # pymobiledevice3 AFC wrapper (list/pull/delete)
        media_source.py          # enumerate DCIM + PhotoData over AFC
      catalog/
        __init__.py
        database.py              # SQLite schema, migrations, connection
        models.py                # dataclasses: Asset, AssetFile, Album, ImportSession
        repository.py            # queries (by hash, by album, files to verify)
        sidecar.py               # per-asset JSON sidecar read/write
      core/
        __init__.py
        hashing.py               # streaming SHA-256
        name_safety.py           # Windows/cross-platform safe names + collisions
        archive_layout.py        # album-folder paths, atomic copy/hardlink placement
        importer.py              # incremental import orchestration
        dedup.py                 # duplicate detection & reporting
        verifier.py              # re-hash on-disk copies vs catalog
        albums.py                # parse Photos.sqlite -> album membership
        reclaim.py               # verify-before-delete phone space reclamation
        phone_diff.py            # detect archived assets no longer on the phone
        recycle.py               # move to / restore from / purge the Deleted/ folder
      browse/
        __init__.py
        gallery.py               # album/asset read models for the CLI and GUI
        thumbnails.py            # generate + cache thumbnails (HEIC via pillow-heif)
      gui/                       # PySide6 GUI — thin adapter over service/
        __init__.py
        app.py                   # QApplication bootstrap; ibackup-gui entry point
        main_window.py           # main window: albums sidebar + picture grid + toolbar
        album_list_view.py       # album navigation (list/tree) with counts
        picture_grid_view.py     # QListView icon-mode thumbnail grid, multi-select
        thumbnail_loader.py      # background thumbnail loading from archive files
        operations_controller.py # binds UI actions to service/ calls; progress/cancel
        reclaim_view.py          # "safe to delete from phone" list + confirm
        deleted_on_phone_view.py # review items gone from phone; purge or move-to-Deleted
        models.py                # Qt models wrapping service/ result DTOs
  tests/
    ...                          # unit tests (see docs/unit-tests.md)
```

File and directory names use lowercase with underscores, per project coding
rules.

## 2. Layered architecture

```
        +------------------+        +------------------+
        |      cli.py       |       |      gui/        |
        |  (thin adapter)   |       |  PySide6 (thin)  |
        +---------+---------+       +---------+--------+
                  |                           |
                  +------------+--------------+
                               |
                     +---------v---------+
                     |     service/      |   headless application API (facade):
                     |  app_service.py   |   import, verify, dedup, albums,
                     | progress + results|   browse/query, select, mark-for-delete,
                     +---------+---------+   move, delete, reclaim + progress/cancel
                               |
     +----------------+--------+-------+----------------+
     |                |                |                |
+----v----+     +-----v-----+    +-----v-----+    +-----v-----+
| device/ |     |  core/    |    | catalog/  |    | browse/   |
| (phone) |<--->| (logic)   |<-->| (SQLite + |    | (query +  |
|  AFC    |     |           |    |  sidecars)|    | gallery)  |
+---------+     +-----------+    +-----------+    +-----------+
```

- **`service/`** is a **headless application layer (facade)** that exposes every
  operation as a plain, UI-agnostic API returning structured result objects and
  emitting progress/cancellation events. **Both the CLI and the GUI are thin
  adapters over this layer**, guaranteeing the two frontends stay in parity.
- **`cli.py`** and **`gui/`** contain no business logic — they only translate
  user input into `service/` calls and render results.
- **`device/`** is the only layer that talks to the phone. It exposes a small
  interface (list media, pull a file, delete a file, read `Photos.sqlite`) so
  the rest of the app can be tested with a fake source.
- **`core/`** holds all business logic and is device-, service-, and UI-agnostic.
- **`catalog/`** owns persistence: the SQLite index plus JSON sidecars.
- **`browse/`** provides read-only query/presentation helpers (list albums,
  list/paginate pictures, resolve file paths for thumbnails, optional HTML
  gallery) that a GUI grid or a CLI listing can both consume.

## 3. Module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Resolve archive root and settings; validate the archive. |
| `logging_setup.py` | Configure logging to console and `.ibackup/logs/`. |
| `service/app_service.py` | Headless facade: exposes every operation (import, verify, dedup, albums, browse/query, select, mark-for-delete, move, delete, reclaim, deleted-on-phone review + purge/move-to-Deleted/restore) as UI-agnostic calls used by both the CLI and the GUI. |
| `service/progress.py` | Progress-reporting and cancellation interfaces for long operations (import/verify/reclaim), consumable by a CLI progress bar or a GUI progress dialog. |
| `service/results.py` | Structured, serializable result/DTO types returned to any frontend (no printing/formatting in core). |
| `service/selection.py` | Operate on multiple selected assets/albums at once (move, delete, mark). |
| `service/marks.py` | Manage the mark-for-delete queue: stage items, list staged, unmark, and commit deletions on explicit confirmation. |
| `device/device_manager.py` | Discover the device, report info, manage pairing. |
| `device/afc_client.py` | Wrap `pymobiledevice3` AFC: list, stream-read, delete. |
| `device/media_source.py` | Enumerate `/DCIM` and locate `PhotoData/Photos.sqlite`. |
| `catalog/database.py` | Create/migrate schema; provide connections. |
| `catalog/models.py` | Typed records passed between layers. |
| `catalog/repository.py` | All SQL queries; hash lookups; verify worklists. |
| `catalog/sidecar.py` | Serialize/deserialize per-asset JSON sidecars. |
| `core/hashing.py` | Streaming SHA-256 over file-like objects. |
| `core/name_safety.py` | Produce Windows-safe album/file names; collisions. |
| `core/archive_layout.py` | Compute destination paths; atomic copy/hardlink. |
| `core/importer.py` | Orchestrate the incremental import workflow. |
| `core/dedup.py` | Detect duplicates; report storage/multi-album cost. |
| `core/verifier.py` | Re-hash on-disk copies; report mismatches/missing. |
| `core/albums.py` | Parse `Photos.sqlite`; map assets to album names. |
| `core/reclaim.py` | Determine eligible phone files; delete on confirm. |
| `core/phone_diff.py` | Compare catalog to the latest phone scan; list assets deleted from the phone. |
| `core/recycle.py` | Move assets from `Photos/` to `Deleted/`, restore, and permanently purge; keep catalog `archive_state`/`asset_files.location` in sync. |
| `browse/gallery.py` | Album/asset read models: list albums with counts, list/page assets, unsorted and recycled views. |
| `browse/thumbnails.py` | Generate and cache JPEG previews under `.ibackup/thumbnails/<sha256>_<size>.jpg` (HEIC via `pillow-heif`); originals are only read. Unsupported media (video) reports a placeholder result. |
| `cli.py` | Thin adapter: map subcommands to `service/` calls; format output. |
| `gui/` | PySide6 thin adapter: bind widgets to the same `service/` calls; thumbnail grid, album navigation, multi-select, move/delete/mark, reclaim view, progress/cancel. |

## 4. Data flow — import

```
phone (AFC)                 core                         catalog / disk
-----------                 ----                         --------------
media_source.enumerate() -> importer
  for each asset:
    afc_client.read() ----> hashing.sha256() (streaming)
                            repository.exists(sha256)? --> skip if yes
                            albums.membership(asset) ----> Photos.sqlite (best-effort)
                            name_safety.safe_name()
                            archive_layout.place() ------> Photos/<Album>/file  (atomic)
                            verifier.reverify(stored) ---> compare to source hash
                            sidecar.write() -------------> .ibackup/sidecars/<sha256>.json
                            repository.commit() ---------> catalog.sqlite (assets, asset_files)
importer.summary() -------> import_sessions row
```

## 5. Data flow — reclaim

```
reclaim --dry-run/--confirm
  repository.list_archived_phone_assets()
  for each candidate:
    verifier.verify(archive copy)  -> must pass
  present eligible list
  if --confirm and user confirms:
    afc_client.delete(phone path)  -> never touches archive
```

## 6. Key conventions

- No symlinks are ever created in the archive.
- All destination writes are atomic (write to `.ibackup/tmp`, then rename).
- The catalog is written transactionally; a crash cannot half-record an asset.
- The `device/` interface is dependency-injected so `core/` is unit-testable
  without a real phone.
- Public functions are prefixed with their module concept where helpful
  (e.g. `archive_place_asset`, `catalog_find_by_hash`), per coding rules.
- **Frontend-agnostic core:** no `print()`/formatting or UI concerns below the
  adapter layer. `service/` returns structured results and emits progress events;
  the CLI and GUI decide how to render them.

## 6a. Frontend Parity (CLI + GUI)

Both frontends are thin adapters over `service/`, so they stay in lock-step:

- **Single source of behavior:** every operation lives in `service/app_service.py`.
  The CLI (`ibackup`) and the GUI (`ibackup-gui`) are both adapters over the same
  API — guaranteeing **the GUI can do everything the CLI can**, and vice versa.
- **Structured results, not text:** `service/results.py` returns typed DTOs
  (e.g. album summaries, asset records with on-disk paths for thumbnails,
  operation reports); the GUI wraps them in Qt models and the CLI prints them.
- **Progress + cancellation:** long-running operations (`import`, `verify`,
  `reclaim`) accept a progress/cancel handle from `service/progress.py`; the GUI
  renders a progress dialog with cancel, the CLI a progress line.
- **Selection & batch ops:** `service/selection.py` supports acting on many
  selected pictures/albums at once (move, delete, mark-for-delete); the GUI grid
  provides multi-select, the CLI accepts multiple targets.
- **Mark-for-delete queue:** `service/marks.py` stages items marked for deletion;
  nothing is removed until an explicit commit — matching the append-only safety
  model and the GUI "review before delete" flow.
- **Phone-safe-to-delete view:** the reclaim eligibility query (archived +
  verified) is exposed as data, rendered by the GUI reclaim view and by
  `reclaim --dry-run`.

## 7. External dependencies

- `pymobiledevice3` — USB/AFC access to the iPhone.
- `PySide6` — Qt GUI (Windows).
- `pillow-heif` (+ `Pillow`) — decode HEIC/HEIF to generate cached thumbnails.
- Python standard library: `sqlite3`, `hashlib`, `pathlib`, `json`, `argparse`
  (or `typer` if adopted for the CLI).
- Test tooling: `pytest` (with `pytest-qt` for GUI widget tests).
- Packaging: `PyInstaller` for a portable Windows build (optional MSIX installer).
