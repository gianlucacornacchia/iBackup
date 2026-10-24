# iPhone Archive — Project Structure

Status: current core/CLI and GUI module map (Phase 2 steps 1-12 plus the
later album/preview/location/map work, checked against HEAD on 2026-10-11).
Implementation presence does not establish hardware or crash-safety validation;
see [progress](progress.md) and [test plan](unit-tests.md).

## 1. Current modules

All paths below are relative to `src/iphone_archive/`.

| Path | Responsibility |
|---|---|
| `cli.py` | Typer adapter, archive selection, confirmation prompts, result rendering; `albums` tags iCloud Shared Albums `(shared)` and `albums --shared` lists only them. |
| `config.py` | Archive paths and initialization. |
| `settings.py` | Per-user persisted settings, validation, default/recent archives; `settings_cache_directory()` for machine-local disposable caches (`%LOCALAPPDATA%\ibackup\cache`). Saves through a uniquely named staging file per writer and propagates a failed publication instead of reporting success. |
| `logging_setup.py` | Rotating CLI command start/completion/error log, configured level and handler cleanup. |
| `service/app_service.py` | Headless `AppService` facade; `app_service_device_info(source)` returns `DeviceInfo(udid, media_count)` after full enumeration; `app_service_list_locations(album_id, only_unsorted, include_deleted)` feeds the trip map; `app_service_trip_modes(scope, asset_ids)` and `app_service_set_trip_mode(scope, from_asset_id, to_asset_id, mode)` read/reconcile and save travel modes, and `app_service_trip_ignored(scope, asset_ids)` / `app_service_set_trip_ignored(scope, asset_id, ignored)` read and save ignored map points, committing or rolling back. |
| `service/archive_lock.py` | Exclusive archive-session/process lock. |
| `service/progress.py` | `ProgressEvent`, `ProgressHandle`, Event cancellation and bounded last-256 history snapshots. |
| `service/selection.py` | Batch archive moves and `SelectionResult`; a move target name matching both a user and a shared album resolves to the user album. |
| `service/marks.py` | Staged deletion queue, `MarkSummary` (with an optional `sha256`/`relative_path` thumbnail source), `MarkCommitResult`; `marks_preview_source()` resolves an asset/file/album mark to one stored copy. |
| `device/interface.py` | Injectable `MediaSource` protocol. |
| `device/afc_device.py` | `AfcDevice`: discovery/pairing, AFC media enumeration, streaming, best-effort `Photos.sqlite` album/capture-time/GPS extraction keyed by exact path (bare filenames only for unique legacy keys), offloaded-original previews from `/PhotoData/Thumbnails/V2` with a per-UDID resolved-path cache in `settings_cache_directory()/device-cache/offloaded-preview-cache.json` (`%LOCALAPPDATA%\ibackup\cache`, never the working directory), where the temporary `Photos.sqlite` copy is also made; iCloud Shared Album membership (`shared_album_membership`, from the same database copy) and `afc_device_shared_items()`, which walks `/PhotoData/PhotoCloudSharingData` only when membership exists and yields only named members, falling back to thumbnail-cache previews (via `afc_device_offloaded_preview()`) for uncached ones and logging a WARNING summary of cached/preview/unavailable counts (not in `device_album_map()`). |
| `device/fake_device.py` | Offline `FakeDevice` for tests and CLI exercises; optional `album_map`, `locations` and `shared_album_map`. |
| `catalog/database.py` | SQLite connection, schema initialization and forward-only migrations up to `SCHEMA_VERSION = 8` (v7: `trip_segments` table; v8: `trip_ignored_points` table); newer versions are rejected. |
| `catalog/models.py` | `Asset` (incl. offloaded-preview flags, GPS, camera fields), `AssetFile`, `Album`, `ImportSession`, `DeletionMark`, `PhoneItem` (incl. preview flags, GPS, `shared_album_names`), state enums. |
| `catalog/repository.py` | Catalog queries, identities, membership, scan state; preview lookup/upgrade (`repository_find_offloaded_preview_by_original_path`, `repository_upgrade_offloaded_asset`), `repository_backfill_asset_metadata`, `repository_unlink_asset_album`. |
| `catalog/sidecar.py` | JSON metadata serialization and `SidecarData` (no GPS/camera fields). |
| `core/hashing.py` | Chunked SHA-256. |
| `core/atomic.py` | `atomic_replace()` / `atomic_rename()`: atomic file publication that retries Windows' transient `PermissionError` (a file briefly held by antivirus, the indexer or Explorer) for about 1.5 s; `FileExistsError` is never retried. Used by sidecars, settings and `file_operations` journals/publication. |
| `core/name_safety.py` | Windows-safe names and collision handling. |
| `core/archive_layout.py` | Copy/hardlink placement and `PlacedFile`; album folders via `archive_layout_album_safe_name(name, kind)` / `archive_layout_album_dir(paths, name, kind)`, with shared albums under `SHARED_ALBUMS_DIR_NAME` (`Photos/_Shared Albums/`). |
| `core/file_operations.py` | Journaled archive edit preflight, placement, rollback/finalization and sidecar recovery. |
| `core/importer.py` | Incremental import, placement, catalog/sidecars, `ImportResult` (incl. `upgraded_count`); album reconciliation with current phone membership (`importer_sync_albums`), in-place offloaded-preview upgrade, metadata backfill and EXIF capture; `importer_album_targets(item)` orders user albums (primary copy) before shared albums. |
| `core/albums.py` | Paged archive album summaries/counts and best-effort phone `Photos.sqlite` parsing: exact `ZDIRECTORY`/`ZFILENAME` keys (`albums_asset_key_sql`), album membership by `kind` (`USER_ALBUM_KIND = 2`; `SHARED_ALBUM_KIND = 1505` as an unvalidated older-iOS fallback), iOS 26+ shared albums from `ZSHARE` via `ZASSET.ZCOLLECTIONSHARE` (`albums_collection_share_query()`, trashed rows skipped), `albums_parse_shared_albums()` merging both and limited to `SHARED_MEDIA_ROOT` (`albums_is_shared_path`), and GPS (`albums_parse_location_data`, excluding the `-180` sentinel). `AlbumSummary.kind` is `"user"` or `"shared"`. |
| `core/exif.py` | Best-effort `exif_read_metadata()` → `ExifMetadata` (camera, lens, ISO, aperture, focal length, GPS fallback) from an archived file via Pillow/pillow-heif; any failure returns all-`None`. |
| `core/trip.py` | Trip-map travel modes: `TRIP_MODES`, `TripSegment`, validation, `trip_reconcile()` (keep consecutive pairs, split inherited modes over inserted photos, drop pairs with a missing or reordered photo) and `trip_set_mode()`, over `trip_segments` keyed by view scope; `trip_ignored()` / `trip_set_ignored()` over `trip_ignored_points`. The caller commits. |
| `core/dedup.py` | Read-only storage report, `DuplicateGroup`, `DedupResult`. |
| `core/verifier.py` | Verify all cataloged copies, `VerifyIssue`, `VerifyResult`. |
| `core/phone_diff.py` | Device inventory reconciliation, `DeletedFromPhoneItem`, `PhoneDiffResult`. |
| `core/reclaim.py` | Selected/all-candidate preview and guarded deletion, `ReclaimCandidate`, `ReclaimResult`; never offers shared-album cache files. |
| `core/recycle.py` | Move to Deleted, restore, purge, `RecycleResult`. |
| `browse/gallery.py` | Album/asset listings and `AssetView` (incl. `latitude`/`longitude`); aligned `file_ids`/`paths` filtered by current album/location, including partially recycled assets; `gallery_list_located()` lists located assets oldest-capture-first for the map; **no HTML generator**. |
| `browse/thumbnails.py` | Cached previews and `ThumbnailResult`: still images via Pillow/pillow-heif, video poster frames via PyAV (display-matrix rotation applied, dark opening frames skipped). Previews only — never transcodes or modifies originals. A Windows `PermissionError` on publishing is ignored when a concurrent writer already produced the entry. |
| `gui/__init__.py` | Package marker. Deliberately imports no Qt, so a broken PySide6 install cannot break the CLI. |
| `gui/application.py` | Process bootstrap, logged style fallback, persisted theme, logging, entry point, opt-in `--mica-probe` and worker join on application exit. |
| `gui/main_window.py` | Window shell, lazy worker owner, surfaced worker errors and deferred close until worker shutdown completes; routes every verb, including `main_window_map_action` (view key → `app_service_list_locations` scope → `app_service_trip_modes` when ≥ 2 photos are located → `main_window_open_map()` → `MapDialog`, given the worker's `archive_root` for popup pictures and a callback that submits `app_service_set_trip_mode`; the map still opens if reading modes fails). |
| `gui/theme.py` | WinUI tokens/type ramp/metrics, scoped QSS, live theme/accent controller and high-contrast preservation; GUI-thread-only. |
| `gui/win32_effects.py` | Lazy native preference queries, build-guarded DWM attributes, checked HRESULTs and observable solid fallback; experimental frame extension for the Mica probe. |
| `gui/worker.py` | GUI-affine `WorkerController`, dedicated FIFO `ServiceThread`, worker-only session, bounded/coalesced progress mailbox and detached `WorkerResult`/`WorkerFailure` transport. |
| `gui/models.py` | `ArchiveModels`, lazy `AssetModel`/`AlbumModel`, cached roles (incl. `AlbumRole.KIND`; shared-album tooltip "(iCloud Shared Album)"), generation-bound exact-copy selections and mutation barriers; no direct SQLite/device access. |
| `gui/icons.py` | Line-art glyphs drawn with QPainter in the caller's colour, so icons follow light/dark/high-contrast themes with no bundled asset set; includes the `shared-album` glyph. |
| `gui/navigation.py` | `NavigationPane`: library/album rows, live counts, accent selection pill delegate, icon-rail collapse and programmatic selection that never fakes a user navigation; `navigation_set_albums(albums, shared_album_ids=...)` lists shared albums under a separate "Shared albums" header after "Albums". |
| `gui/commands.py` | `CommandSpec` table binding every command-bar verb to a service operation, plus availability/tooltip rules for missing archive or phone. |
| `gui/shell.py` | `ArchiveShell`: navigation, page stack, command bar and status composition. Holds no archive data; counts and albums come from the worker and follow the models' mutation barriers. Each `ShellPage` header has a **Map** button, shown only on gallery-backed views with an archive open (`shell_map_requested`); `shell_page_take_body` checks layout membership, not Qt parentage. |
| `gui/previews.py` | `PreviewLoader`: dedicated render pool off the service worker, bounded LRU pixmap cache, per-key coalescing, cancel-on-scroll, remembered failures and bounded shutdown. Pool threads receive immutable paths/hashes only. |
| `gui/gallery.py` | `AssetGallery`: delegate-painted icon grid bound directly to the shared paged model, rubber-band/Ctrl/Shift selection, scope-gated selection bar and context menu. Painting never touches the disk; it reads the preview cache or schedules a render. |
| `gui/viewer.py` | `ViewerDialog`: full-size single-asset view with its own large-preview loader, keyboard navigation that pages the model on demand, metadata facts and close-on-reset. |
| `gui/operations.py` | `OperationDialog`: progress, elapsed/remaining, cancellation where the backend implements it, Hide, and the per-operation result summaries. `CANCELLABLE_OPERATIONS` is derived from the real service signatures, not hand-listed. |
| `gui/dialogs.py` | `MoveToAlbumDialog` and `ReportDialog`: non-blocking prompts and read-only reports, shown rather than `exec`-ed so no nested event loop runs inside the GUI. |
| `gui/confirm.py` | `ConfirmDialog` and the `ConfirmSpec` builders: the single gate between a selection and a deletion. Permanent verbs require the typed word `DELETE`, re-checked when the button is pressed; reversible ones ask explicitly without it. The spec carries the exact operation and parameters that were described to the user. |
| `gui/review.py` | `ReviewList`/`ReviewPage` plus `DeletedPhonePage` (sketch §3) and `MarksPage` (§6): bounded listings of decisions over a `QStandardItemModel`, shown in an icon-mode `QListView` painted by `gallery.TileDelegate` with real thumbnails from the shared `PreviewLoader`; "checked" is the view's multi-selection. A refreshed listing drops its selection so a replaced row cannot inherit a deletion. |
| `gui/reclaim.py` | `ReclaimDialog` (sketch §4): the report of a completed **dry run**, and the only route to a real phone-side deletion, which still has to pass the typed confirmation. |
| `gui/settings_dialog.py` | `SettingsDialog` (sketch §7b): edits a detached copy of every preference; safety options shown ticked and disabled. |
| `gui/parity.py` | No widgets: declares which GUI surface reaches each service operation and CLI command, checked by `tests/test_gui_parity.py`. |
| `gui/mapview.py` | Trip map: `MapPoint` (incl. `captured_at`, `note`, `mode`, `ignored`), `mapview_parse_ignore_change()` (`ibackup-ignore:<index>:<0|1>`) feeding `WebMapWidget.ignore_changed` / `MapDialog(..., ignored, on_point_ignored)`, Previous/Next point buttons driving the page's `mapStep()`, `MODE_STYLES` (label/emoji/colour/dash per travel mode), per-leg polylines with click-to-tag popups on a `preferCanvas` map, `mapview_parse_mode_change()` (`ibackup-mode:<leg>:<mode|none>`, known modes and legs only) feeding `WebMapWidget.mode_changed` and `MapDialog(..., segments, on_mode_changed)`, `mapview_note`/`mapview_located`/`mapview_points`, `mapview_build_html()` (Leaflet inlined, points JSON-escaped; Start/End pins, Web-Mercator direction arrows shown for segments ≥ 40 px, cached per-point photo popups), `mapview_parse_request()` (in-range `ibackup-photo:<index>` only), `mapview_render_photo()` (archived copy → `thumbnails_get` 320 px → `data:` URI), `MapPhotoBridge`/`MapPhotoTask` (2-thread `QThreadPool`), `MapPage` (`QWebEnginePage` intercepting photo-request console messages), `mapview_tile_profile()` (named persistent `QWebEngineProfile` "ibackup-map-tiles", 200 MB disk cache, custom User-Agent), `WebMapWidget(parent, archive_root)` and `MapDialog(title, assets, parent, archive_root)` (900×640, delete-on-close, waits for renders). The app's only network use: OpenStreetMap tiles. |
| `gui/webassets/leaflet/` | Vendored Leaflet `leaflet.js`/`leaflet.css` and its BSD-2-Clause `LICENSE`; package data in `pyproject.toml` and a `datas` entry in `packaging/ibackup.spec`. |

DTOs live with their owning modules above. There is no `service/results.py`,
`device_manager.py`, `afc_client.py`, or `media_source.py`.
Repository metadata/tool configuration is in `pyproject.toml`, `.github/`, and
`.pre-commit-config.yaml`; tests are inventoried in `unit-tests.md`.

## 2. Layering and data flow

```text
CLI / GUI worker
              |
        service/AppService
              |
       core + browse + catalog
              |
       injectable MediaSource
              |
       AfcDevice / FakeDevice
```

The trip map is the one GUI path outside this stack's locality: its data
comes through the worker like any listing, but `gui/mapview.py` then fetches
OpenStreetMap tiles directly from the GUI process via Qt WebEngine.

The service owns the archive session and connection. Frontends translate input
and render results; persistence and destructive eligibility stay below them.
Settings are outside the archive; media, catalog, sidecars and recovery data
travel together. Plain media remains viewable without SQLite or this app.

Import: enumerate device metadata (plus offloaded-preview stand-ins) →
device-scoped fast-skip checks (backfill missing GPS/camera metadata,
reconcile album copies) → upgrade a matching offloaded preview in place, or
stream new/changed bytes into archive staging while hashing → verify/place
each copy, read EXIF → persist sidecar/catalog/session state. Album placement
of already-archived assets follows the phone's current membership: missing
album copies are added first, then stale `Photos/` copies are removed.
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

## 4. GUI execution contract

The sketch was approved on 2026-09-11. Every Phase 2 step is implemented; the
views must keep preserving the following:

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
  `operations.py`, `dialogs.py`, `confirm.py`, `review.py`, `reclaim.py`,
  `settings_dialog.py` and `parity.py`, delivered by steps 1-11 of
  `plan.md` §2b, plus `mapview.py` and its vendored `webassets/leaflet/`
  (added 2026-10-10). `parity.py` holds no widgets: it declares which surface
  reaches each service operation, so `tests/test_gui_parity.py` can fail when a
  capability exists only in the CLI. The earlier
  planned names (`navigation_pane.py`, `command_bar.py`, `picture_grid_view.py`,
  `thumbnail_loader.py`, `operations_controller.py`) map onto those files.
- DWM failures log the attribute/result and select a solid background.
  Normal launches remain opaque; `--mica-probe` opts into experimental
  translucent painting on Windows 11 22H2+. No visual probe result exists.
- Full parity is an acceptance requirement, not guaranteed by a facade alone:
  see the complete [CLI↔GUI map](ui-sketch/README.md#8-cli--gui-parity-map). It
  is enforced by `tests/test_gui_parity.py` against `gui/parity.py`, so the map
  cannot quietly fall behind the code.

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

`pymobiledevice3`, Typer, Pillow/pillow-heif (thumbnails and EXIF), PyAV
(video poster frames) and SQLite support the current CLI/core.
PySide6 and pytest-qt support the GUI (`darkdetect` remains
reserved; Qt/Win32 currently supply native appearance). The trip map uses
PySide6's `QtWebEngineCore`/`QtWebEngineWidgets` and vendored Leaflet, read
from disk at runtime (package data, and an explicit PyInstaller `datas`
entry). Actual version and
optional-extra declarations live in `pyproject.toml`.
PyInstaller Windows packaging lives in `packaging/` (spec, entry-point shim,
self-drawn icon, version resource and an artifact smoke test); a signed,
released binary is still a separate milestone.
Qt/icon notices and replacement/relinking obligations must be checked before
distribution; see [ADR-0011](adr/0011-licensing-and-gui-contract-addendum.md)
and its 2026-10-11 note (Leaflet notice, Qt WebEngine/Chromium notices,
OpenStreetMap attribution and tile policy).
