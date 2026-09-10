# iPhone Archive — Project Structure

Status: current core/CLI module map plus explicitly planned GUI contracts.
Implementation presence does not establish hardware or crash-safety validation;
see [progress](progress.md) and [test plan](unit-tests.md).

## 1. Current modules

All paths below are relative to `src/iphone_archive/`.

| Path | Responsibility |
|---|---|
| `cli.py` | Typer adapter, archive selection, confirmation prompts, result rendering. |
| `config.py` | Archive paths and initialization. |
| `settings.py` | Per-user persisted settings, validation, default/recent archives. |
| `logging_setup.py` | Rotating CLI command start/completion/error log, configured level and handler cleanup. |
| `service/app_service.py` | Headless `AppService` facade; `app_service_device_info(source)` returns `DeviceInfo(udid, media_count)` after full enumeration. |
| `service/archive_lock.py` | Exclusive archive-session/process lock. |
| `service/progress.py` | `ProgressEvent`, `ProgressHandle`, Event cancellation and bounded last-256 history snapshots. |
| `service/selection.py` | Batch archive moves and `SelectionResult`. |
| `service/marks.py` | Staged deletion queue, `MarkSummary`, `MarkCommitResult`. |
| `device/interface.py` | Injectable `MediaSource` protocol. |
| `device/afc_device.py` | `AfcDevice`: discovery/pairing, AFC media enumeration, streaming, best-effort album extraction. |
| `device/fake_device.py` | Offline `FakeDevice` for tests and CLI exercises. |
| `catalog/database.py` | SQLite connection, schema initialization and upgrade handling. |
| `catalog/models.py` | `Asset`, `AssetFile`, `Album`, `ImportSession`, `DeletionMark`, `PhoneItem`, state enums. |
| `catalog/repository.py` | Catalog queries, identities, membership, scan state. |
| `catalog/sidecar.py` | JSON metadata serialization and `SidecarData`. |
| `core/hashing.py` | Chunked SHA-256. |
| `core/name_safety.py` | Windows-safe names and collision handling. |
| `core/archive_layout.py` | Copy/hardlink placement and `PlacedFile`. |
| `core/file_operations.py` | Journaled archive edit preflight, placement, rollback/finalization and sidecar recovery. |
| `core/importer.py` | Incremental import, placement, catalog/sidecars, `ImportResult`. |
| `core/albums.py` | Archive album queries and `AlbumSummary` (not the phone database parser). |
| `core/dedup.py` | Read-only storage report, `DuplicateGroup`, `DedupResult`. |
| `core/verifier.py` | Verify all cataloged copies, `VerifyIssue`, `VerifyResult`. |
| `core/phone_diff.py` | Device inventory reconciliation, `DeletedFromPhoneItem`, `PhoneDiffResult`. |
| `core/reclaim.py` | Selected/all-candidate preview and guarded deletion, `ReclaimCandidate`, `ReclaimResult`. |
| `core/recycle.py` | Move to Deleted, restore, purge, `RecycleResult`. |
| `browse/gallery.py` | Album/asset listings and `AssetView`; aligned `file_ids`/`paths` filtered by current album/location, including partially recycled assets; **no HTML generator**. |
| `browse/thumbnails.py` | Cached previews and `ThumbnailResult`: still images via Pillow/pillow-heif, video poster frames via PyAV (display-matrix rotation applied, dark opening frames skipped). Previews only — never transcodes or modifies originals. |
| `gui/__init__.py` | Placeholder package only; no implemented GUI or GUI entry point. |

DTOs live with their owning modules above. There is no `service/results.py`,
`device_manager.py`, `afc_client.py`, or `media_source.py`.
Repository metadata/tool configuration is in `pyproject.toml`, `.github/`, and
`.pre-commit-config.yaml`; tests are inventoried in `unit-tests.md`.

## 2. Layering and data flow

```text
CLI (current) / GUI (planned)
              |
        service/AppService
              |
       core + browse + catalog
              |
       injectable MediaSource
              |
       AfcDevice / FakeDevice
```

