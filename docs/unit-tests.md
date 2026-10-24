# iPhone Archive — Tests and Validation Plan

Status: offline core/CLI hardening and its regression checkpoint are complete.
The GUI (all Phase 2 steps, plus the trip map) has offline coverage; live
Windows appearance and the Windows release are **not validated**.
Use the final validation report in [progress](progress.md), not stale copied
test counts, for executed commands/results.

## 1. Running existing tests

With the project virtual environment active and dev dependencies installed:

```powershell
pytest tests\test_importer.py tests\test_service.py tests\test_cli.py
pytest
pytest --cov=iphone_archive
```

Choose targeted existing tests after code changes; run the full configured
quality gates for a checkpoint. Docs-only edits need no Python test run.
The suite uses fake devices and pytest `tmp_path`; configure a project-local
test base when the execution environment prohibits system temporary folders.
GUI tests run headless: `tests/test_gui.py`, `tests/test_gui_theme.py`,
`tests/test_gui_worker.py`, `tests/test_gui_models.py` and
`tests/test_gui_previews.py`, `tests/test_gui_shell.py`, `tests/test_gui_gallery.py`,
`tests/test_gui_operations.py`, `tests/test_gui_destructive.py`,
`tests/test_gui_settings.py`, `tests/test_gui_parity.py` and
`tests/test_gui_mapview.py` set
`QT_QPA_PLATFORM=offscreen`, so no display is
needed and CI behaves like a developer machine. They
skip cleanly when PySide6 or pytest-qt is unavailable;
`test_gui_mapview.py` additionally needs Qt WebEngine (PySide6-Addons) but
no network.

## 2. Existing test inventory

This table names actual files and their area, not a claim that every possible
scenario is covered or that the latest edited suite has passed.

