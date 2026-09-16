# iPhone Archive — Project Structure

Status: current core/CLI and GUI shell/theme/worker/models map plus planned GUI contracts.
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
| `core/albums.py` | Paged archive album summaries/counts and best-effort phone `Photos.sqlite` album membership parsing. |
| `core/dedup.py` | Read-only storage report, `DuplicateGroup`, `DedupResult`. |
| `core/verifier.py` | Verify all cataloged copies, `VerifyIssue`, `VerifyResult`. |
| `core/phone_diff.py` | Device inventory reconciliation, `DeletedFromPhoneItem`, `PhoneDiffResult`. |
| `core/reclaim.py` | Selected/all-candidate preview and guarded deletion, `ReclaimCandidate`, `ReclaimResult`. |
| `core/recycle.py` | Move to Deleted, restore, purge, `RecycleResult`. |
| `browse/gallery.py` | Album/asset listings and `AssetView`; aligned `file_ids`/`paths` filtered by current album/location, including partially recycled assets; **no HTML generator**. |
| `browse/thumbnails.py` | Cached previews and `ThumbnailResult`: still images via Pillow/pillow-heif, video poster frames via PyAV (display-matrix rotation applied, dark opening frames skipped). Previews only — never transcodes or modifies originals. |
| `gui/__init__.py` | Package marker. Deliberately imports no Qt, so a broken PySide6 install cannot break the CLI. |
| `gui/application.py` | Process bootstrap, logged style fallback, persisted theme, logging, entry point, opt-in `--mica-probe` and worker join on application exit. |
| `gui/main_window.py` | Window shell, lazy worker owner, surfaced worker errors and deferred close until worker shutdown completes. Views arrive in later steps. |
| `gui/theme.py` | WinUI tokens/type ramp/metrics, scoped QSS, live theme/accent controller and high-contrast preservation; GUI-thread-only. |
| `gui/win32_effects.py` | Lazy native preference queries, build-guarded DWM attributes, checked HRESULTs and observable solid fallback; experimental frame extension for the Mica probe. |
| `gui/worker.py` | GUI-affine `WorkerController`, dedicated FIFO `ServiceThread`, worker-only session, bounded/coalesced progress mailbox and detached `WorkerResult`/`WorkerFailure` transport. |
| `gui/models.py` | `ArchiveModels`, lazy `AssetModel`/`AlbumModel`, cached roles, generation-bound exact-copy selections and mutation barriers; no direct SQLite/device access. |
| `gui/icons.py` | Line-art glyphs drawn with QPainter in the caller's colour, so icons follow light/dark/high-contrast themes with no bundled asset set. |
| `gui/navigation.py` | `NavigationPane`: library/album rows, live counts, accent selection pill delegate, icon-rail collapse and programmatic selection that never fakes a user navigation. |
| `gui/commands.py` | `CommandSpec` table binding every command-bar verb to a service operation, plus availability/tooltip rules for missing archive or phone. |
| `gui/shell.py` | `ArchiveShell`: navigation, page stack, command bar and status composition. Holds no archive data; counts and albums come from the worker and follow the models' mutation barriers. |
| `gui/previews.py` | `PreviewLoader`: dedicated render pool off the service worker, bounded LRU pixmap cache, per-key coalescing, cancel-on-scroll, remembered failures and bounded shutdown. Pool threads receive immutable paths/hashes only. |
| `gui/gallery.py` | `AssetGallery`: delegate-painted icon grid bound directly to the shared paged model, rubber-band/Ctrl/Shift selection, scope-gated selection bar and context menu. Painting never touches the disk; it reads the preview cache or schedules a render. |
| `gui/viewer.py` | `ViewerDialog`: full-size single-asset view with its own large-preview loader, keyboard navigation that pages the model on demand, metadata facts and close-on-reset. |
| `gui/operations.py` | `OperationDialog`: progress, elapsed/remaining, cancellation where the backend implements it, Hide, and the per-operation result summaries. `CANCELLABLE_OPERATIONS` is derived from the real service signatures, not hand-listed. |
| `gui/dialogs.py` | `MoveToAlbumDialog` and `ReportDialog`: non-blocking prompts and read-only reports, shown rather than `exec`-ed so no nested event loop runs inside the GUI. |
| `gui/confirm.py` | `ConfirmDialog` and the `ConfirmSpec` builders: the single gate between a selection and a deletion. Permanent verbs require the typed word `DELETE`, re-checked when the button is pressed; reversible ones ask explicitly without it. The spec carries the exact operation and parameters that were described to the user. |
| `gui/review.py` | `ReviewList`/`ReviewPage` plus `DeletedPhonePage` (sketch §3) and `MarksPage` (§6): bounded checkable listings of decisions rather than photo grids. A refreshed listing drops its ticks so a replaced row cannot inherit a deletion. |
| `gui/reclaim.py` | `ReclaimDialog` (sketch §4): the report of a completed **dry run**, and the only route to a real phone-side deletion, which still has to pass the typed confirmation. |

DTOs live with their owning modules above. There is no `service/results.py`,
`device_manager.py`, `afc_client.py`, or `media_source.py`.
Repository metadata/tool configuration is in `pyproject.toml`, `.github/`, and
`.pre-commit-config.yaml`; tests are inventoried in `unit-tests.md`.