The service owns the archive session and connection. Frontends translate input
and render results; persistence and destructive eligibility stay below them.
Settings are outside the archive; media, catalog, sidecars and recovery data
travel together. Plain media remains viewable without SQLite or this app.

Import: enumerate device metadata → device-scoped fast-skip checks → stream
new/changed bytes into archive staging while hashing → verify/place each copy
→ persist sidecar/catalog/session state. Album growth is append-only.
Fast-skip is not evidence that a current phone file still has identical bytes.

Reclaim: obtain current device inventory → restrict to requested asset IDs if
provided → verify active archive copies and current source identity/content
→ preview → explicit confirmation and execution-time revalidation. Real AFC
deletion remains gated by the Windows/iPhone matrix; no flag bypasses it.

An atomic file rename or SQLite transaction alone cannot make a filesystem +
database operation atomic. Core hardening must provide rollback/recovery for
partial multi-copy placement, recycle, restore, purge and sidecar updates.
`file_operations.py` journals edits under `.ibackup/operations/`; service open
attempts recovery of provably owned interrupted edits, preserving conflicting
files under
`.ibackup/operation_conflicts/`. This does not prove all import or power-loss
failure cases are covered.
Imports separately journal each item under `.ibackup/import-journals/`, using
schema-v2 `import_commits` markers. Service initialization/open now runs schema
initialization → `importer.importer_recover(connection, paths)` →
`file_operations.file_operations_recover(connection, paths)` under the archive
session lock. Import also invokes its recovery before work.
Use catalog-derived sidecars so membership/file updates stay represented.
The immutable fsynced intent owns a private staging directory before media
creation, while originals remain intact. Bounded per-file ownership records
persist staged device/inode identity before no-clobber publication. This avoids
both the creation/ownership crash window and quadratic whole-batch journal
rewrites. Windows uses native rename; POSIX uses hardlink publication and refuses
unsupported filesystems rather than copying into an unowned public destination.
Recovery refuses ambiguous or externally replaced files, even byte-identical
replacements; ordinary staging creation/ownership-write failures can roll back.
A SQLite `meta` commit marker commits with file rows/marks; recovery rolls back
precommit destinations or finishes committed source cleanup and sidecars.
Purge stages copies until commit. Allow temporary extra space for these copies.
Preserve `.ibackup/import-staging/` with the import journals while any operation
is unfinished.
Recovery checks identity and content before destructive cleanup and fails
explicitly on ambiguous ownership or changed/damaged data. Serialization
coordinates app sessions, not external file
managers; it does not provide instantaneous whole-batch filesystem visibility.
Never describe a batch as all-or-nothing unless failure-injection tests prove
that boundary. No destructive action may discard the last good copy on error.

## 3. Archive and identity contracts

- No archive symlinks; resolve and validate paths before writing/deleting.
- One open service session per archive, protected by an OS-exclusive lock
  across processes, including read operations. Competing sessions are rejected
  as busy, not queued. Thread ownership is enforced before SQLite access.
- Source identity must include device identity, not only a phone path or asset
  ID. Multiple phone identities may refer to the same SHA-256 content.
  Schema-v2 `source_identities` records many device/path/content mappings.
  Repository identity lookup requires device UDID and modification time;
  missing provenance fails closed, and v1 content rows gain no fabricated
  provenance during migration.
- A failed/cancelled/incomplete scan must not publish absence. Reclaim uses
  fresh device-scoped matches, not global `present_on_phone` alone.
- Schema changes need versioned, transactional migrations and upgrade tests.
  Unscoped legacy identities are not trusted for skip, absence or deletion;
  require renewed device-scoped import/content validation. Schema v2 stores
  device/path source identities; unchanged size/mtime supports trusted lookup,
  not proof of current bytes for deletion. Newer unsupported schemas fail closed.
- Verification includes recycled copies; active archive presence is required
  for phone reclaim. Catalog repair from sidecars remains separate future work.
  An asset remains active while any `Photos/` copy exists; `asset_albums` tracks
  active folders. Recycled views include partially recycled assets.
  Deleted copies retain their original `asset_files.album_id` for restoration;
  `recycle_purge(..., recycled_only=True)` preserves all active copies.