| File (`tests/`) | Area |
|---|---|
| `test_config.py` | Archive path initialization/resolution. |
| `test_settings.py` | Settings persistence, defaults, validation, CLI config behavior; a failed publication is reported and its unique staging file cleaned up. |
| `test_logging_setup.py` | Logging configuration and operation output. |
| `test_hashing.py` | Streaming hashes, known inputs and property checks. |
| `test_atomic.py` | `core/atomic.py`: a transient `PermissionError` retried with the bounded delays, a persistent one raised, `FileExistsError` never retried, no retry off Windows, and real replace/rename on disk. |
| `test_name_safety.py` | Sanitization, reserved names, collisions and property checks. |
| `test_archive_layout.py` | Placement, hardlink/copy behavior and safe paths. |
| `test_catalog.py` | Schema and repository behavior; v5 (`latitude`/`longitude`) and v6 (camera fields) migrations and round trips. Upgrade coverage must track migrations. |
| `test_sidecar.py` | Metadata serialization/round trip. |
| `test_device.py` | Fake-device protocol (including `locations`) plus mocked AFC behavior; real parser-to-AFC-to-import regression for an offloaded album member sharing a filename with a different local photo, exact-path capture dates, legacy ambiguity refusal (database-wide filename uniqueness), bare-key album and GPS fallback only for legacy keys with exact-path matches preferred, missing-original warnings and correct archive placement; offloaded-photo cached-thumbnail preview fallback (recovered and placed in its album, named and flagged as a preview), its never-raises behavior when no cache exists, its on-disk resolved-path cache persisting across runs, and a second lookup for an already-cached path making zero AFC calls; the device cache never resolving under the working directory; an unreadable `Photos.sqlite` marking items `album_membership_known = False`. Hardware evidence is recorded separately in `progress.md`. |
| `test_importer.py` | Import/skip/dedup, album placement, process-exit recovery after placement/extra copy/sidecar, and refusal of ambiguous recovery files; album reconciliation (stale copy removed on a phone-side move, fallback to `_Unsorted` when removed from every album, a rolled-back item keeping its stale copy, a committed item's retired copy deleted by the next recovery, album copies kept when the phone's album data is unreadable, a stale copy kept when the copy that would remain is corrupt); a fast-skipped unchanged asset hashed exactly once; in-place offloaded-preview upgrade (single asset, preview file gone, location replaced; never by another device's photo at the same path; preview kept and item counted as a duplicate when the original's bytes are already archived); phone GPS and EXIF camera metadata stored on new assets with phone GPS preferred over EXIF GPS; reimport backfilling missing GPS/camera metadata and never overwriting recorded values. |
| `test_dedup.py` | Read-only duplicate/storage reports. |
| `test_verifier.py` | Intact, missing and corrupted cataloged copies; no `--full` mode. |
| `test_albums.py` | Archive album summaries, discovered join-table ordinals, exact directory/filename membership keys (including through `device_enumerate`), slash normalization, missing-directory refusal and legacy filename uniqueness across all assets (including those without albums); GPS parsing with the `(-180, -180)` sentinel excluded and empty results for schemas without GPS columns or a missing database. Synthetic schemas do not qualify every iOS version. |
| `test_core_exif.py` | `core/exif.py` against synthetic Pillow JPEGs: camera/lens/ISO/aperture/focal length, GPS sign from the ref tags, missing-EXIF and corrupt-file degradation to all-`None`, Make/Model de-duplication and one-item-tuple numerics. |
| `test_shared_albums.py` | iCloud Shared Albums (14 tests): iOS 26 `ZSHARE`/`ZCOLLECTIONSHARE` parsing with trashed shares/assets skipped and user albums unaffected, legacy `ZKIND = 1505` parsing kept apart from user albums, no legacy shared albums without `ZKIND`, graceful degradation for missing/unreadable databases, `albums_is_shared_path`, import into `Photos/_Shared Albums/<name>/` with `kind = shared`, stable reimport, a photo in a user and a shared album getting both copies, reclaim never offering shared-cache files or thumbnail previews, real-SQLite AFC enumeration yielding only named members of the sharing cache, uncached members falling back to thumbnail previews (`offloaded_original_path` = the shared path) with the WARNING summary, walk-failure tolerance, and CLI `(shared)` tagging and `albums --shared`. Synthetic schemas only; not hardware evidence. |
| `test_phone_diff.py` | Inventory/absence reconciliation. |
| `test_reclaim.py` | Device/content eligibility, selected reclaim, fresh checks and fail-closed deletion regressions. |
| `test_gallery.py` | Asset/album read models, partial recycling and location-filtered paths/counts, not HTML output; `gallery_list_located` capture-time ordering, album/unsorted/recycled scoping and exclusion of unlocated assets. |
| `test_thumbnails.py` | Still-image generation/cache, video poster frames (orientation checked against ffmpeg, dark lead-in skipped, missing PyAV degrades), and unsupported-media behavior. |
| `test_progress.py` | Progress and cancellation handle (`core/progress.py`). |
| `test_layering.py` | Import graph: `core`, `catalog` and `device` never import `service`, `browse`, `gui` or `cli`. |
| `test_service.py` | Facade, recycle/restore/purge/reclaim, selection, locks/thread ownership, `app_service_list_locations`. |
| `test_marks.py` | Stage/unmark/commit behavior; pending marks carrying a thumbnail source and none for an empty album. |
| `test_selection.py` | Partial/batch moves, conflicts, preflight and interrupted-operation recovery, including subprocess exit/restart rollback. |
| `test_recycle.py` | Partial recycle/restore/purge, invalid paths, missing copies, sidecar-failure recovery and committed-operation restart finalization. |
| `test_cli.py` | Command parsing, errors, confirmation and service wiring. |
| `test_e2e.py` | Offline pipeline and selected crash/resume scenarios; album reconciliation end to end (first album replaces the `_Unsorted` copy, multi-album growth keeps both copies, a phone-side move leaves no duplicate). |
| `test_gui.py` | Offscreen window shell, entry point/style selection, WebEngine software-rendering flag and Qt-free package/bootstrap imports in a fresh process. |
| `test_gui_theme.py` | Exact color/alpha/type tokens, scoped QSS, persisted theme bootstrap, live system/accent changes, high-contrast precedence, Qt 6.7 fallback and rendered solid opacity. |
| `test_gui_worker.py` | Real QThread service/device ownership, queued GUI delivery, archive-lock release, fake-device import/verify, detached request/result data, FIFO/overflow, coalesced progress, direct and queued cancellation, failure cleanup/restart without replay and window/application shutdown. |
| `test_gui_models.py` | Lazy 1 297-asset paging on the worker, roles and bounded queries, Qt model contracts/reentrant notifications, stale replies/indexes, persistent proxy selections, mutation barriers and exact-copy recycle/restore isolation. |
| `test_gui_previews.py` | Preview key/path validation, LRU eviction, background render and cache reuse, per-key coalescing, remembered failures and retry, cancel-on-scroll, pending bound, superseded/cancelled replies, archive/size switching, off-GUI-thread rendering, cross-thread rejection, bounded shutdown, concurrent cache writers, invalid persisted sizes and window ownership; review-page rows picking up a thumbnail through `TileDelegate` once the real loader settles. |
| `test_gui_shell.py` | Drawn-glyph coverage and colour, album/library navigation keys, live counts and albums from real worker imports, preserved selection across refreshes, rail collapse, command-to-service mapping and availability rules, phone state from device failures, page/scope switching, archive close and shutdown cleanup, and status precedence over errors; shared albums listed in their own "Shared albums" navigation section. |
| `test_gui_gallery.py` | Tile layout/eliding/size formatting, delegate painting from cache and scheduled renders, anchor-based viewport scanning cost, cancel-on-scroll safety when no tile is locatable, rubber-band/Ctrl/Shift selection, scope-gated selection bar and context menu, selection captured as exact copies on the GUI thread, stale-selection refusal after a reset, paging while scrolling, page errors surfaced in the status bar, gallery re-hosting across pages, and viewer open/navigate/page/close-on-reset with deletion on close. |
| `test_gui_destructive.py` | The confirmation gate: a permanent action refusing a click without the typed word and re-checking the word when the button is pressed, a reversible action confirmed without it, Cancel holding default focus, cancelling deleting nothing, a purge really removing the bytes, a stale selection refused after the prompt opened, a recycle-bin purge restricted to recycled copies, restore running ungated, marking staging without deleting and stating album scope, a queue-wide mark commit, clearing marks asking nothing, an oversized unmark refused rather than flooding the bounded queue, the deleted-on-phone listing and its gated buttons, ticks dropped on refresh, bounded listings, reclaim running a dry run that deletes nothing, the reclaim dialog as the only route to a phone deletion and still passing the typed confirmation, an empty dry run opening no dialog, previews never reported as completed deletions, and summaries reporting only what happened. |
| `test_gui_operations.py` | Duration/estimate/eliding helpers, the cancellable set checked against the real service signatures in both directions, every result summary including a cancelled import reported as a partial success, problem detection and error-line listing, bounded duplicate reports, the move prompt's empty-name refusal and album-scope wording, archive open/create from a chosen folder, the progress dialog's own-request filtering, Hide keeping work running, a running dialog refusing to be destroyed, a clean hidden run closing itself and an erroring one coming back, cancellation reaching the request and being harmless after completion, quiet reads, a real move landing files in the album, album-scoped moves, stale-selection refusal, refused submissions and failures staying on screen, window close closing a running dialog, replaced dialogs/viewers not orphaning their successors, and preview clearing quiescing the loaders. |
| `test_gui_settings.py` | The six settings panels against the real settings store in `tmp_path`: saved values reaching the file, no panel weakening a confirmation, no preference opening/creating/modifying an archive, reopen-on-startup only for a folder that is still an archive, and settings operations running with no archive open. |
| `test_gui_mapview.py` | Trip map (28 tests): a real WebEngine map of 20,000 points (a page well over `setHtml()`'s 2 MB limit) plotting every marker; ignore-message parsing (in-range index, `0`/`1` only), the ignored flag carried onto points and into the HTML, a real WebEngine round trip for **Ignore this point** (the legs touching it vanish and none bridges it, Start/End pins stay, **Include** restores them, `ignore_changed` and the "(N ignored)" caption), points ignored from the start greyed and unconnected, no leg bridging an ignored point, **Next/Previous point** visiting only non-ignored points and wrapping, the buttons disabled when nothing is left to visit; travel-mode message parsing, saved modes carried onto points, a style for every mode, a real WebEngine round trip (initial modes drawn; clicking a leg and **Tuk-tuk** saves `(12, 13, "tuktuk")` and recolours it; **Clear** saves `None`); point extraction skipping unlocated assets, capture-time and preview/video notes, generated HTML embedding Leaflet and the points with Start/End pins and direction arrows, world-view fallback with no points, escaping of `</script>` in labels, photo-request parsing (in-range indices only), `data:` URI rendering from the archived copy, a clicked point receiving its photo (mocked `runJavaScript`), the "No archive open" message, `MapPage` forwarding only photo requests, the single persistent disk-cached tile profile, real WebEngine page execution (4 points, two at the same spot → 4 markers, 2 arrow segments, 2 pins; `openPopup` emits `ibackup-photo:1`), an end-to-end popup-shows-the-picture regression (Leaflet re-running content functions), and `WebMapWidget`/`MapDialog` building offscreen. Tile loading is not exercised. |
| `test_trip.py` | Travel modes and ignored points (17 functions, 21 cases with parametrization; ignored points: saved per view and surviving reopen, modes untouched, idempotent, invalid input refused, cascade on purge): persistence across service reopen, across re-importing the same photos (same asset ids), across an offloaded preview being upgraded to its original, and in an album's map across re-import; a photo newly imported inside a tagged leg splitting it, per-view scope, a removed photo dropping the modes touching it and not restoring them, an inserted photo splitting a leg (also with several insertions), an explicit mode winning over an inherited one, purge cascading to segments, invalid edits refused (scope, ids, mode, unknown assets), malformed asset lists refused, and the required mode list. `core/trip.py` at 100% coverage. |
| `test_gui_parity.py` | CLI↔GUI parity enforced from the real Typer app, the real `AppService` and the real GUI source: every service operation having a surface, the declaration naming only operations that still exist, every declared surface really submitting its operation, no undeclared submission, every CLI command mapped and no CLI command doing work the GUI cannot, no verb left deferred, plus offscreen journeys that import, verify, mark an album, mark one copy or every copy, dismiss the scope prompt without staging anything, and commit and restore a recycle round trip asserted against the files on disk. The window fixture accepts `located=True`; `test_the_map_saves_and_restores_travel_modes` opens Map, edits a mode, and checks a reopened map receives it. |
| `test_win32_effects.py` | Mocked platform/build guards, native preference queries, pointer-sized HWND/32-bit arguments, HRESULT/load failures and opt-in Mica fallback. Not a live Windows probe. |
| `test_packaging.py` | The PyInstaller spec executed with stubbed builders (shared entry point, `src` on the path, `pymobiledevice3` hidden import, windowed one-directory build, icon and version resource), the committed multi-resolution `.ico`, the version resource against `project.version`, and the artifact smoke test driven against real child processes: a missing artifact, a surviving process, the enforced offscreen platform, an immediate exit, a traceback from a process that stays alive, and the default artifact path. Does not build the executable - that runs in the `package` CI job - and does not yet assert the `gui/webassets` `datas` entry. |

`test_reclaim.py`, `test_recycle.py` and `test_selection.py` were added in core
hardening; related integration cases remain in service/E2E files. Their presence
is not a claim of a completed final validation run. Result DTOs
live with their owning modules, not `service/results.py`.

Shared `conftest.py` fixtures are `isolated_settings`, `catalog_connection`,
and `sample_media`; other service/device fixtures are local to individual tests.

## 3. Core-hardening acceptance coverage

The checkpoint must record pass/fail evidence for these requirements, including
new regression tests where existing tests do not cover them:

- Device-scoped, many-to-one identities; same path on different phones; renamed
  and duplicate content; legacy migration; unknown newer schema rejection.
- Incomplete/failed/cancelled scans do not publish absence; `_Unsorted` fallback
  is observable for unavailable/unsupported album metadata.
- Bounded AFC file reads and deterministic resource closure after errors,
  cancellation and early exit; large-video byte-count/hash preservation.
  Cover supported async-library adaptation with a persistent session event
  loop, not a new loop for each chunk, and `device_close`/context-manager paths.
- Reclaim rejects stale/changed source bytes, recycled-only/missing/corrupt
  archive copies and unselected assets; failed candidates report reasons.
  Preview and cancellation delete nothing; real AFC deletion fails closed.
- Archive copy/sidecar/catalog failures, conflicts and retries; recovery after
  partial recycle/restore/purge; preserving valid copies and album memberships.
  Recovery must refuse external replacements even with identical bytes, while
  private staging makes ordinary creation/ownership-record-write interruptions
  recoverable. Fault-inject ENOSPC/fsync errors and actual process exits at
  those boundaries. Measure journal bytes to ensure linear batch scaling.
- Aligned `AssetView.file_ids`/paths and `list --files`; mutually exclusive
  `marks add --file`/`--album`; file-scoped commit preserves unselected copies.
  Source-album moves differ explicitly from default all-active-copy moves.
  Recycled-only purge preserves Photos copies of partially recycled assets;
  mismatched explicit file IDs fail rather than broadening selection.
  CLI repeated `--file ID` forwards copy selection with required asset IDs.
  `--device UDID` selects device-info/import/scan/reclaim and scopes deleted
  reports with or without rescan.
- Typed `DELETE` required for permanent archive deletion and confirmed
  reclaim; absent/wrong/EOF input aborts. Reversible mark commit retains its
  explicit `--confirm`. Settings cannot weaken this policy.
- Process/session exclusivity, worker-owned SQLite, Event cancellation and
  cleanup; selected reclaim, marks clear, thumbnail cache clear and operation
  logs with actual settings applied.

Unit success does not prove power-loss durability or Windows filesystem
behavior. Identify tested failure boundaries rather than promising universal
atomicity. An immutable audit trail and catalog rebuild are separate work.

## 4. Windows/iPhone validation gate

**Required before enabling destructive reclaim on real phones.** All rows are
pending until a dated report identifies Windows build, iPhone model, iOS
version, Apple driver, dependency versions and filesystem. Use a disposable
library with an independent verified backup, not personal irreplaceable media.

| Matrix area | Required checks / evidence |
|---|---|
| Windows 10 and 11 connectivity | Trust/untrusted/locked phone, reconnect/disconnect, multiple devices, correct UDID, driver errors. |
| Read/import | JPEG/HEIC/video/Live Photo components available via AFC; byte counts and independent hashes; no assumption that cloud-only originals are local. |
| Album metadata | Supported and unsupported `Photos.sqlite` schemas, WAL/snapshot consistency, inaccessible DB, explicit warnings and `_Unsorted` fallback; album reconciliation on reimport after phone-side album moves, and its behavior when the DB is unreadable; offloaded-preview recovery and in-place upgrade once the original returns (preview recovery confirmed on iOS 26.4 only); iCloud Shared Albums: `ZSHARE` schema, `PhotoCloudSharingData` layout and AFC reads checked on iOS 26.4 (2026-10-11, from a database copy); still pending: an end-to-end import run, re-encoded bytes differing from DCIM originals, and the legacy `ZKIND = 1505` schema on older iOS. |
| Location metadata | `ZLATITUDE`/`ZLONGITUDE` populated on each supported iOS version (one real iOS 26.4 archive backfill is recorded in `progress.md`, not a qualification run); EXIF fallback on HEIC; map tiles and the frozen build's Qt WebEngine on Windows. |
| Large videos | Multi-GB files, measured bounded read sizes/peak memory, interruption/retry, no truncation, handles closed. |
| Archive filesystems | NTFS copy/hardlink and exFAT copy/fallback, long/colliding paths, disk-full and access-denied behavior. |
| Inventory/identity | Two phones with reused paths, same content under multiple identities, cancelled scans, source changed after preview, migration from prior schema. |
| Destructive safety (separate approved test) | Fresh validation immediately before selected delete, residual hash-to-unlink race, typed confirmation, cancellation, disconnect, recovery and phone Photos consistency after deletion. |

Read/album/large-video rows must pass **before** even considering real-phone
destructive tests. AFC file removal is not assumed equivalent to a supported
Apple Photos deletion workflow; validate photo-library consistency and
recoverability before lifting the gate. An offline fake delete is not enough.

## 5. GUI and release gates

The sketch was approved on 2026-09-11. Shell/theme and worker lifetime,
queued delivery, bounded request/progress transport, error cleanup and
cancellation/shutdown now have offscreen tests. Worker tests assert actual
thread IDs and exclusive archive-lock contention; coverage alone is not proof
of correct thread placement. Any GUI test that starts a worker must join it in
a `finally` block: a failing assertion that leaves a `QThread` running aborts
the whole process, which hides the assertion message. Tests must also wait for
the refresh a mutation triggers, not just for the mutation itself, or they pass
against broken status handling. Still validate the view/model integration,
bounded thumbnail queues and native accessibility/theme behavior. The parity map
is no longer validated by reading it: `tests/test_gui_parity.py` checks the
declaration in `gui/parity.py` against the real Typer app, the real `AppService`
and the real GUI source, and fails when a capability exists only in the CLI, when
a declared surface never submits its operation, or when the GUI submits an
operation the map does not list. Perform the
Mica probe on Windows 11 22H2+ using `ibackup-gui --mica-probe` and retain its
result/logs. Confirm both themes, wallpaper tint, native title bar, resize/snap/
maximize, high contrast, transparency disabled and battery saver. Normal
launches remain solid until that client-painting path is proven.

Release requires passing Windows CI, a Windows-built CLI executable smoke test
on a clean machine without Python, dependency/license notices, versioned
artifacts, and separately validated GUI packaging. GUI packaging now exists and
is checked two ways: `tests/test_packaging.py` guards the build inputs on every
run, and the `package` CI job builds `dist/ibackup-gui/ibackup-gui.exe` and
launches it with `packaging/smoke_test.py`. Neither covers a clean machine
without Python, and the artifact is unsigned, so until that work lands do not
advertise a downloadable installer or portable release.