## 2. Layering and data flow

```text
CLI / GUI worker (operation views pending)
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

## 4. GUI execution contract — implementation in progress

The sketch was approved on 2026-09-11. The shell, theme, worker and paged models
exist. Later operation views must preserve the following:

- Create/open/use/close `AppService` and its SQLite connection **in the worker
  thread that owns them**. Never share a service/connection between QThreads,
  and do not defeat SQLite thread checks. `WorkerController` enforces GUI-side
  affinity and queues work to one lazy `ServiceThread`; its worker-only session
  constructs and closes the service. The service rejects competing sessions as
  busy. Archive switching requires explicit close then open, not a second session.
- Use `threading.Event` cancellation; emit progress/results through queued Qt
  signals. Worker callbacks must never touch widgets directly. Shutdown
  cancels, waits for safe completion, then closes the worker-owned session.
  The current progress handle retains only the last 256 events; a locked mailbox
  coalesces updates to at most one pending Qt notification per accepted request.
  The FIFO accepts at most 32 outstanding requests, rejecting overflow, and
  reserves a separate shutdown slot. Cancellation is cooperative, not rollback:
  operations without checkpoints must finish; completed work remains successful.
- Request parameters/results are detached plain data (including nested DTOs).
  Live service/SQLite/device/widget objects cannot cross this boundary. Error
  replies contain strings, not exceptions retaining worker traceback frames.
  Device contexts are constructed/used/closed inside the operation on the worker.
  Expected failures are reported without losing the session; unexpected failures
  close it and fail pending requests without replay. The next request after the
  `stopped` signal can start a fresh worker session.
- Bound thumbnail workers, pending requests and decoded-image caches; request
  visible/prefetch tiles only, discard stale requests, and paginate metadata.
  Independent thumbnail workers receive immutable paths/DTOs, not SQLite.
- Models fetch at most one page each (128 rows by default, 1-512 configurable,
  plus one lookahead row). Metadata access is cached and performs no I/O;
  loaded metadata accumulates until reset, not a fixed-size cache of the whole
  library. Archive mutations invalidate pages/selections before GUI reply
  delivery. Qt insertion/reset notifications cannot trigger overlapping
  fetches or relabel copies into a new scope.
- Selection snapshots bind model token, generation, archive and scope to exact
  `asset_ids`/`file_ids`. Ordinary source indexes carry the generation; proxy
  indexes must be captured as `QPersistentModelIndex` while valid, since mapping
  a stale ordinary proxy index can crash Qt. Recheck snapshots immediately before
  submission. Empty selections pass explicit empty lists, never an all-assets
  fallback.
- The GUI package is `main_window.py`, `application.py`, `theme.py`,
  `win32_effects.py`, `worker.py`, `models.py`, `previews.py`, `navigation.py`,
  `commands.py`, `icons.py`, `shell.py`, `gallery.py`, `viewer.py`,
  `operations.py`, `dialogs.py`, `confirm.py`, `review.py`, `reclaim.py` and
  `settings_dialog.py`, delivered by steps 1-10 of `plan.md` §2b. The earlier
  planned names (`navigation_pane.py`, `command_bar.py`, `picture_grid_view.py`,
  `thumbnail_loader.py`, `operations_controller.py`) map onto those files.
- DWM failures log the attribute/result and select a solid background.
  Normal launches remain opaque; `--mica-probe` opts into experimental
  translucent painting on Windows 11 22H2+. No visual probe result exists.
- Full parity is an acceptance requirement, not guaranteed by a facade alone:
  see the complete [CLI↔GUI map](ui-sketch/README.md#8-cli--gui-parity-map).

## 5. Dependencies and packaging

The service applies `album_link_mode`, `thumbnail_size` and
`scan_phone_after_import` defaults for all adapters. Settings APIs include
`app_service_get_settings`, `app_service_update_settings`,
`app_service_set_setting`, `app_service_reset_settings`,
`app_service_settings_path` and `app_service_forget_archive`.
Malformed settings JSON warns and falls back to defaults; invalid recognized
values raise on validation. The six settings operations are archive-free: the
GUI worker runs them against a preferences-only service whose root is a sentinel
that cannot be an archive, so they work before one is open and fail closed if
an archive-touching operation is ever added to that set. The GUI edits every
preference in its §7b dialog and applies theme, preview size, log level and the
deleted-on-phone default as soon as they are saved; `reopen_last_archive`
reopens the last archive at startup only when that folder is still an archive.
`app_service_reset_settings` / `config reset` can recover invalid configuration.

`pymobiledevice3`, Typer, Pillow/pillow-heif and SQLite support the current CLI.
PySide6 and pytest-qt support the GUI shell/theme/worker/models layer (`darkdetect` remains
reserved; Qt/Win32 currently supply native appearance). Actual version and
optional-extra declarations live in `pyproject.toml`.
PyInstaller Windows packaging is a scheduled milestone; no spec or released
binary is supplied in this remediation.
Qt/icon notices and replacement/relinking obligations must be checked before
distribution; see [ADR-0011](adr/0011-licensing-and-gui-contract-addendum.md).
