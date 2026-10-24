# Progress Log — iPhone Archive (`ibackup`)

Living status document so work can be **resumed after any interruption**. Update
this whenever a todo changes state or a decision is made. The source-of-truth
task list is the session todo DB / `todos.md`; this file is the human-readable
resume point.

_Last updated: 2026-10-16 (map: ignore a point, Previous/Next point; previously 2026-10-13: the trip map is now a real, zoomable Leaflet/
OpenStreetMap map embedded via Qt WebEngine, replacing the offline hand-drawn
canvas, after the user explicitly asked for a Google-Maps-like experience with
zoom)._

## Current status

- **Open quality items (2026-10-23):** `ruff check`, `ruff format --check`
  and `mypy --strict` are clean again, and the two `test_gui_settings.py`
  Windows path-separator failures are fixed. Still flaky:
  `WinError 5` on atomic replace when another process briefly holds the
  file (seen in `test_recycle.py` sidecars and in
  `test_cli.py::test_marks_purge_requires_typed_confirmation` on
  `settings.json`; no retry yet); a Qt access violation that hangs
  `test_gui_settings.py::test_the_window_saves_and_applies_what_was_edited`
  in `waitUntil` (run with `-p no:faulthandler` and a timeout, or the dump
  log grows without bound); and
  `test_gui_worker.py::test_close_then_open_serializes_archive_switches`.
- **Trip-map travel modes (2026-10-12):** legs can be tagged with how the
  user travelled; stored per view in `trip_segments` (schema v7).

- **iCloud Shared Albums (2026-10-11):** imported into
  `Photos/_Shared Albums/<name>/`, listed separately in the GUI and by
  `ibackup albums --shared`, excluded from reclaim. The first version
  (`ZKIND = 1505`) found nothing on the user's iPhone 12 (iOS 26.4); fixed to
  read iOS 26 `ZSHARE` rows (18 albums, 6,150 items found from a database
  copy). Most shared media is not cached on the phone, so it is imported as
  low-resolution previews from the thumbnail cache until the user opens the
  album in Photos and imports again. **The user must re-run Import** to get
  their shared albums. Next: a full end-to-end import run on the phone.

- **Map is now a real, zoomable OpenStreetMap view:** `gui/mapview.py` embeds
  a `QWebEngineView` running a self-contained Leaflet.js page (vendored at
  `gui/webassets/leaflet/`, BSD-2-Clause) with an OpenStreetMap tile layer,
  full mouse/touch pan and zoom, a trip polyline, and start/end-highlighted
  circle markers with popups. **This is the first and only feature that makes
  network calls on the user's behalf** (fetching tiles from
  `tile.openstreetmap.org`), a deliberate, explicit exception the user asked
  for after an earlier, more conservative offline-grid attempt was judged not
  good enough. Tiles are cached to disk via a dedicated, named
  `QWebEngineProfile` ("ibackup-map-tiles", 200MB disk cache) so re-viewing a
  previously-seen area needs the network again only for genuinely new tiles.
  A descriptive User-Agent is set per OpenStreetMap's tile usage policy. If
  the network is unavailable, the map UI (zoom, pan, markers, trip line)
  still works, just without tile imagery.