- Selection must preserve scope: asset marks cover the asset, album marks its
  album copies, and `target_type="file"` marks one copy. `list --files` exposes
  aligned IDs/paths for the current filter. Moves default to all active copies;
  `--from-album` restricts the source. Per-copy commits preserve other copies,
  memberships and sidecars.
  Default moves leave Deleted copies unchanged; explicit `file_ids` that do
  not match the requested assets/location are rejected.
  Service move/recycle/restore/purge accepts optional `file_ids`; CLI adapters
  expose repeated `--file ID` while retaining required positional asset IDs.
  `app_service_purge` also accepts `recycled_only`. Marks commit delegates
  scoped edits once and returns its `recycle_result`; it does not delete the
  resolved asset IDs a second time.
- Sidecars now record `archive_state` and actual copy path/location, album
  ID/name and link mode; reads remain compatible with older sidecar data.

Device hardening must adapt supported asynchronous `pymobiledevice3` APIs
without per-chunk event-loop creation: a persistent loop owns the AFC session,
bounded `fopen`/`fread`/`fclose` reads, and deterministic `device_close`/
context-manager cleanup. Adapter implementation/tests are not hardware proof.
`AfcDevice(udid=...)` retains its constructor; first use establishes worker
affinity. Missing/inaccessible media directories are errors, not a valid empty
inventory. Source verification and per-device scan publication are separate;
only a complete successful scan publishes absence.

## 4. Future GUI execution contract — blocked

No GUI code, entry point, theme module or Mica probe is authorized until the
user explicitly approves the sketch. Review fixes are not that approval.

After approval:

- Create/open/use/close `AppService` and its SQLite connection **in the worker
  thread that owns them**. Never share a service/connection between QThreads,
  and do not defeat SQLite thread checks. Prefer a single serialized archive
  worker. The service rejects competing sessions as busy; any UI-side queue
  must route work through that same owning worker, not open another session.
- Use `threading.Event` cancellation; emit progress/results through queued Qt
  signals. Worker callbacks must never touch widgets directly. Shutdown
  cancels, waits for safe completion, then closes the worker-owned session.
  The current progress handle retains snapshots of only the last 256 events;
  it is not an unbounded event log.
- Bound thumbnail workers, pending requests and decoded-image caches; request
  visible/prefetch tiles only, discard stale requests, and paginate metadata.
  Independent thumbnail workers receive immutable paths/DTOs, not SQLite.
- `gui/theme.py`, `win32_effects.py`, `main_window.py`, `navigation_pane.py`,
  `command_bar.py`, `picture_grid_view.py`, `thumbnail_loader.py`,
  `operations_controller.py`, review/settings views and Qt models are
  **planned names, not existing files**.
- DWM failures must log the attribute/result and select a solid background.
  Probe Mica only after approval on Windows 11 22H2+; no probe result exists.
- Full parity is an acceptance requirement, not guaranteed by a facade alone:
  see the complete [CLI↔GUI map](ui-sketch/README.md#8-cli--gui-parity-map).

## 5. Dependencies and packaging

The service applies `album_link_mode`, `thumbnail_size` and
`scan_phone_after_import` defaults for all adapters. Settings APIs include
`app_service_get_settings`, `app_service_update_settings`,
`app_service_set_setting`, `app_service_reset_settings`,
`app_service_settings_path` and `app_service_forget_archive`.
Malformed settings JSON warns and falls back to defaults; invalid recognized
values raise on validation. GUI-only stored preferences remain inactive.
`app_service_reset_settings` / `config reset` can recover invalid configuration.

`pymobiledevice3`, Typer, Pillow/pillow-heif and SQLite support the current CLI.
PySide6/darkdetect and pytest-qt support the planned GUI. Actual version and
optional-extra declarations live in `pyproject.toml`.
PyInstaller Windows packaging is a scheduled milestone; no spec or released
binary is supplied in this remediation.
Qt/icon notices and replacement/relinking obligations must be checked before
distribution; see [ADR-0011](adr/0011-licensing-and-gui-contract-addendum.md).
