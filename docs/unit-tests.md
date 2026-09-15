# iPhone Archive — Tests and Validation Plan

Status: offline core/CLI hardening and its regression checkpoint are complete.
The GUI shell/theme/worker/models have offline coverage; live Windows appearance, full GUI
operations and the Windows release are **not validated**.
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
`tests/test_gui_previews.py`, `tests/test_gui_shell.py`, `tests/test_gui_gallery.py` and
`tests/test_gui_operations.py` set
`QT_QPA_PLATFORM=offscreen`, so no display is
needed and CI behaves like a developer machine. They
skip cleanly when PySide6 or pytest-qt is unavailable.

## 2. Existing test inventory

This table names actual files and their area, not a claim that every possible
scenario is covered or that the latest edited suite has passed.

| File (`tests/`) | Area |
|---|---|
| `test_config.py` | Archive path initialization/resolution. |
| `test_settings.py` | Settings persistence, defaults, validation, CLI config behavior. |
| `test_logging_setup.py` | Logging configuration and operation output. |
| `test_hashing.py` | Streaming hashes, known inputs and property checks. |
| `test_name_safety.py` | Sanitization, reserved names, collisions and property checks. |
| `test_archive_layout.py` | Placement, hardlink/copy behavior and safe paths. |
| `test_catalog.py` | Schema and repository behavior; upgrade coverage must track migrations. |
| `test_sidecar.py` | Metadata serialization/round trip. |
| `test_device.py` | Fake-device protocol plus mocked AFC behavior, not hardware evidence. |
| `test_importer.py` | Import/skip/dedup, album placement, process-exit recovery after placement/extra copy/sidecar, and refusal of ambiguous recovery files. |
| `test_dedup.py` | Read-only duplicate/storage reports. |
| `test_verifier.py` | Intact, missing and corrupted cataloged copies; no `--full` mode. |
| `test_albums.py` | Archive album summaries, not real `Photos.sqlite` compatibility. |
| `test_phone_diff.py` | Inventory/absence reconciliation. |
| `test_reclaim.py` | Device/content eligibility, selected reclaim, fresh checks and fail-closed deletion regressions. |
| `test_gallery.py` | Asset/album read models, partial recycling and location-filtered paths/counts, not HTML output. |
| `test_thumbnails.py` | Still-image generation/cache, video poster frames (orientation checked against ffmpeg, dark lead-in skipped, missing PyAV degrades), and unsupported-media behavior. |
| `test_progress.py` | Progress and cancellation handle. |
| `test_service.py` | Facade, recycle/restore/purge/reclaim, selection, locks/thread ownership. |
| `test_marks.py` | Stage/unmark/commit behavior. |
| `test_selection.py` | Partial/batch moves, conflicts, preflight and interrupted-operation recovery, including subprocess exit/restart rollback. |
| `test_recycle.py` | Partial recycle/restore/purge, invalid paths, missing copies, sidecar-failure recovery and committed-operation restart finalization. |
| `test_cli.py` | Command parsing, errors, confirmation and service wiring. |
| `test_e2e.py` | Offline pipeline and selected crash/resume scenarios. |
| `test_gui.py` | Offscreen window shell, entry point/style selection and Qt-free package/bootstrap imports in a fresh process. |
| `test_gui_theme.py` | Exact color/alpha/type tokens, scoped QSS, persisted theme bootstrap, live system/accent changes, high-contrast precedence, Qt 6.7 fallback and rendered solid opacity. |
| `test_gui_worker.py` | Real QThread service/device ownership, queued GUI delivery, archive-lock release, fake-device import/verify, detached request/result data, FIFO/overflow, coalesced progress, direct and queued cancellation, failure cleanup/restart without replay and window/application shutdown. |
| `test_gui_models.py` | Lazy 1 297-asset paging on the worker, roles and bounded queries, Qt model contracts/reentrant notifications, stale replies/indexes, persistent proxy selections, mutation barriers and exact-copy recycle/restore isolation. |
| `test_gui_previews.py` | Preview key/path validation, LRU eviction, background render and cache reuse, per-key coalescing, remembered failures and retry, cancel-on-scroll, pending bound, superseded/cancelled replies, archive/size switching, off-GUI-thread rendering, cross-thread rejection, bounded shutdown, concurrent cache writers, invalid persisted sizes and window ownership. |
| `test_gui_shell.py` | Drawn-glyph coverage and colour, album/library navigation keys, live counts and albums from real worker imports, preserved selection across refreshes, rail collapse, command-to-service mapping and availability rules, phone state from device failures, page/scope switching, archive close and shutdown cleanup, and status precedence over errors. |
| `test_gui_gallery.py` | Tile layout/eliding/size formatting, delegate painting from cache and scheduled renders, anchor-based viewport scanning cost, cancel-on-scroll safety when no tile is locatable, rubber-band/Ctrl/Shift selection, scope-gated selection bar and context menu, selection captured as exact copies on the GUI thread, stale-selection refusal after a reset, paging while scrolling, page errors surfaced in the status bar, gallery re-hosting across pages, and viewer open/navigate/page/close-on-reset with deletion on close. |
| `test_gui_operations.py` | Duration/estimate/eliding helpers, the cancellable set checked against the real service signatures in both directions, every result summary including a cancelled import reported as a partial success, problem detection and error-line listing, bounded duplicate reports, the move prompt's empty-name refusal and album-scope wording, archive open/create from a chosen folder, the progress dialog's own-request filtering, Hide keeping work running, a running dialog refusing to be destroyed, a clean hidden run closing itself and an erroring one coming back, cancellation reaching the request and being harmless after completion, quiet reads, a real move landing files in the album, album-scoped moves, stale-selection refusal, refused submissions and failures staying on screen, window close closing a running dialog, replaced dialogs/viewers not orphaning their successors, and preview clearing quiescing the loaders. |
| `test_win32_effects.py` | Mocked platform/build guards, native preference queries, pointer-sized HWND/32-bit arguments, HRESULT/load failures and opt-in Mica fallback. Not a live Windows probe. |

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
| Album metadata | Supported and unsupported `Photos.sqlite` schemas, WAL/snapshot consistency, inaccessible DB, explicit warnings and `_Unsorted` fallback. |
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
bounded thumbnail queues, full parity map and native accessibility/theme
behavior. Perform the
Mica probe on Windows 11 22H2+ using `ibackup-gui --mica-probe` and retain its
result/logs. Confirm both themes, wallpaper tint, native title bar, resize/snap/
maximize, high contrast, transparency disabled and battery saver. Normal
launches remain solid until that client-painting path is proven.

Release requires passing Windows CI, a Windows-built CLI executable smoke test
on a clean machine without Python, dependency/license notices, versioned
artifacts, and separately validated GUI packaging when it exists. Until then,
do not advertise a downloadable installer or portable release.