- **Gallery and control sizing:** thumbnail tiles in the main photo grid
  (`TILE_IMAGE`) grew from 120px to 160px, every button's minimum/fixed height
  (`CONTROL_HEIGHT`, used across the whole GUI including the selection bar's
  "Mark" button and the Marked page's action buttons) grew from 32px to 36px,
  and the line-art glyph icons (`ICON_SIZE`, used by the navigation pane rows
  including "Marked" and the toggle/settings buttons) grew from 16px to 20px,
  after user feedback that images, buttons and the navigation icon shown when
  opening the Marked page were hard to see.
- **Offloaded-preview lookup cache:** each offloaded-photo preview lookup
  (`afc_device_offloaded_preview`) costs two AFC round-trips. On a device with
  thousands of offloaded album paths this made every single import slow, not
  just the first. Resolved paths are now cached on disk per device UDID
  (`.ibackup-device-cache/offloaded-preview-cache.json`) so a later import of
  the same still-offloaded photo skips AFC entirely. Import itself was already
  incremental (it never re-copies bytes for assets already in the catalog);
  this removes the regression that made *enumeration* slow on every run too.
- **Offloaded-photo previews:** albums whose originals are offloaded ("Optimize
  iPhone Storage") are no longer silently incomplete. The AFC adapter mirrors
  each missing DCIM path into `/PhotoData/Thumbnails/V2` (the same cached JPEG
  iOS itself uses for degraded previews) and imports that file instead, named
  with an `" (offloaded preview)"` suffix and flagged via the
  `assets.is_offloaded_preview` column (schema v3). Lookup failures never break
  enumeration of real media. This app cannot force iCloud to download an
  original over USB/AFC (that's not something the protocol exposes); getting
  the full-resolution original still requires either opening the photo in the
  Photos app on the phone, or disabling "Optimize iPhone Storage", before
  reimporting.
- **Album placement reconciliation:** moving a photo between albums on the
  phone (or into/out of an album entirely) used to leave the old copy behind —
  album growth was strictly append-only, by design, so a move looked like a
  new album *plus* a stale, now-orphaned copy of the old one. `importer_sync_
  albums` now compares the phone item's *current* full album membership
  against what's archived and reconciles both directions: it still adds a
  copy for any newly discovered album (a photo can genuinely belong to more
  than one at once), but it also removes any existing copy for an album the
  phone no longer reports, including a stale `_Unsorted` copy once a photo
  gains its first real album, and restores an `_Unsorted` copy if a photo
  loses all album membership. New copies are always created before stale ones
  are removed, so an interrupted import can never drop an asset below one
  valid on-disk copy. Recycle-bin copies are untouched — this is purely about
  the `Photos/<Album>` / `Photos/_Unsorted` placement matching the phone.
- **Offloaded-preview upgrade on reimport (schema v4):** a preview now
  remembers the real album-member path it stands in for
  (`assets.offloaded_original_path`). When a later import finds the real
  original back on the phone at that same path, the existing preview asset is
  upgraded in place — content/phone identity replaced, old low-resolution file
  deleted, same asset id kept so album links, marks, and sidecars all carry
  over — instead of archiving a second, duplicate asset. Reported via a new
  `ImportResult.upgraded_count` surfaced by both the CLI and GUI import
  summaries.
- **Album correction:** earlier filename fallback assigned offloaded photos'
  albums to unrelated local files. The current adapter uses exact paths for
  modern Photos databases; older filename-only schemas require uniqueness
  across the whole database and USB inventory. Since album reconciliation
  (`d7eea11`), reimporting removes existing wrong album copies of photos still
  on the phone (they move to their real album or `_Unsorted`); photos no
  longer on the phone keep their old placement. Back up existing archives
  before that reimport.
- **Phase:** Phase 2 — building the GUI. Phase 1 (core engine + full CLI) and
  the core-hardening checkpoint are complete offline.
- **State:** the UI-sketch gate **passed on 2026-09-11**; the sketch and its
  clickable mock were approved and `gui-theme` / `gui-frontend` were unblocked.
  `gui-frontend` has been broken into the twelve steps listed in §"Phase 2 GUI
  steps" below and in `plan.md` §2b.
- **Next action on resume:** Phase 2 step work is finished; the remaining gates
  are live Windows theme/Mica qualification, real-iPhone destructive
  validation and the release milestones (`windows-cli-release`,
  `windows-gui-release`). Steps 1-12 are implemented. The GUI can open or
  create an archive, import,
  verify, scan the phone, check the phone, report duplicates, refresh counts,
  clear the preview cache and move a selection into an album - all off the GUI
  thread, behind the sketch's progress dialog where the work is long. Step 9
  added the destructive half: moving copies to the `Deleted/` recycle bin,
  restoring them, purging permanently, the deleted-on-phone review, the marks
  queue and phone-space reclamation. **Nothing destructive reaches the worker
  without passing the confirmation dialog**, and anything permanent requires the
  word `DELETE` to be typed, mirroring the CLI's `--confirm`. Step 10 added the
  §7b settings dialog, which also closed the aggregate `settings-store` item:
  every stored preference is now editable and every one of them has a consumer.
  **No command or navigation verb is deferred any more.** Step 11 proved the
  parity claim instead of asserting it: `gui/parity.py` declares where each
  service operation is reachable and `tests/test_gui_parity.py` checks that
  declaration against the real CLI, the real service and the real GUI source.
  Writing it found and closed the last real gap - album-scoped and copy-scoped
  marks, which the CLI had and the GUI did not. Step 12 packaged the app:
  `packaging/ibackup.spec` freezes `ibackup-gui` into a one-directory Windows
  build with a self-drawn icon and a version resource, and
  `packaging/smoke_test.py` launches the built `.exe` offscreen and fails on an
  early exit or a traceback. **This step was actually run on Windows 11**
  (PyInstaller 6.22, Python 3.11): `dist\ibackup-gui\ibackup-gui.exe` built and
  passed the smoke test. Live Windows theme/Mica qualification remains pending.
- **Not yet validated:** real-iPhone *destructive* behaviour, Mica and native
  window chrome, and the Windows CI workflow as a whole. The Windows `.exe`
  packaging **has** now been built and smoke-tested locally on Windows 11, and
  the read path has been exercised against a real iPhone 12 (see the
  hardware-validation entries below); everything else is Linux + fake device.
- **Release:** step 12 delivers a build recipe, not a release. `ibackup-gui`
  exists as a real entry point that opens an archive, browses it and runs every
  operation, and it can now be frozen into `dist\ibackup-gui\`. Signing, an
  installer, bundled notices, a clean-machine (no-Python) install test and the
  still-missing CLI recipe belong to `windows-cli-release` /
  `windows-gui-release`.

## Phase 2 GUI steps

Ordered, one commit each, bottom-up with tests. Full descriptions in `plan.md`
§2b; live state is in the todo DB and `todos.md`.

| # | Step | State |
|---|---|---|
| 1 | `gui-scaffold` — package, entry point, window shell, offscreen tests | **done** |
| 2 | `gui-theme` — WinUI tokens, light/dark, guarded native effects | **done offline; Windows probe pending** |
| 3 | `gui-worker` — thread owning `AppService`, progress/cancel | **done offline** |
| 4 | `gui-models` — lazy-paging asset/album models, selection scope | **done offline** |
| 5 | `gui-thumbnail-loader` — background previews, bounded cache | **done offline** |
| 6 | `gui-shell` — navigation, pages, command bar, status bar | **done offline** |
| 7 | `gui-gallery` — grid, multi-select, viewer | **done offline** |
| 8 | `gui-ops-safe` — import, verify, scan, dedup, move | **done offline** |
| 9 | `gui-ops-destructive` — typed-DELETE gating, deleted/marks/reclaim | **done offline** |
| 10 | `gui-settings` — six panels; also closes `settings-store` | **done offline** |
| 11 | `gui-parity-tests` — fails if any CLI action lacks a GUI surface | **done offline** |
| 12 | `gui-packaging` — PyInstaller `.exe` | **done; built + smoke-tested on Windows** |

Step 3 centralizes the threading backbone: the window owns a lazy
`WorkerController`, whose dedicated thread constructs/opens/uses/closes
`AppService`. Requests are serialized and bounded (32 outstanding, plus a
reserved shutdown slot); data is copied across the boundary and live resources
are rejected. Progress is coalesced, cancellation uses the existing Event, and
window close waits asynchronously for safe shutdown. No archive/device is
automatically opened, and no archive-operation controls exist yet.

Step 4 adds `MainWindow.models`: lazy asset/album metadata and shared selection,
with all/album/unsorted/recycled scopes, default 128-row pages plus lookahead,
and one outstanding page per model. Metadata accumulates until reset; decoded
image caching belongs to step 5. Mutation barriers and model generations reject
stale pages/selections; insertion/reset notifications cannot reenter paging or
change selection scope halfway through an insertion. Proxy selections require
persistent indexes captured while valid. Backend optional pagination preserves
the CLI's existing unbounded defaults. The visible grid is still a later step.

Step 2 retains solid client painting for normal launches. The opt-in
`ibackup-gui --mica-probe` requests Mica plus experimental translucent Qt
painting on Windows; accepted DWM requests are **not** visual proof. Validate
the probe on Windows 11 22H2+ before enabling transparent client painting by
default. Windows 10, unsupported attributes, disabled transparency,
high-contrast mode and native-call failures use solid/native fallback.

### Step 11 validation checkpoint

2026-09-17, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest -q --cov --cov-fail-under=85` | 713 tests, 1 skipped; 90% coverage. |
| `ruff check .` / `ruff format --check .` | Passed; 118 files. |
| `mypy src` / `mypy --platform win32 src` | Passed, 56 source files. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| Parity test proven to fail | Three separate reverts: deleting a declared surface, making a surface stop submitting its operation, and adding a new CLI command with no GUI equivalent. Each failed a different parity test with a message naming the gap. |

The end-to-end flows ran offscreen against a fake device inside `tmp_path`: an
empty folder was turned into an archive, imported, verified, marked, committed
to the recycle bin and restored using only GUI surfaces, with the assertions
made against the files on disk. The mark-scope prompt was exercised in all
three of its outcomes - copy, asset and dismissed - and dismissing it staged
nothing. No real device, no Windows build and no Windows CI run were involved.

### Step 10 validation checkpoint

2026-09-16, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest -q --cov --cov-fail-under=85` | 699 tests, 1 skipped; 90% coverage. |
| `ruff check .` / `ruff format --check .` | Passed. |
| `mypy src` / `mypy --platform win32 src` | Passed, 55 source files. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| Step-10 safety guards | Confirmed to fail with their fix reverted: reading `confirm_word_required` back from its widget, and reopening a remembered folder without checking it is still an archive. |

Preferences were edited, saved, reset and forgotten against the real settings
store redirected into `tmp_path`. **No archive was opened, created or modified
by any settings operation**, and the preferences-only service was shown to
refuse an archive operation rather than fall back to the working directory. The
reopen-on-startup preference was exercised against a missing folder, a real
archive and a disabled preference. No Windows builds or Windows CI runs were
performed.

### Step 9 validation checkpoint

2026-09-15, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest -q --cov --cov-fail-under=85` | 683 tests, 1 skipped; 90% coverage. |
| `ruff check .` / `ruff format --check .` | Passed; 114 files formatted. |
| `mypy src` / `mypy --platform win32 src` | Passed, 54 source files. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| Every step-9 safety guard | Confirmed to fail with its fix reverted (six reverts). |

Recycling, restoring, purging, marking, mark commits and reclamation dry runs
were exercised against a fake device and temporary archives, and the purge tests
assert that the bytes really are gone. **No real phone files were deleted**:
`AfcDevice.device_delete` still refuses unconditionally, so reclamation cannot
free space on a real iPhone yet. No Windows builds or Windows CI runs were
performed.

### Step 8 validation checkpoint

2026-09-15, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest -q --cov --cov-fail-under=85` | 647 tests, 1 skipped; 89.94% coverage. |
| `ruff check .` / `ruff format --check .` | Passed; 110 files formatted. |
| `mypy src` / `mypy --platform win32 src` | Passed, 51 source files. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| Every step-8 regression test | Confirmed to fail with its fix reverted. |

Imports, verifies and moves were exercised against a fake device and temporary
archives. No real-phone operations, Windows builds or Windows CI runs were
performed.

### Step 7 validation checkpoint

2026-09-14, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest -q --cov --cov-fail-under=85` | 602 tests, 1 skipped; 89.78% coverage. |
| `ruff check .` / `ruff format --check .` | Passed; 107 files formatted. |
| `mypy src` / `mypy --platform win32 src` | Passed, 49 source files. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| Every step-7 regression test | Confirmed to fail with its fix reverted. |

No real-phone operations, Windows builds or Windows CI runs were performed.

### Step 4 recovery checkpoint

2026-09-14, Linux host, existing Python 3.12 virtual environment:

| Command / evidence | Result |
|---|---|
| `pytest tests/test_gui_models.py tests/test_gui_worker.py tests/test_gui.py tests/test_gallery.py tests/test_albums.py tests/test_service.py -ra` | 115 passed. |
| `pytest --cov=iphone_archive --cov-report=term --cov-fail-under=85 -ra` | 524 passed, 1 skipped; 89.86% coverage. |
| `ruff check .` / `ruff format --check .` | Passed; 96 files formatted. Mock review artifacts explicitly excluded as documented. |
| `mypy src` / `mypy --platform win32 src` | Passed, 42 source files. Windows target is static analysis only. |
| `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 source files. |
| `pip check` / `git diff --check` | Passed. |
| Follow-up review of step 4 | No significant remaining findings. |

The single skipped case remains the inapplicable purge/publication checkpoint.
No real-phone operations or Windows builds were performed. The Windows CI
commands were exercised locally where applicable, not on a Windows runner.

### Final core-hardening validation report

2026-09-09, Linux host, Python 3.12, source revision `96a17e8`:

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest --cov=iphone_archive --cov-report=term-missing --cov-fail-under=85 -rs` | 351 passed, 1 skipped; 90.79% coverage. |
| `.venv/bin/ruff check .` | Passed. |
| `.venv/bin/ruff format --check .` | Passed, 85 files formatted. |
| `.venv/bin/python -m mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 modules. |
| `.venv/bin/python -m mypy src/iphone_archive` | Passed, 36 modules. |
| `.venv/bin/python -m mypy --platform win32 src/iphone_archive` | Passed, 36 modules; static analysis, not Windows execution. |
| `.venv/bin/python -m pip check` | No broken requirements. |
| `git diff --check` | Passed. |

The skipped parametrized case is purge at the final-publication checkpoint:
purge never publishes a final media filename. Other crash boundaries include
actual subprocess termination, disk-full/ownership-write faults, and restart
recovery. The batch-journal scaling regression requires doubling the selection
to write less than 2.2 times the journal bytes.

Independent review's archive-ownership and quadratic-journal findings are
resolved and re-reviewed. Its device/import findings prompted primary-album
association for repair copies, retention of restored missing copies, and an
indexed presence query, with additional regression coverage.
Do not infer Windows CI, live-device, or release qualification from this report.

## Approval gates (must not be passed without explicit approval)

1. **Docs approval** — before writing any code. _(approved)_
2. **UI-sketch approval** — before writing any GUI code. _(approved 2026-09-11)_

## How to resume

1. Read this file, then `docs/plan.md` (plan) and `docs/todos.md` (checklist).
2. Set up the dev env per `docs/development.md` (create/activate `.venv`,
   `pip install -e ".[dev]"`).
3. Find the next actionable todo (dependencies done, status pending).
4. Implement it **with tests**, run `pytest`, then update this file and
   `todos.md`.

## Milestones

- [x] Phase 0 — documentation complete (specs, user README, user-stories,
      structure, unit-tests, development, plan, todos, progress).
- [x] Docs approved.
- [x] Phase 1 — core + CLI offline baseline.
- [x] Core hardening and offline regression validation.
- [ ] Windows/iPhone read, album and large-video validation.
- [ ] Controlled real-phone destructive/recovery qualification.
- [x] UI sketch and clickable mock approved (2026-09-11).
- [x] Phase 2 — GUI: scaffold, theme, worker, models, preview loader, shell,
  gallery, safe and destructive operations, settings, parity tests and Windows
  packaging implemented; live Windows theme/Mica qualification still pending.
- [x] Offline core/CLI checkpoint complete; GUI foundation/model tests now exist.
- [x] Windows packaging (`.exe`) — build recipe plus a passing artifact smoke
      test on Windows 11; signing/installer/clean-machine test remain release work.

## Change log

- 2026-10-23 — **Fixed: device cache lived in the working directory.** The
  temporary `Photos.sqlite` copy and the offloaded-preview cache were written
  to `<cwd>/.ibackup-device-cache`. A GUI started from a shortcut or a frozen
  build may have an unwritable or shared cwd; the failed copy was logged as
  "Photos metadata unavailable", and reconciliation then moved every album
  copy into `_Unsorted` (spec §12 known limitation). Both now use
  `settings_cache_directory()/device-cache` (`%LOCALAPPDATA%\ibackup\cache`;
  under `IBACKUP_CONFIG_DIR` in tests). An existing cwd cache is simply no
  longer read (the next import re-resolves previews once). Tests:
  `tests/test_device.py` paths updated, 1 new. Docs: README, readme-user,
  specifications §9, structure, unit-tests.

- 2026-10-23 — **Fixed: offloaded-preview upgrade matched on path only.**
  `repository_find_offloaded_preview_by_original_path` now also requires a
  source identity from the importing device, so a second (or reset) phone's
  unrelated photo at the same `/DCIM` path no longer deletes and replaces
  another phone's preview. When the original's bytes already exist as a
  different asset, the preview is kept and the item is a duplicate; before,
  the `UNIQUE(sha256)` update failed on every import, which also blocked
  presence publishing. Tests: 2 new in `tests/test_importer.py`. Docs:
  specifications §9 step 4b, readme-user, unit-tests.

- 2026-10-23 — **Fixed: album reconciliation could delete an asset's only
  copy.** `importer_sync_albums` unlinked stale album copies before the
  item's catalog commit; if the item then failed (e.g. a sidecar write
  error) or the process died, recovery removed the new copies and the
  catalog rolled back to point at the deleted file. Stale copies (and an
  upgraded preview's old files) are now retired in the item's import journal
  (`ImportJournal.retire`, path + file identity) and deleted by
  `importer_recover` only for committed items, and only while the path is
  still the recorded inode. Tests: 2 new in `tests/test_importer.py`. Docs:
  specifications §12, plan, unit-tests.

- 2026-10-23 — **Quality gates green again.** `tests/test_importer.py`
  reformatted; `core/exif.py` mypy errors fixed (`pillow_heif` does not
  re-export `register_heif_opener`; `int()` on an `object` returns `Any`);
  `test_gui_settings.py` now compares `Path` objects, so it passes with
  Windows separators. No behaviour change.

- 2026-10-17 — **Ignored point no longer bridged.** Ignoring a map point keeps it (greyed) and now just removes the line across it: no leg joins its previous/next points any more (mapRedraw skips non-adjacent pairs). Tests updated (`test_gui_mapview.py`); specifications §16.4, readme-user, user-stories US-G11, unit-tests adjusted.
- 2026-10-17 — **Map window maximizable.** `MapDialog` now has Maximize/Minimize buttons and a size grip, so the map can fill the screen and be resized freely.

- 2026-10-16 — **Map: ignore a point; Previous/Next point buttons.** Two
  requested features, tracked as todos `map-ignore-point` and `map-prev-next`.
  *Ignore:* the point popup has **Ignore this point** / **Include this
  point**; an ignored point is greyed and left out of the legs, arrows,
  Start/End pins and stepping, but stays on the map so it can be included
  again. Persisted per view in new table `trip_ignored_points` (**schema v8**,
  `CREATE TABLE IF NOT EXISTS` migration, cascade on asset delete);
  `core/trip.py` `trip_ignored()` / `trip_set_ignored()`; service
  `app_service_trip_ignored` / `app_service_set_trip_ignored` (parity map,
  operation titles/summaries); window chain Map → list_locations →
  trip_modes → trip_ignored → `MapDialog(ignored=…, on_point_ignored=…)`.
  Travel modes are not touched by ignoring: reconciliation still sees every
  located photo, a leg across an ignored point shows the mode of its first
  part and saves a mode for every pair it spans. The page now redraws from
  `mapRedraw()` (legs carry `fromIndex`/`toIndex`; `fitBounds` must precede
  it). *Prev/Next:* `WebMapWidget` header buttons call page `mapStep(±1)`
  (pan + open popup, skip ignored, wrap). Tests: 7 new in
  `tests/test_gui_mapview.py`, 3 in `tests/test_trip.py`. Docs updated:
  README, readme-user, specifications (§8, §16.4), plan, structure,
  unit-tests, development, todos, user-stories (US-G11), ui-sketch §8.
  Full suite: only the two known Windows path-separator failures in
  `test_gui_settings.py` remain.

- 2026-10-16 — **Fixed: GUI crashed while zooming a map with many points.**
  Access violation in `Qt6WebEngineCore.dll` (PySide6/Qt 6.11.2, GPU path);
  reproduced headless with 500/3000 points and rapid wheel events, gone with
  `--disable-gpu`. `application_create` now adds that flag to
  `QTWEBENGINE_CHROMIUM_FLAGS` before Qt starts (user flags kept). Test added
  in `tests/test_gui.py`; `docs/unit-tests.md` updated.

- 2026-10-12 — **Verified: travel modes persist across imports.** Question:
  can a photo be uniquely identified so its modes survive re-import? Yes:
  catalog assets are keyed by content SHA-256 (`assets.sha256` UNIQUE) and
  `trip_segments` by the stable `assets.id`; imports fast-skip known phone
  identities or dedup onto the existing row, previews upgrade in place, and
  album ids are stable. No code change was needed; four new tests in
  `tests/test_trip.py` prove re-import, insertion by import (split), preview
  upgrade and album-scope persistence (18 cases, all pass). Identity is lost
  only when the bytes change (phone-side edit; evicted shared original
  re-imported as a preview); the phone's `ZUUID` is not captured — new
  follow-up `phone-asset-uuid`. Docs: `readme-user.md` (map: importing again
  keeps modes), `specifications.md` §16.4 (persistence across imports),
  `unit-tests.md`, `todos.md`.

- 2026-10-12 — **Trip map: travel modes between pins.** New `core/trip.py`:
  `TRIP_MODES` (`car`, `plane`, `foot`, `bike`, `tuktuk`, `bus`, `taxi`,
  `boat`), `TripSegment(from_asset_id, to_asset_id, mode)`,
  `trip_reconcile(connection, scope, asset_ids)` and
  `trip_set_mode(connection, scope, from, to, mode | None)`, validating scope
  (non-empty, ≤ 64), distinct positive ids, a known mode and that both assets
  exist. **Schema v7**: table `trip_segments(scope, from_asset_id,
  to_asset_id, mode, PK(scope, from, to))`, both asset FKs `ON DELETE
  CASCADE`; the v6→v7 migration is the `CREATE TABLE IF NOT EXISTS`, no
  column changes. Scope is the map's navigation key (`all`, `unsorted`,
  `recycled`, `album:<id>`), so modes are per view. Reconciliation runs each
  time a map opens against the plotted capture-ordered ids and is committed:
  consecutive pairs keep their mode; a pair split by inserted photos is
  deleted and every leg it spans inherits its mode unless already tagged; a
  pair with a missing photo (removed, recycled, moved out, no location) or
  reversed order is deleted, and its mode does not return. Service:
  `app_service_trip_modes` / `app_service_set_trip_mode` (commit, rollback on
  error), GUI-only, declared in `gui/parity.py`; titles "Reading travel
  modes"/"Saving travel mode", summaries "Map ready: N legs have a travel
  mode." / "Travel mode saved." / "Travel mode cleared.". `main_window`: Map
  → `app_service_list_locations` → (≥ 2 located) `app_service_trip_modes` →
  new `main_window_open_map()` → `MapDialog(segments=…, on_mode_changed=…)`;
  a failed or cancelled mode read still opens the map without modes.
  `mapview`: `MODE_STYLES` (Car 🚗, Plane ✈️ dashed, On foot 🚶 dotted, Bike
  🚲, Tuk-tuk 🛺, Bus 🚌, Taxi 🚕 dashed, Boat ⛴️ dashed); one polyline per
  leg styled by mode (untagged blue solid), arrows in the mode colour with an
  emoji badge, a wide invisible twin line for clicking, tooltip "<emoji>
  <label> · Click to set how you travelled", popup "How did you travel from
  photo n to n+1?" with a 3-column mode grid plus Clear; edits log
  `ibackup-mode:<leg>:<mode|none>`, parsed by `mapview_parse_mode_change`
  (known modes, legs 0..count-2) and emitted as
  `WebMapWidget.mode_changed(from_asset_id, to_asset_id, mode)`. Zero-length
  legs cannot be tagged. `MapPoint.mode`; `mapview_points(assets, segments)`;
  Leaflet `preferCanvas`. Caption ends "Click a point to see its photo, or a
  line to set how you travelled." Tests: new `tests/test_trip.py` (14 cases),
  `test_gui_mapview.py` now 20 tests (incl. a real WebEngine tag/clear round
  trip), `test_gui_parity.py::test_the_map_saves_and_restores_travel_modes`
  with a `located=True` fixture option. Coverage 90%, `core/trip.py` 100%.
  Full suite: the two pre-existing `test_gui_settings.py` failures; **flaky:**
  `test_gui_worker.py::test_close_then_open_serializes_archive_switches`
  failed once with Windows "Access is denied" renaming the `settings.json`
  staging file, passed on 3 reruns (open item `flaky-worker-archive-switch`,
  alongside `flaky-recycle-restart`). Also: `ruff format` reformatted
  `gui/review.py` and `gui/shell.py` (no behaviour change), **resolving that
  part of the earlier formatting open item**; still open:
  `tests/test_importer.py` formatting and 2 `mypy --strict` errors in
  `core/exif.py`. Docs updated: `README.md`, `readme-user.md`,
  `specifications.md` (§8 schema v7, §16.4), `plan.md`, `structure.md`,
  `development.md`, `unit-tests.md`, `user-stories.md` (new US-G10),
  `todos.md`, `ui-sketch/README.md` §8.

- 2026-10-12 — **Trip map: Start/End pins, direction arrows and photo
  popups.** `gui/mapview.py`: labelled Leaflet `divIcon` pins — "Start"
  (green, above its point) and "End" (red, below it, so a round trip shows
  both), "Start / End" for a single point; clicking a pin opens that point's
  popup. One direction arrow per segment at its midpoint, angle computed once
  in Web Mercator (conformal, so valid at every zoom); zero-length segments get
  none, and arrows show only for segments ≥ 40 px on screen, refreshed on
  `zoomend`. Every point has a popup: picture, file name, capture time
  (`YYYY-MM-DD HH:MM`), "n of N", and a note for previews ("Low-resolution
  preview (original not on the phone)", detected by the
  `" (offloaded preview)"` marker) or videos ("Video (poster frame)"). The
  picture is rendered from the **archived** copy with `thumbnails_get` at
  320 px on a 2-thread `QThreadPool` and pushed in as a `data:` URI; nothing
  is fetched from the phone and the page gets no file access. Requests arrive
  as console messages `ibackup-photo:<index>`, intercepted by `MapPage`;
  `mapview_parse_request` accepts only in-range numeric indices; each point
  renders at most once per plot. Messages: "No archive open", "No archived
  copy", "No preview available (…)". Popup elements are cached per point
  because Leaflet re-runs content functions on `update()` (bug found and
  fixed during the work; regression test). `MapDialog` is 900×640,
  delete-on-close and waits for in-flight renders (`mapview_shutdown`);
  `main_window.py` passes the worker's `archive_root`. New caption: "N located
  photos, plotted in capture order from Start to End. Click a point to see its
  photo." No new service operation (parity map unchanged), no new
  dependencies. `tests/test_gui_mapview.py` now has 16 tests, including real
  WebEngine page execution (4 points → 4 markers, 2 arrow segments, 2 pins;
  `openPopup` emits `ibackup-photo:1`) and an end-to-end popup-shows-the-
  picture regression. Full suite: the same two pre-existing
  `test_gui_settings.py` failures; **flaky:**
  `test_recycle.py::test_restart_finalizes_catalog_committed_before_cleanup[restore]`
  failed once in a full run, passed on 3 reruns and passes at HEAD (open item
  `flaky-recycle-restart` in `todos.md`). Docs updated: `README.md`,
  `readme-user.md` (how to read the map), `specifications.md` §16.4,
  `structure.md`, `development.md` (bridge rules), `unit-tests.md`,
  `user-stories.md` (US-G9), `todos.md`, `ui-sketch/README.md` §8.

- 2026-10-11 — **Fixed: shared albums not found on a real iPhone (iOS 26.4).**
  Testing `0cf5b4f` on the user's iPhone 12 imported no shared albums. A copy
  of its `Photos.sqlite` showed no `ZGENERICALBUM` row with `ZKIND = 1505`
  (kinds present: 2 ×71, 1506 ×9, 1510 ×8, 16xx, 35xx, 39xx, 400x). On iOS 26
  shared albums are `ZSHARE` rows (entity `CollectionShare`, `Z_ENT` 67,
  `ZCOLLECTIONSHAREKIND` 2) with `ZTITLE` (e.g. "India 2024") and
  `ZSCOPEIDENTIFIER` = the GUID folder under
  `/PhotoData/PhotoCloudSharingData/<personId>/<GUID>/100CLOUD`; assets link
  via `ZASSET.ZCOLLECTIONSHARE -> ZSHARE.Z_PK`, not the `Z_33ASSETS` join.
  New `albums_collection_share_query()` (requires `ZASSET.ZCOLLECTIONSHARE`,
  `ZSHARE.ZTITLE` and `ZDIRECTORY`; skips trashed shares/assets via
  `ZTRASHEDSTATE`); `albums_parse_shared_albums()` merges it with the
  `ZKIND = 1505` path (kept as an unvalidated older-iOS fallback), still
  limited to `PhotoCloudSharingData`. Result: 18 shared albums, 6,150 items
  (India 2024 = 1,473). Only a small fraction is cached (India 2024: 13 of
  1,473 files in its `100CLOUD`), but iOS keeps a thumbnail for every item
  under `/PhotoData/Thumbnails/V2/PhotoData/PhotoCloudSharingData/.../<file>/
  5005.JPG` (35/35 sampled). `afc_device_shared_items()` therefore falls back
  to `afc_device_offloaded_preview()` for uncached members
  (`is_offloaded_preview`, `offloaded_original_path` = the shared path, on-disk
  preview cache), so they upgrade in place once downloaded; the old info log
  is replaced by an always-emitted WARNING summary ("Shared albums: N albums,
  M items; X full-resolution copies cached on the phone, Y imported as
  low-resolution previews, Z unavailable. …"). New tests
  `test_ios26_shared_albums_are_read_from_zshare` and
  `test_afc_uncached_shared_items_fall_back_to_thumbnails` (13 in
  `tests/test_shared_albums.py`). Reclaim now also skips every
  `is_offloaded_preview` item (a thumbnail is never the original; new
  `test_reclaim_never_offers_thumbnail_previews`, 14 tests in the file).
  User-visible: re-run Import; shared albums
  appear mostly as `(offloaded preview)` copies until opened in Photos.
  Still unverified: a full end-to-end import run on the phone, whether shared
  copies' bytes differ from the owner's DCIM originals, owner name (no column
  in `ZSHARE`; maybe `ZSHAREPARTICIPANT`). Docs updated: `README.md`,
  `readme-user.md`, `specifications.md` (§9, §12.1, §13, §15),
  `structure.md`, `unit-tests.md`, `user-stories.md` (US-D1b), `todos.md`,
  `plan.md`, ADR-0008 (new hardware-validation addendum) and the ADR index.

- 2026-10-11 — **iCloud Shared Albums.** `Photos.sqlite` albums with
  `ZKIND = 1505` (`core/albums.py` `SHARED_ALBUM_KIND`) are read through the
  same runtime-discovered join as user albums (new `kind` parameter on
  `albums_membership_query`/`albums_parse_photos_database`;
  `albums_parse_shared_albums()` keeps only keys under
  `/PhotoData/PhotoCloudSharingData`). Schemas without `ZKIND` yield no shared
  albums; user-album parsing (`ZKIND = 2`) is unchanged. `AfcDevice` parses
  shared membership from the same database copy, then
  `afc_device_shared_items()` walks the sharing cache only when membership
  exists and yields only named members, carried in the new
  `PhoneItem.shared_album_names`; walk failures log "shared albums
  unavailable", uncached members are skipped with an info log, and there is
  no preview fallback. Shared albums are stored in
  `Photos/_Shared Albums/<name>/` with `albums.kind = 'shared'` and
  `safe_name = '_Shared Albums/<name>'`, so they never merge with a same-named
  user album; no schema change (`SCHEMA_VERSION` still 6).
  `importer_album_targets()` puts user albums first (primary copy) then
  shared albums; extra copies and reconciliation treat both alike. Reclaim
  never offers shared-cache files; move-to-album prefers the user album on a
  name clash. `AlbumSummary.kind`; `ibackup albums` tags `(shared)` and
  `ibackup albums --shared` lists only them; the GUI lists a separate
  "Shared albums" navigation section with a `shared-album` glyph and an
  "(iCloud Shared Album)" tooltip; `gui/parity.py` names both sections. New
  `tests/test_shared_albums.py` (11 tests) and
  `test_gui_shell.py::test_navigation_lists_shared_albums_in_their_own_section`;
  those 12 were re-run for this docs update and pass. Reported full-suite
  result: all pass except the two pre-existing Windows path-separator
  failures in `tests/test_gui_settings.py`
  (`test_reset_asks_once_and_forget_names_the_archive`,
  `test_cache_and_folder_buttons_need_something_to_act_on`, also failing at
  HEAD); coverage 90%. **Not validated on a real iPhone:** `ZKIND = 1505` and
  the `PhotoCloudSharingData` `ZDIRECTORY` layout follow known iOS
  conventions and the existing `tests/test_albums.py` docstring. The album
  owner is not captured. Only media already cached on the phone can be
  imported; still local USB, no iCloud login or network. Docs updated:
  `README.md`, `readme-user.md`, `specifications.md` (§6, §8, §9, §12.1,
  §13, §15, §16.2), `structure.md`, `unit-tests.md`, `user-stories.md`
  (US-D1b), `todos.md`, `plan.md`, `ui-sketch/README.md` (§1 note, §8
  parity rows), ADR-0008 addendum and ADR index.
  **Open items (pre-existing at HEAD, not caused by this feature):**
  `ruff format --check` flags `src/iphone_archive/gui/review.py`,
  `src/iphone_archive/gui/shell.py` and `tests/test_importer.py`;
  `mypy --strict` reports 2 errors in `src/iphone_archive/core/exif.py`; the
  two `test_gui_settings.py` failures above.
- 2026-10-11 — **Docs reconciled with commits since 2026-09-16** (`7c7b477`
  through `aa0086b`), checked against the source at HEAD; documentation only,
  no code or tests changed. Updated: root `README.md` (status, post-Phase-2
  features, network note, tech stack), `docs/readme-user.md` (GUI status, map,
  camera details, upgraded previews, album reconciliation section, internet
  FAQ, stale settings/GUI text), `docs/specifications.md` (local-only
  exception, layout/immutability, schema v3-v6, import workflow, §12 album
  reconciliation replacing "never moved or deleted automatically", new §16.4
  trip map, constraints, performance notes), `docs/structure.md` (module map
  incl. `core/exif.py`, `gui/mapview.py`, `gui/webassets/`, `gui/review.py`,
  `service/marks.py`), `docs/development.md` (Qt WebEngine, vendored Leaflet,
  map rules, packaging caveat), `docs/unit-tests.md` (inventory incl.
  `test_core_exif.py`, `test_gui_mapview.py`, `test_gui_settings.py`),
  `docs/todos.md` (delivered items and follow-ups), `docs/plan.md`,
  `docs/user-stories.md` (US-D1, US-F1, new US-G9), `packaging/README.md`
  (webassets `datas`, Qt WebEngine) and a dated note in ADR-0011 (map network
  use and notices; album reconciliation vs ADR-0004/0007) with the ADR index;
  here, the "Album correction" status bullet no longer claims wrong copies
  are never removed.
  Found, not resolved: an unreadable `Photos.sqlite` makes reconciliation move
  album copies of still-present assets into `_Unsorted`; no post-map `.exe`
  rebuild is recorded and the smoke test never opens a map;
  `tests/test_packaging.py` does not check the `webassets` entry; the
  offloaded-preview cache lives under the process working directory; assets
  without EXIF camera data are re-read on every import. The 2026-10-12/13
  entries below postdate their commits (2026-10-10).
- 2026-10-13 — **Fixed: every map reported "no location" — existing assets
  were never backfilled with GPS/camera metadata.** The prior GPS/map and
  EXIF features only wrote `latitude`/`longitude`/camera fields onto
  *newly* archived assets and offloaded-preview upgrades; an asset already
  present in the catalog from before those features existed took the
  "fast-skip" path on every later import (identity already matches, no
  bytes re-transferred) and was never revisited, so its location/camera
  columns stayed permanently `NULL`. Verified directly on the user's real
  6,630-item archive: 0 assets had `latitude`/`camera_model` populated
  despite the phone's `Photos.sqlite` carrying GPS for thousands of them.
  Added `importer_backfill_metadata()`, called from both places an
  already-known asset is recognized during import (the phone-identity
  fast-skip path and the content-hash duplicate path): if `latitude` is
  still `NULL` and the just-enumerated phone item now reports a location,
  it's written in; if `camera_model` is still `NULL`, the asset's already-
  archived file is read locally for EXIF (no phone round trip needed) and
  any camera/lens/ISO/aperture/focal-length/GPS it carries is filled in.
  New `repository_backfill_asset_metadata()` performs the update. Existing
  non-`NULL` values are never overwritten — only genuinely missing fields
  are filled in — so a later import can never clobber data an earlier one
  already found, including from a phone location that may have moved on to
  reporting different (or no) coordinates for that same path. Cost is
  self-amortizing: once an asset's fields are filled, later imports skip it
  immediately (`camera_model`/`latitude` already non-`NULL`), so repeat
  imports of an already-backfilled archive do no extra disk I/O. Verified
  end-to-end against the real archive: re-running `import` lifted assets
  with GPS from 0 to 5,396 and assets with camera metadata from 0 to 1,123
  out of 6,641. Added `test_reimport_backfills_location_and_camera_
  metadata_on_existing_asset` and `test_reimport_never_overwrites_already_
  recorded_metadata` to `test_importer.py`. ruff/mypy clean; full suite
  green aside from the pre-existing Windows flakes.
- 2026-10-13 — **Added EXIF camera metadata extraction (lens, ISO, aperture,
  focal length) and a GPS fallback read from each photo's own EXIF.** User
  asked whether lens/camera/GPS metadata is available on imported photos, is
  importable, and whether it lives in the internal DB or the picture
  metadata; answered that GPS/capture-time are DB-sourced from the phone's
  `Photos.sqlite` (already implemented), but lens/camera/ISO/aperture are not
  captured anywhere, though still physically present in each archived file's
  own EXIF since files are copied byte-for-byte. This adds that capture.
  Schema v6 adds `camera_model`/`lens_model`/`iso`/`aperture`/
  `focal_length_mm` columns to `assets` (migration mirrors the v3–v5
  pattern). New module `core/exif.py` (`ExifMetadata`, `exif_read_metadata`)
  opens the archived file with Pillow/pillow-heif, reads `Make`/`Model`
  (combined without duplicating the brand name), the EXIF sub-IFD for lens
  model/ISO/aperture/focal length, and the GPS IFD as a **fallback only**
  — phone-sourced GPS from `Photos.sqlite` still wins whenever present.
  Reading is maximally defensive (bare `except Exception` degrading to an
  all-`None` result) since metadata is a bonus, never a reason to fail an
  import; this mirrors the existing degrade-gracefully philosophy used for
  Photos.sqlite album/GPS parsing. `Asset` gained the five new optional
  fields; `PhoneItem` is deliberately unchanged, since this data comes from
  the archived file after copy, not from phone-side enumeration.
  `importer.py` calls `exif_read_metadata()` once the file is placed on disk,
  for both newly archived assets and offloaded-preview upgrades, with EXIF
  GPS only used when the phone item had no coordinates. `core/exif.py` does
  not import `browse/thumbnails.py`'s HEIC registration helper to avoid an
  upward dependency from `core` to `browse`; it duplicates the same small
  registration call locally instead. No new GUI service operation was added
  (unlike the GPS/map feature) since this only enriches existing listing
  calls rather than adding a new callable, so no new `gui/parity.py` entries
  were needed; GUI display of the new fields was not added this round and
  remains a possible follow-up. Added `tests/test_core_exif.py` (synthetic
  JPEGs built with Pillow carrying known EXIF, covering camera/lens/ISO/
  aperture/focal-length extraction, GPS sign handling, missing-EXIF and
  corrupt-file degradation, and the Make/Model/one-tuple-numeric quirks),
  plus a v6 migration/round-trip test in `test_catalog.py` and two importer
  integration tests in `test_importer.py` (camera metadata lands on new
  assets; phone GPS beats EXIF GPS when both are present). ruff and mypy
  clean; full suite green aside from the pre-existing Windows flakes
  (`test_gui_settings.py`, an occasional `test_recycle.py` monkeypatched-
  fsync settings-file race, and the occasional `test_cli.py::
  test_marks_remove` file-locking flake).
- 2026-10-12 — **Added GPS/map support: every album and library now has a
  "Map" button showing a trip map of its located photos.** User asked to (1)
  recap every photo action possible from the iPhone vs. the PC app, and (2)
  add a map section to each album/library that places photos at their GPS
  location and shows trip steps from the phone's metadata. Part 1 was
  answered directly. For part 2, confirmed no location/EXIF/GPS handling
  existed anywhere in the codebase, so this is a full-stack addition: schema
  v5 adds `latitude`/`longitude` columns to `assets` (migration mirrors the
  existing v3/v4 pattern); `Asset`/`PhoneItem` carry the new fields;
  `core/albums.py` gained `albums_location_query`/`albums_parse_location_
  data`, which discover `ZLATITUDE`/`ZLONGITUDE` on the phone's `Photos.sqlite`
  asset table the same way album membership is discovered, filtering out both
  NULL and CoreLocation's `(-180, -180)` "no location" sentinel;
  `afc_device_photo_metadata` now returns a third `locations` mapping,
  reusing the Photos.sqlite copy already made for album/capture-time parsing
  (no extra AFC round trip), and `device_enumerate` wires it onto each
  `PhoneItem` with the same legacy-bare-filename fallback already used for
  albums; `importer.py` propagates `latitude`/`longitude` into both newly
  archived assets and offloaded-preview upgrades; `browse/gallery.py` gained
  `gallery_list_located()` (assets with coordinates, ordered oldest-capture-
  first so plotting them in order traces a trip), exposed through the new
  `app_service_list_locations()`. On the GUI side, added `gui/mapview.py`
  with `TripMapCanvas` (custom `QPainter` equirectangular projection fit to
  the points' bounding box, scaled by `cos(mean_latitude)` to avoid
  longitude stretching, with a chronological trip line and distinct
  start/end markers), `TripMapWidget`, and `MapDialog` — deliberately
  offline/custom-painted rather than tile-based, consistent with the app
  never making network calls on the user's behalf. Added a "Map" button to
  `ShellPage`'s header, shown only on gallery-backed views (All photos,
  Unsorted, Recycle bin, each album); `MainWindow.main_window_map_action`
  resolves the view to `album_id`/`only_unsorted`/`include_deleted`
  parameters and opens `MapDialog` with the result. Declared the new
  operation's surface in `gui/parity.py` and gave it a title/summary in
  `gui/operations.py` so `tests/test_gui_parity.py` continues to guarantee
  every service capability is actually reachable from the GUI, not just
  described. Added tests for the location query/parsing (`test_albums.py`),
  device-layer wiring including the bare-filename fallback
  (`test_device.py`), the new gallery listing scoped to album/unsorted/
  recycled (`test_gallery.py`), the service facade (`test_service.py`), the
  schema migration and repository round trip (`test_catalog.py`), and
  importer propagation for new assets and offloaded-preview upgrades
  (`test_importer.py`). Known limitation: the Marked and Deleted-from-phone
  review pages have no map yet (different underlying data model — a list of
  decisions, not a gallery). Known assumption, not yet verified against a
  real device (the user's iPhone 12 was not connected during this session):
  GPS columns are read directly from `ZASSET`/`ZGENERICASSET`, not from any
  `ZADDITIONALASSETATTRIBUTES` join; if a given iOS version stores location
  only there, the feature will silently show "no location data" rather than
  erroring, matching the app's existing degrade-gracefully philosophy for
  unsupported Photos.sqlite schemas. "Trip steps" currently means "located
  photos in that view, plotted in capture-time order," not automatic
  multi-trip segmentation. Full suite green aside from the two known
  pre-existing Windows path-separator flakes in `test_gui_settings.py` and
  the occasional transient `test_cli.py::test_marks_remove` file-locking
  flake.
- 2026-10-11 — **Album placement now reconciles with the phone's current
  membership on every import; moving a photo between albums, or into/out of
  one entirely, no longer leaves a duplicate copy behind.** Follow-up to a
  sequence of user questions about creating an album directly on the phone
  and moving photos into it: investigating "what happens on the next import
  if I move a photo into a different album" surfaced that `importer_sync_
  albums` was deliberately append-only — its own docstring said existing
  copies are "never moved or removed." That was fine for genuine multi-album
  growth (a photo gaining a *second* album while keeping the first) but wrong
  for an actual move: the phone reports the photo in its new album and no
  longer in the old one, yet the importer only ever added, so the stale copy
  (or a stale `_Unsorted` copy, the same gap flagged earlier when discussing
  moving photos out of Unsorted) persisted forever alongside the new one —
  the user explicitly required this not to happen. Rewrote `importer_sync_
  albums` to build the asset's *desired* set of album placements from the
  phone item's current `album_names` (treating "no albums" as a desired
  `_Unsorted` placement), add a copy for any desired placement not yet on
  disk, and then remove any existing `Photos`-location copy whose placement
  is no longer desired — unlinking its file, its `asset_files` row
  (`repository_delete_asset_file`), and its `asset_albums` link via the new
  `repository_unlink_asset_album`. New copies are always created before old
  ones are removed. Recycle-bin copies are filtered out up front and never
  touched. Updated `tests/test_e2e.py::test_album_added_later_is_appended`
  (renamed `test_album_added_later_replaces_unsorted_copy`, since the old
  duplicate-leaving behavior was the bug being fixed) and added
  `test_album_growth_keeps_both_copies`, `test_album_moved_on_phone_is_not_
  duplicated`, `tests/test_importer.py::test_album_move_removes_stale_copy`,
  and `test_album_removed_on_phone_falls_back_to_unsorted`. The
  pre-existing `test_album_growth_is_append_only` (genuine two-album growth)
  needed no change and still passes. Full suite green aside from the two
  known pre-existing Windows path-separator flakes in `test_gui_settings.py`.
- 2026-10-11 — **Offloaded-preview assets now upgrade in place when their real
  original comes back to the phone, instead of being archived as a duplicate.**
  User question after the review-page fix: "is there a way to download
  full-size photos if there's only the thumbnail?" Confirmed there is no
  AFC/USB-level way for this app to force iCloud to push a full-resolution
  original to the phone — that is strictly a Photos-app/iCloud operation (open
  the photo in Photos, or turn off "Optimize iPhone Storage"). But re-reading
  `importer_process_item` surfaced a real gap on the *app's* side of that
  workflow: once the user does get the original back onto the phone and
  reimports, the importer had no way to recognize it as the same photo as the
  low-resolution preview it had already archived — identity matching only
  looked at the exact phone path, and a preview's `phone_path` was its
  thumbnail location under `/PhotoData/Thumbnails/V2`, never the real DCIM
  path. The real file would therefore import as a brand-new, unrelated second
  asset, leaving the stale preview behind. Added `PhoneItem`/`assets`
  (schema v4) `offloaded_original_path`, set by `afc_device_offloaded_preview`
  to the real album-member path it stands in for. On a later import of a
  non-preview item, `repository_find_offloaded_preview_by_original_path`
  checks for a preview recorded against that same path; if found,
  `importer_upgrade_offloaded_preview` deletes the old low-resolution file,
  rewrites the asset's content/phone identity in place (same asset id, so
  existing album links, marks, and sidecars all carry over automatically),
  and places the new full-resolution copy exactly like a fresh import would.
  Added `ImportResult.upgraded_count`, surfaced in both the CLI (`ibackup
  import`) and GUI import-summary text. New regression test
  `test_offloaded_preview_upgraded_in_place_once_original_reappears` drives a
  scripted device through preview-then-original import twice and asserts a
  single catalog row survives with the preview file gone and the real bytes in
  place. Full suite green (same 2 pre-existing Windows `test_gui_settings.py`
  path-separator flakes, and a one-off transient `WinError 5` rename flake in
  `test_cli.py::test_marks_remove` that passed cleanly on its own — both
  previously documented as pre-existing and unrelated); ruff and `mypy
  --strict` clean on all changed source files.
- 2026-10-11 — **Fixed the Marked and Deleted-from-phone pages rendering
  almost blank, then gave them real thumbnails sized and rendered the same
  way as the rest of the app.** User report: both pages showed only the big
  page title and an item-count subtitle, plus a cluster of tiny, unreadable
  pixels in the top-left corner; "All photos" and "Recycle bin" were fine.
  Root cause: `ArchiveShell.__init__` constructed `MarksPage(page)` /
  `DeletedPhonePage(page)`, passing the hosting `ShellPage` as the Qt parent.
  `ShellPage.shell_page_take_body()` only calls `addWidget()` (which supplies
  the stretch factor that lets the body fill the page) when
  `widget.parent() is not self` — but the widget's parent was already `self`
  from construction, so that check was always false and the review widget
  was *never actually inserted into the page's layout*. It stayed a child
  widget floating at Qt's default `100x30` geometry, while the layout handed
  all the page's remaining space to the title/subtitle labels instead (which
  is exactly what rendered as the oversized title/subtitle and the tiny
  corner smudge). A second, compounding issue: when a review list is empty
  (e.g. no marks yet), `ReviewList` shows only its `empty_label`, a plain
  `QLabel` without an expanding size policy (unlike `AssetGallery`'s
  equivalent `message_label`, which explicitly sets
  `Expanding`/`Expanding`) — so even once properly laid out, an *empty*
  review page would still collapse. Fixed both: `review.py` now gives
  `ReviewPage`, `ReviewList` and `empty_label` explicit
  `Expanding`/`Expanding` size policies, and `shell.py` constructs the review
  pages with no parent (letting `shell_page_take_body` parent and add them)
  and hardens that method to check actual layout membership
  (`body_layout.indexOf(widget)`) rather than Qt parentage, so a
  pre-parented widget can no longer silently skip being added to the layout.
  Verified by reproducing the exact broken geometry through a real
  `ArchiveShell` instance (not just an isolated `ReviewPage`, which had
  masked the bug).

  Once visible, the user noted the rows showed a checkbox, name, size and
  date but no image — `ReviewList` never had a `PreviewLoader` or any
  per-row hash/path to request a thumbnail with, so every row was always
  text-only. Gave `ReviewRow` optional `sha256`/`relative_path` fields;
  `review_phone_rows` fills them from `DeletedFromPhoneItem` (already
  asset-scoped), and a new `marks_preview_source()` in `service/marks.py`
  resolves a mark's target to one representative stored copy - the asset
  itself for an asset mark, the owning asset for a file mark, and one photo
  in the album for an album mark. Two follow-up reports then refined the
  rendering itself: first that the thumbnails were "very small" at a
  conservative 48px; then, after enlarging them, that the photos "don't fit
  the grey box" and that the checkbox sat oddly beside a tiny icon instead of
  under a photo. Both came from the review pages having grown a second,
  parallel tile implementation (a hand-rolled `QListWidget` delegate) instead
  of reusing the gallery's own. `ReviewList` is now a `QListView` in icon mode
  over a plain `QStandardItemModel`, painted by `gallery.TileDelegate` itself
  through the same `AssetRole.SHA256`/`PATHS`/`ORIGINAL_NAME` data roles the
  photo grid uses - so a thumbnail here has the exact same crop, rounding and
  size as everywhere else, because it is the same code drawing it. "Checked"
  is now the view's own multi-selection (click, ctrl/shift-click to extend)
  rather than a separate checkbox, matching how the gallery marks a tile
  selected with its accent check-circle; `review_checked_ids()`/
  `review_set_all()` keep their old signatures so `ReviewPage`, `MarksPage`,
  `DeletedPhonePage` and `ReclaimDialog` needed no further changes beyond one
  latent bug the constructor-signature change surfaced: `reclaim.py`'s
  `ReclaimDialog` was calling `ReviewList(text, self)` positionally, so
  `self` (the dialog) landed in the new `previews` slot and crashed on
  `previews.preview_ready.connect()` - fixed by passing `parent=self` as a
  keyword there. Added `test_marks_preview_source_is_none_for_an_empty_album`,
  `test_pending_marks_carry_a_thumbnail_source` and
  `test_review_rows_pick_up_a_thumbnail_once_it_settles` (the last against a
  real `PreviewLoader`, asserting through the delegate's own `tile_entry()`
  lookup, reusing `test_gui_previews.py`'s existing archive/loader fixtures
  rather than building a fresh `QThreadPool` per test, which proved to crash
  the interpreter when run alongside other `MainWindow`-heavy tests in the
  same session). Full suite green throughout (same pre-existing,
  order-dependent Windows path-separator/permission flakes as before, each
  confirmed to pass in isolation and unrelated to this work), ruff and
  `mypy --strict` clean.
- 2026-10-10 — **Increased gallery/control sizing; cached offloaded-preview
  lookups to fix repeat-import slowness.** User feedback after the first real
  run: (1) grid thumbnails and buttons were too small to see comfortably, and
  (2) a second import took a long time and the user wasn't sure how to get
  only new photos quickly. For (1), bumped `gallery.py`'s `TILE_IMAGE` 120→160
  (with `CHECK_RADIUS`/`BADGE_HEIGHT` scaled to match) and `theme.py`'s
  `CONTROL_HEIGHT` 32→36; `CONTROL_HEIGHT` is shared by every button in the
  app (selection bar, Marked page, dialogs, settings), so the fix is global
  and consistent rather than page-specific. A follow-up clarified the small
  icon was specifically the navigation pane's line-art glyph shown next to
  "Marked" (and every other nav row): `icons.py`'s `ICON_SIZE` grew 16→20 and
  `navigation.py`'s per-row `icon_rect` was resized and recentred to match.
  For (2), confirmed the previous
  session's offloaded-preview feature was an unintentional performance
  regression: `afc_device_offloaded_preview` ran an AFC `listdir` + `stat` for
  *every* unavailable album path on *every* `device_enumerate()` call — up to
  ~10,500 extra round-trips per import on a device with ~5,263 offloaded
  paths, even though import itself already skips re-copying bytes for assets
  already in the catalog. Added a small on-disk cache
  (`.ibackup-device-cache/offloaded-preview-cache.json`, keyed by device UDID
  then phone path) so a resolved thumbnail path is remembered and reused
  without any further AFC calls; a path only needs re-resolving if it was
  never resolved before. No cache invalidation is needed: once a real
  original becomes available on the phone again, its path simply leaves the
  "unavailable" set upstream and the cached preview is never looked up again.
  Added `test_offloaded_preview_lookup_reuses_cache_without_repeating_afc_calls`,
  asserting a second lookup makes zero AFC calls, and updated the existing
  offloaded-preview regression test's assertions for the new persistent cache
  file. Full suite green (same 2 pre-existing Windows path-separator failures
  as before), ruff and `mypy --strict` clean.
- 2026-10-09 — **Added offloaded-photo low-resolution preview fallback; real
  iPhone 12 validation.** Root-caused the `device-info` warning "5263 album
  media paths across 67 albums are not in the USB media inventory": those
  originals are offloaded by "Optimize iPhone Storage", so AFC's `/DCIM` walk
  cannot see them even though Photos.sqlite still lists their album
  membership. Confirmed by direct AFC inspection that iOS keeps a cached JPEG
  thumbnail for every asset (including offloaded ones) under
  `/PhotoData/Thumbnails/V2`, mirroring the DCIM tree path-for-path — the same
  degraded preview iOS itself shows in Photos. `AfcDevice.device_enumerate`
  now looks up that mirrored thumbnail for every album path missing from the
  USB inventory and, when found, synthesizes a `PhoneItem` reading the cached
  JPEG, named with an `" (offloaded preview)"` suffix so it is never mistaken
  for the real original; any lookup failure is swallowed and that path is left
  genuinely missing, exactly as before. Added `assets.is_offloaded_preview`
  (schema v3, forward-only migration, idempotent against a column that may
  already exist) and threaded the flag through `PhoneItem` → importer → `Asset`
  so archives can distinguish previews from full-resolution copies. Updated
  the enumeration warning to report how many missing paths were recovered as
  previews versus truly unavailable. New regression coverage: a real
  SQLite-parsed offloaded album member recovered as a preview and correctly
  placed/verified through `AppService`, and a lookup-failure path proven never
  to raise. Full targeted suite plus the whole repo suite passed (only the two
  pre-existing Windows GUI settings path-separator failures remain, unrelated
  to this change); Ruff lint/format and strict core/catalog/device mypy
  passed.
  **Real iPhone 12 validation (iOS 26.4, same device as the Sept 16 entries):**
  enumeration found 1360 real USB items and all 5263 previously-missing album
  paths resolved to a cached thumbnail (0 fully unrecoverable). A scoped
  import of 12 items (6 real DCIM photos across 3 albums plus 2 unsorted, and
  6 offloaded previews from the `EyeEm` album) into an isolated temporary
  archive added all 12 with zero errors, and archive verification passed. The
  catalog correctly recorded 6 real assets and 6 preview assets with distinct
  `is_offloaded_preview` flags and the `" (offloaded preview)"` filename
  marker. The temporary archive and validation script were deleted afterward;
  no existing archive, settings, or phone content were touched. This does not
  qualify a full-library import, Live Photo pairing, non-JPEG/video keyframe
  cache formats, or GUI display of the preview flag (not yet surfaced in the
  GUI beyond the existing filename/log visibility).

- 2026-09-16 — **Corrected real-phone album misassignment; supersedes the earlier
  metadata confidence claims below.** The filename fallback was unsafe even
  when unique among album members: another, unassigned asset elsewhere in
  Photos could have the same filename. On this phone it falsely assigned
  albums to 635 local files. The merge-time test expecting a cross-directory
  match encoded that bug; it now expects no membership. Modern album and
  capture-date lookup use only exact directory/filename keys. Legacy filename
  lookup rejects ambiguity across *all* database assets, not just album
  members, as well as across the USB inventory. Missing album media paths
  produce a warning rather than filename substitutions.
  Independent SQL against the live iOS 26.4 database matched all 1,318
  enumerated items' memberships and capture dates with zero mismatches;
  119 items had actual exact-path album membership. A fresh, isolated
  three-file import (1,164,739 bytes) covered two correctly assigned photos
  and a formerly misassigned photo now stored under `_Unsorted`. All three
  copies' folder/catalog membership matched independent SQL, their hashes
  matched fresh USB reads, verification passed, and reimport skipped all three.
  Temporary media and database snapshots were removed; the phone and existing
  archives/preferences were untouched.
  The reported missing albums **do exist** in Photos, but none of their
  recorded originals was in the DCIM inventory:
  `Sardegna - 2021` (251 members), `Lago di Fiastra - Lame rosse - Tempio del
  Valadier` (62), and the three `Folgarida 2021` albums (85, 44 and 53).
  Direct stat of a member from each returned AFC file-not-found. This is
  consistent with offloaded originals; the iCloud setting itself was not
  inspected, and USB does not automatically download missing originals.
  Regression coverage now exercises real SQLite parsing through the AFC
  adapter and importer, not merely `FakeDevice` album maps. Targeted suite:
  98 passed; full suite before the final additional legacy-date case:
  732 passed, 8 skipped, the same two pre-existing Windows GUI-settings
  path-separator failures. Ruff lint/format and strict core/catalog mypy passed.
  The Windows executable was rebuilt with this correction and passed the
  artifact startup smoke test; an already-running GUI must be restarted.

- 2026-09-16 — **Real-phone read/import validation of `7c7b477` passed.**
  Windows build 26200, NTFS; iPhone 12 (`iPhone13,2`), iOS 26.4 (`23E246`);
  Python 3.11.9, pymobiledevice3 11.10.4, PySide6 6.11.2, Pillow 12.3.0,
  PyAV 18.1.0. Apple driver version was not established by the driver query.
  USB enumeration returned 1,320 media files (5,580,684,594 bytes), including
  753 files with memberships across 15 albums. A bounded sample of eight real
  files (HEIC, JPG, PNG, MOV and MP4; 240,836,651 bytes total, largest video
  236,902,297 bytes) was imported through `AppService` into an isolated
  temporary archive using copy mode. One sampled item had multiple albums;
  four had no album assignment.
  All eight catalog hashes and all nine stored copies matched independent,
  fresh phone reads in both SHA-256 and byte count. Archive verification
  checked nine copies with zero mismatches/missing files. A second import
  skipped all eight items with zero media reads and verification still passed.
  Re-enumeration matched the initial paths, sizes, modification times and album
  memberships. All streams/sessions closed, and a new USB session reconnected
  to the same device. Temporary media, catalog and isolated preferences were
  removed after the successful 152-second run; no existing archive/preferences
  were changed and no phone mutation was attempted.
  This does **not** qualify multi-GB streaming/peak memory, Live Photo pairing,
  manual album correctness, physical cable interruption, locked/untrusted
  states, exFAT/hardlinks, the frozen GUI, or any destructive operation.

- 2026-09-16 — **Integrated `gcor/nugfix` into `main`.** Album membership now
  uses `ZDIRECTORY` paths where available. Integration regressions cover the
  real AFC enumeration method: exact paths win, filename fallback requires
  uniqueness in both the membership map and device inventory, and repeated
  filenames do not inherit ambiguous capture times. Settings retain unique
  staging files but propagate failed publication rather than pretending an
  existing file contains the requested preferences.
  Read-only USB validation found 1,317 media items, 753 with memberships across
  15 albums and no repeated filenames; the device was closed without import or
  deletion. This checks metadata availability, not manual album correctness.
  The affected suite passed (99 tests); full Windows validation: 724 passed,
  8 skipped, 2 previously recorded GUI-settings path-separator assertion
  failures, 89.98% coverage. Ruff lint/format and strict core/catalog mypy passed.

- 2026-09-16 — **Step 12 `gui-packaging` implemented, built and smoke-tested on
  Windows 11** (Python 3.11, PyInstaller 6.22). `packaging/` holds the spec,
  the entry-point shim, the icon generator and its committed `icon.ico`, the
  Windows version resource, the artifact smoke test and a README; a `package`
  CI job repeats the build and the smoke test on `windows-latest`. Decisions
  worth remembering:
  - **One directory, not one file.** Qt ships as separate DLLs next to the
    executable so a user can replace them, which is what keeps the LGPL
    relink right real (ADR-0011 item 3). `--onefile` would be a licensing
    decision, not a build-flag preference.
  - **A build that "succeeded" proves nothing.** PyInstaller happily produces
    executables that die on the first missing DLL or hidden import, so
    `packaging/smoke_test.py` launches the real artifact offscreen, requires it
    to survive a grace period and fails on a traceback in stderr. That is the
    step's actual acceptance check, and it was run here, not just written.
  - **`pymobiledevice3` is a hidden import.** It is reached indirectly through
    `iphone_archive.device`, which static analysis misses.
  - **The icon is drawn by the app itself.** `make_icon.py` renders the GUI's
    own "photos" glyph into a multi-resolution `.ico`, so packaging adds no
    third-party asset or its redistribution terms (ADR-0011 item 4).
  - **The frozen build is not a second implementation.** `run_gui.py` only
    calls the same `application_main()` the installed `ibackup-gui` entry point
    uses, and a test asserts it stays that thin.
  - **The version resource has no automatic sync**, so `tests/test_packaging.py`
    fails when it drifts from `project.version`; the same test executes the spec
    with stubbed builders, so a renamed entry point or a silent switch to a
    console/onefile build breaks in seconds rather than in a release.

- 2026-09-17 — **Step 11 `gui-parity-tests` implemented offline.** New
  `gui/parity.py` declares the GUI surface behind every service operation, and
  `tests/test_gui_parity.py` enforces it against the real Typer app, the real
  `AppService` and the real GUI source, alongside end-to-end offscreen journeys.
  Decisions worth remembering:
  - **A parity map that nobody checks is a comment.** The test does not only ask
    whether an operation is listed; it reads the GUI source and fails when a
    declared surface never submits the operation it claims, and when the GUI
    submits an operation the map never mentions. Membership in a refresh list or
    a title table deliberately does not count as a surface.
  - **The test found a gap, which is the point.** `marks add --album` and
    `--file` had no GUI equivalent, so an album can now be marked from its
    right-click menu, and marking a single copy inside an album asks whether the
    copy or the whole asset is meant. The narrower scope is the default button.
  - **Two capabilities are covered indirectly, and both say why.** Bulk
    preference saving writes every edited field in one `app_service_update_settings`
    call rather than one round trip per field, and previews are rendered by the
    GUI's own pool so scrolling never queues behind an archive operation. An
    unexplained entry in that table is exactly the gap this test exists to
    catch, so each one carries its reason next to it.
  - **The journeys assert against the disk.** The end-to-end flows check the
    archive's files after import, commit and restore rather than the widgets,
    because a GUI that looks right while writing nothing is the failure mode
    that matters here.

- 2026-09-16 — **Step 10 `gui-settings` implemented offline, closing
  `settings-store`.** New `gui/settings_dialog.py` is the sketch's §7b editor;
  `service/app_service.py` gained `ARCHIVE_FREE_OPERATIONS` and
  `app_service_preferences()`, and `gui/worker.py` routes the settings
  operations to that preferences-only service. Decisions worth remembering:
  - **Preferences need no archive, but the service must not invent one.** The
    preferences-only service is bound to the sentinel root
    `<preferences-only>`, which cannot be an archive, so an operation added to
    `ARCHIVE_FREE_OPERATIONS` by mistake raises `ArchiveNotFoundError` instead
    of quietly operating on the working directory. A test asserts exactly that,
    and that the working directory stays empty afterwards.
  - **A settings panel may add friction, never remove it.** The typed-word rule
    and the dry-run-first rule are shown ticked and disabled, and
    `confirm_word_required` is written as `True` rather than read back from its
    widget, so forcing the widget cannot weaken a confirmation.
  - **The dialog is opened by the reply, not by the press.** It therefore always
    shows what is really stored; a reset or a forget re-reads from the service
    instead of patching the widgets.
  - **Saving applies immediately.** Preview size, theme, log level and the
    deleted-on-phone default take effect in the running window; a preference
    that only reached the file would leave the window disagreeing with its own
    settings dialog until the next launch.
  - **`reopen_last_archive` reopens only a folder that is still an archive**,
    after the window is on screen, with a normal status line. A removed drive
    must not turn startup into an error, and nothing is ever created.
  - **`default_deleted_action` only suggests.** It sets which button the §3
    review offers as its default; it never presses it, and a permanent choice
    still requires the typed word.

- 2026-09-15 — **Step 9 `gui-ops-destructive` implemented offline.** The GUI
  can now delete things, which makes this the step where the archive's core
  promise had to be enforced in code rather than by refusing the verb. New
  `gui/confirm.py` (the sketch's §5 dialog), `gui/review.py` (§3 deleted-on-phone
  review and §6 marks queue) and `gui/reclaim.py` (§4, opened only by a dry run).
  Decisions worth remembering:
  - **Two strengths of confirmation.** Permanent verbs - purge, permanent mark
    commit, phone reclamation - require the typed word `DELETE`, because the CLI
    requires `--confirm` on exactly those and the GUI must not be the weaker
    frontend. Reversible verbs - moving to `Deleted/` - ask explicitly but do
    not demand the word: asking for it everywhere would teach the user to type
    it without reading, which costs more safety than it buys.
  - **The typed word is re-checked when the button is pressed**, not only when
    it enables the button. The enabled state is a hint; a programmatic click or
    a future change to the enabling rule must not be able to bypass the gate.
  - **Reclaim is always a dry run first.** "Free up space" runs
    `app_service_reclaim` with `confirmed` absent; only that report can open the
    dialog that leads to a real deletion, and the service re-verifies the
    candidates again at execution because a preview is not an authorization.
  - **A recycle-bin purge passes `recycled_only=True`**, so purging what you can
    see in the bin cannot reach an asset's still-active copies.
  - **Marking is whole-asset and says so.** There is no bulk copy-scoped mark
    API, so marking from an album view states plainly that it covers the copies
    in other albums rather than implying album scope.
  - **Unmark is bounded.** There is no bulk unmark call and the worker queue
    holds 32, so a selection over 16 is refused with the one-request
    alternative instead of being turned into a flood.
  - A refreshed review list **drops its ticks**; silently re-checking a replaced
    row would aim a deletion at something the user never chose.
  Two Qt lifetime bugs of the same class were found and fixed: a slot that
  enables a footer button was connected before the footer existed, so filling
  the list raised inside Qt's event loop (`ReclaimDialog`, `ReviewPage`, and
  pre-emptively `ConfirmDialog`). `mypy` caught a third defect: `ReclaimDialog`
  stored its preview as `self.result`, shadowing `QDialog.result()` and breaking
  every caller asking whether the user had confirmed. Three earlier placeholder
  tests asserting the old "step 9" refusals were updated to assert the new
  behaviour.
- 2026-09-15 — **Step 8 `gui-ops-safe` implemented offline.** The command bar
  stopped being decorative: opening and creating archives, importing, verifying,
  scanning the phone, checking the phone, the duplicate report, refreshing
  counts, clearing the preview cache and moving a selection into an album all
  run for real, on the worker thread, through the existing bounded request
  boundary. Long work gets the sketch's §2 progress dialog; short reads report
  one status line, because a modal dialog for a counter refresh flashes open and
  shut without telling the user anything. Two honesty rules shaped the dialog.
  First, **cancellation is only offered where it exists**: only a service method
  that accepts a `ProgressHandle` ever observes the cancel event, so the
  cancellable set is *derived from the real signatures* rather than hand-listed,
  and operations that cannot be interrupted say so instead of showing a button
  that quietly does nothing. The first version of that set was hand-written and
  the test caught it immediately - it had missed `app_service_reclaim` - which
  is precisely why it is now computed. Second, **hiding is not finishing**: Hide
  leaves the work running, and a run that ends with errors re-opens the dialog,
  because a list of failures must not be reduced to one status line. Building it
  surfaced two more bugs of a kind this project keeps meeting. A `WA_DeleteOnClose`
  dialog does **not** emit `finished` on every destruction path, so the window
  held a pointer to a dead dialog and aborted on the next window close; owners
  now clear their reference on `destroyed`. And a *hidden* import's summary was
  being erased milliseconds later by the counter refresh the import itself
  triggered - the third time a routine read has overwritten something the user
  needed - so a hidden run's summary is now held like an error. Review then
  found two further defects: because a finished dialog is destroyed one
  event-loop turn *after* it closes, a dying dialog could clear the window's
  reference to the live dialog that had already replaced it, leaving a running
  operation with nothing watching it and a modal dialog that survived window
  shutdown; the viewer had the same hole, where the stale handler also cancelled
  the renders of the viewer the user was looking at. Both now bind the identity
  at connect time. Review also caught that "Clear previews" was the first caller
  to unlink cache files while the preview pools - which deliberately bypass the
  worker - were reading and writing them; on Windows that fails with a sharing
  violation, so the pools are quiesced first and the sweep now tolerates a
  locked file rather than aborting. Destructive verbs remain refused and name
  step 9; nothing in this step deletes anything.
- 2026-09-15 — **Step 7 `gui-gallery` implemented offline.** The window finally
  shows photographs. `gui/gallery.py` binds an icon-mode grid **directly to the
  shared paged asset model** and paints tiles with a `QStyledItemDelegate`, so a
  200 000-asset archive costs only the tiles on screen and painting never reads
  the disk - it answers from the preview cache or schedules a background render.
  There is one model and therefore one gallery, re-hosted by whichever page is
  shown. Selection verbs are gated by scope, so the recycle bin offers
  restore/purge while ordinary views offer move/mark/delete, and the selection
  bar and context menu are generated from one table so they cannot drift apart.
  Every verb captures the selection **immediately, on the GUI thread**, as exact
  asset and file IDs bound to the model generation, so later steps act on the
  copies the user actually saw. `gui/viewer.py` adds a full-size viewer with its
  own second preview loader at 1024 px and a tiny cache, because sharing the
  grid's loader would evict every tile on each open; it navigates with the arrow
  keys, pages the model when it runs off the end, and closes itself on a model
  reset because "row 12" then means a different asset. Two bugs were found while
  building: a bare `QTimer.singleShot` fired a deferred method into an already
  destroyed grid, model and worker, and the gallery's automatic page reads were
  erasing the user's error message - the rule is now "ignore any automatic read",
  backed by bounded request histories so correctness never depends on Qt
  signal-connection order. Review then found five more defects a green suite had
  missed: a viewport scan that visited every loaded row (37.6 ms per scan at
  20 000 rows, twice per scroll, defeating the paged model), closed viewers that
  were never destroyed and kept a multi-megabyte pixmap plus live model and
  loader connections, and three tests that could not fail for the reasons they
  named. The scan is now an `indexAt` probe plus an outward walk that stops at
  the first tile past the viewport, and scrolling no longer cancels renders when
  no tile can be located, so a momentarily unlaid-out viewport cannot discard
  images about to be painted. The lesson recorded from this round is that a
  *cost* fix needs a *cost* assertion: the regression counts how many rows the
  scan touches, because the returned rows are identical either way. Also learned
  offscreen: `QMenu.exec` hangs a headless suite in a modal loop, so menu
  construction is separated from showing it. Commands and selection verbs still
  only acknowledge themselves; the dialogs are step 8.
- 2026-09-15 — **Step 6 `gui-shell` implemented offline.** The window now shows
  the sketch's frame: navigation pane with live counts, page stack, the command
  bar that replaces a menu bar, and a status line. The shell holds no archive
  data; counters and album rows are read through the service worker and re-read
  once the models' mutation barriers clear, so an import cannot leave stale
  numbers on screen. Every command names a real service operation and a test
  fails if it does not, which is the first half of the CLI/GUI parity proof.
  Commands needing an archive or a phone are disabled with an explanatory
  tooltip; since there is no cheap AFC presence probe, the phone state stays
  unknown - and those commands stay available - until a device operation
  succeeds or fails. Icons are drawn with QPainter rather than bundled, so they
  follow light, dark and high-contrast themes with no extra assets. A regression
  found while wiring the shell: routine status refreshes overwrote worker error
  messages, so errors are now held until the next success or command. Review
  then found four more defects a green suite had missed - cancelled mutations
  never reaching the shell even though a cancelled import has already committed
  what it copied, the page stack drifting out of step with the navigation pane,
  "disconnected" being an unrecoverable dead end because the phone probe itself
  was gated on the phone, and a failed mutation erasing its own error. The last
  fix first depended on Qt signal-connection order and was replaced by a bounded
  housekeeping history; the lesson is that status correctness must never depend
  on connection order. Each regression test was checked by reverting its fix.
  Pages are still placeholders; the grid is step 7.
- 2026-09-14 — **Step 5 `gui-thumbnail-loader` implemented offline.** Previews
  render on a dedicated bounded thread pool rather than the archive worker, so
  a running import cannot blank the grid and fast scrolling cannot flood the
  worker's request queue. Pool threads receive only the archive root, a hash and
  a relative path. Added a bounded LRU pixmap cache, per-key coalescing,
  cancel-on-scroll with an outstanding-render bound, remembered failures with
  explicit retry and a bounded shutdown that never forces threads. Review caught
  a cancelled render's reply being applied to the re-request that replaced it,
  which could fail a valid tile permanently; replies now carry a per-render
  token. An invalid persisted `thumbnail_size` no longer stops the window
  opening. Thumbnail staging files are now uniquely named, because
  concurrent GUI renders and a concurrently running CLI previously shared one
  `.part` path. No gallery is visible yet; the grid arrives in step 7.
- 2026-09-14 — **Recovered and completed step 4 `gui-models`.** Steps 2 and 3
  were already committed (`0928835`, `8e8cf24`); the worktree held unfinished
  step-4 source/tests without matching progress documentation. Completed
  `gui/models.py`, window ownership and optional backend album/unsorted/recycled
  pagination. Selection snapshots retain exact copy IDs and reject changed
  scopes, archives and generations. Review exposed reentrant Qt insertion/reset
  callbacks that could repeat offsets or relabel active copies as recycled, and
  stale ordinary proxy indexes that could crash native Qt mapping. Added
  transaction guards, deferred scope resets, a persistent-proxy-index contract
  and regressions. Invalid close requests no longer lose the controller's
  archive identity. No thumbnail loader, visible gallery or operation controls
  were added; step 5 is next.
- 2026-09-14 — **Reconciled CI scope and living docs.** Repository-wide Ruff
  commands included throwaway mockups despite the documented exclusion.
  Added the explicit mock directory exclusion, leaving application/tests
  covered, and ran the repository checkpoint above. Updated README, plan,
  checklist, architecture, development/testing guide and session task states.

- 2026-09-11 — **Step 3 `gui-worker` implemented offline.** Added `gui/worker.py`:
  worker-owned service and per-request device contexts, explicit archive
  create/open/close, FIFO request IDs, detached parameters/results, text-only
  error DTOs and explicitly queued Qt delivery. A full queue rejects new work
  without dropping accepted requests; shutdown always has a reserved queue slot.
  Progress retains the existing last-256 history and at most one outstanding
  notification per request. Cancellation reaches active work directly through
  its Event; queued cancelled requests never execute, and late cancellation does
  not relabel completed operations. Expected errors leave the session usable;
  unexpected failures close it, fail queued work without replay and allow a fresh
  session on the next request after `stopped`. The window defers close until the
  worker joins, and the application also joins on programmatic exit. Offline
  tests exercise real fake-device import/verify, thread ownership, archive-lock
  release, queue saturation, error cleanup, progress coalescing and cancellation.
  Uncancellable I/O still has to return before shutdown can complete; the worker
  is never forcibly terminated. No GUI operations or hardware qualification are
  implied by this foundation.
  Targeted GUI/Win32/service/progress/settings run: 165 passed. Ruff and
  host/Windows-targeted mypy passed for the GUI modules.
- 2026-09-11 — **Step 2 `gui-theme` implemented offline.** Added exact WinUI
  light/dark color tokens, logical-pixel type ramp, metrics and scoped QSS over
  native controls. Persisted `theme=system|light|dark` works through the existing
  settings/CLI/service APIs and is applied at GUI startup. The controller follows
  system theme/accent changes, releases explicit overrides for high contrast,
  and restores native colors/fonts. Windows style selection now logs
  `windows11` -> `windowsvista` -> Fusion fallbacks. Native DWM requests use
  pointer-sized handles, 32-bit arguments/HRESULTs and per-attribute build guards;
  unsupported/failed effects log a solid fallback. The Mica probe is opt-in;
  normal client painting stays opaque until real Windows validation. Offscreen
  regression coverage includes settings, live theme changes, contrast/accent,
  rendered fallback opacity and mocked native calls; no live Mica/chrome result
  or Windows release qualification is claimed.
  Targeted GUI/settings/service/CLI regression run: 171 passed, 94% GUI coverage
  with branches measured; ruff and host/Windows-targeted mypy passed for the
  changed modules.
- 2026-09-11 — **UI-sketch gate passed; Phase 2 started.** The user approved
  both `gui-theme` and `gui-frontend` and asked for the GUI work to be broken
  into smaller steps. `gui-frontend` is now twelve ordered steps (`plan.md` §2b)
  with dependencies recorded in the todo DB, so no step starts before the layer
  beneath it is proven.
- 2026-09-11 — **Step 1 `gui-scaffold` complete.** Added
  `src/iphone_archive/gui/` with `application.py` (QApplication bootstrap, style
  selection, `--help` without Qt, readable message on a broken PySide6 install)
  and `main_window.py` (window shell, page stack, status bar). Restored the
  `ibackup-gui` entry point, now backed by real code. `tests/test_gui.py` runs
  headless under `QT_QPA_PLATFORM=offscreen`; one test asserts that importing
  `iphone_archive.gui` does **not** import Qt, so a broken Qt install can never
  take the CLI down with it. 377 passed, 1 skipped; ruff and mypy clean.

- 2026-09-10 — **Video thumbnails implemented** (`future-video-thumbnails`,
  one of the two gaps raised at the UI-mock review). `thumbnails` now extracts a
  poster frame with PyAV, whose wheels bundle FFmpeg so Windows needs no system
  install. Two correctness points were settled against the ffmpeg CLI rather
  than by assumption: the display-matrix rotation is applied so portrait iPhone
  clips are not sideways (verified pixel-identical to ffmpeg's autorotate for
  0/90/180/270), and the decoder walks forward from the seek keyframe to the
  target instead of returning the keyframe itself, which was silently producing
  black frames. A nearly-black poster frame also triggers a bounded scan for a
  brighter one. `av>=12` is now a declared dependency and is imported lazily, so
  a missing install degrades videos to a placeholder without affecting image
  thumbnails. The UI mock was updated to match: video tiles carry a duration
  badge instead of the word "video".

- 2026-09-10 — **Built a clickable UI mock** in `docs/ui-sketch/mockup/` using
  the selected framework (PySide6), covering every screen in the sketch and
  navigable between them: navigation pane with counts and selection pill,
  thumbnail grid with multi-select, import/verify progress, deleted-on-phone
  review, reclaim, typed-DELETE confirmation, viewer, marks queue and the
  six-panel settings dialog. Rendered 20 reference screenshots (light + dark)
  via `capture_screens.py`. The mock is a **review artifact only** — fake data,
  no imports from `iphone_archive`, excluded from lint/type/test — so the
  UI-sketch approval gate remains closed and no application GUI code exists.

- 2026-09-10 — **First run against a real iPhone** (iPhone 12, iOS 26.4, 1297
  items, 5.55 GB). Import, dedup, incremental fast-skip, verification, HEIC
  thumbnails and the archive layout all behaved correctly on real data.
  **Fixed a real defect**: album membership was completely broken on device
  because the Photos.sqlite album/asset join table ordinal (`Z_28ASSETS`) is
  version-specific and is `Z_33ASSETS` on iOS 26; it is now discovered at
  runtime and filtered to user albums (`ZKIND = 2`). Album coverage went from
  0 to 750 items across 67 albums. Measured ~34 MB/s transfer and a fixed ~36 s
  enumeration cost caused by copying the 1 GB Photos.sqlite on every run.
  Confirmed `reclaim` still cannot delete from the phone (by design) and left
  the device untouched. See ADR-0008.

- 2026-09-09 — Completed offline hardening and final quality gates above.
  Imports and edits now establish durable private staging before creating media,
  persist bounded ownership records before no-clobber publication, and recover
  normal creation/claim-write failures without blocking archive reopen.
  Journal metadata writes scale linearly with batch size. Repair copies retain
  album scope; missing catalogued files restored by import are not discarded
  as duplicates. Added indexes for per-asset files, album/location queries and
  per-asset source presence. Real AFC deletion is hard-disabled and the inspected
  adapter dependency is pinned to `pymobiledevice3==11.10.4`. No GUI approval,
  live-device qualification or packaged release is implied.
- 2026-09-09 — Corrected implementation versus requirements throughout docs;
  added core-hardening, hardware and scheduled release gates. Current commands,
  test/module inventories and GUI parity contract reconciled. Accepted ADR
  bodies preserved; ADR-0011 corrects licensing/interop rationale and requires
  observable DWM fallback. No GUI approval, hardware pass or release claimed.
- 2026-09-09 — Implementation pass confirms typed `DELETE`, selected reclaim
  (`--asset`), source-album moves (`--from-album`), cache/marks clear, complete
  settings APIs, OS-exclusive single-session locks with thread ownership,
  Event cancellation/last-256 progress snapshots, service-applied import/
  thumbnail settings and configured rotating CLI command start/completion/error
  logs with handler cleanup. Browse queries handle partial recycling and
  active/deleted paths/counts. CI explicitly uses `.venv` and `mypy --strict`;
  this configuration is not evidence of a passed Windows run. Final execution
  evidence remains to be recorded above; hardware and GUI gates remain closed.

- 2026-09-07 — **UI direction set: modern Windows 11 Fluent, not stock Qt.**
  Researched and recorded **ADR-0010**. Key findings: Qt **6.7** ships a native
  `windows11` QStyle (and defaults to it on Win11), so the dependency floor was
  raised from PySide6 6.6 to **6.7**; **qfluentwidgets is GPLv3**, so it is
  originally described as license-incompatible (corrected by ADR-0011: MIT is
  GPL-compatible, but this distribution does not adopt GPL obligations);
  **Segoe Fluent Icons may
  not be redistributed**, so MIT `fluentui-system-icons` is used instead.
  Sketch §0 now specifies the Mica/rounded-corner/dark-caption DWM calls, the
  WinUI type ramp, 4/8px radii and exact light/dark color tokens, and the
  layout idiom (**menu bar removed**, NavigationView + command bar). Added a
  `gui-theme` todo that must land before `gui-frontend`, starting with a Mica
  probe. Still holding at the UI-sketch approval gate.

- 2026-09-07 — Closed the configuration gap: added **`settings.py`** (persisted
  preferences in `%APPDATA%\ibackup\settings.json`, outside the archive),
  `app_service_get_settings` / `app_service_update_settings`, and the
  **`ibackup config get|set|list|reset|path|forget`** command. The first archive
  created becomes the default, so `--archive` can be omitted. Validation refuses
  any value that would weaken safety (`confirm_word_required` cannot be turned
  off). An autouse fixture isolates tests from the real user profile.
  **205 tests green at that checkpoint.** Later review identified runtime
  settings/log/confirmation wiring gaps; current hardening status is above.

- 2026-09-07 — Wrote the **UI sketch** (`docs/ui-sketch/README.md`): main window,
  import progress, deleted-on-phone review, reclaim, destructive confirmation,
  marks queue, single-photo viewer, plus a full **CLI-to-GUI parity map**.
  **Holding at the UI-sketch approval gate.**

- 2026-09-07 — **Phase 1 delivered.** Implemented, in dependency order and each
  with its own tests + commit: project scaffold, name-safety, hashing, catalog
  (schema/repository/sidecars), config + logging, archive layout, device layer
  (AFC + fake), importer (two-pass with fast-skip), verifier, dedup, phone-diff,
  recycle bin, reclaim, albums, gallery, thumbnails, the `AppService` facade
  with marks + multi-select, and the Typer CLI. Added the golden end-to-end and
  crash-resume suite. **179 tests, 91% coverage, ruff + mypy clean.**
  `IBACKUP_FAKE_DEVICE` / `IBACKUP_ARCHIVE` allow the whole CLI to be exercised
  without an iPhone.

- 2026-09-07 — Adopted **architect top-5 workflow additions**: Windows CI
  (ruff + `mypy --strict` + pytest + **coverage gate**), **pre-commit** hooks,
  **ADR folder** (`docs/adr/`, migrated 8 existing decisions), **`hypothesis`**
  property tests for name-safety + hashing, and a **golden E2E + crash-resume**
  test (`tests/test_e2e.py`). Remaining recommendations saved as `future-*`
  backlog todos (schema migrations, audit log, catalog repair, release
  checklist, dependency hygiene, destructive-op guardrails).
- 2026-09-07 — Initialized **git version control**; committed docs in logical,
  story-telling steps (gitignore → README/development → progress → workflow
  rules). Adopted **incremental-commit / no-push** rule. Stray `report.*.json`
  tool dumps are git-ignored.
- 2026-09-07 — Target set to **Windows-only**; stack fixed to **Python +
  PySide6**; added deleted-from-phone review + `Deleted/` recycle bin; added
  performance/scalability analysis and import fast-skip; added dev-docs
  (development.md, README.md) and this progress log; adopted **venv** and
  **run-tests-after-coding** and **keep-docs-updated** rules.
- 2026-09-07 — Phase 0 documentation drafted and consolidated into `docs/`.

## Notes / open items

- Project license: MIT. Bundled dependencies retain separate obligations;
  Qt/icon release notices and compliance review remain required (ADR-0011).
- Confirm `pymobiledevice3` AFC behavior on target iOS versions for
  `Photos.sqlite` album extraction (best-effort fallback to `_Unsorted`).
