# Build Checklist — iPhone Archive (`ibackup`)

Tracked todos with dependencies. Legend: [x] done · [~] in progress ·
[!] blocked/gate · [ ] pending. "Depends on" must complete first.

> **Workflow rules (apply throughout):**
> - Use a **Python virtual environment** (`.venv/`) — never the global interpreter.
> - Run `pytest` **after writing code for every module/todo**; a todo is not done
>   until its targeted tests pass (full suite before completing a phase).
> - **Keep docs up to date while coding:** `development.md`, `readme-user.md`,
>   `structure.md`, `unit-tests.md`, root `README.md`, and any other affected doc.
> - **Docs before commit (mandatory):** never commit a code change without the
>   docs it affects in the same commit. Before committing, check which docs are
>   stale (`git log -1 --format=%ad -- <doc>` vs. the code commits since) and
>   update them; see the checklist in the root `AGENTS.md`.
> - **Update `progress.md`** whenever a todo changes state (resume point).
> - **Commit incrementally** with clear messages so the project story is
>   readable in git history — one logical commit per step, not one dump at the
>   end. Keep the repo updated as you go, but **do not push**.

## Phase 0 — Documentation (done)

- [x] **doc-specifications** — `docs/specifications.md`.
- [x] **doc-readme-user** — `docs/readme-user.md`.
- [x] **doc-user-stories** — `docs/user-stories.md`.
- [x] **doc-structure** — `docs/structure.md`.
- [x] **doc-unit-tests** — `docs/unit-tests.md`.
- [x] **doc-development** — `docs/development.md` (venv, libraries, tests).
- [x] **doc-readme-root** — root `README.md` (overview + docs index).
- [x] **doc-progress** — `docs/progress.md` (resumable progress log).
- [x] **docs-approval-gate** — docs approved by the user; Phase 1 unblocked. _Depends on: all doc-* above._

## Phase 1 — Core + CLI baseline (implemented offline, not hardware-qualified)

The checked items below record initial implementation, not completion of the
hardening and Windows validation gates that follow.

- [x] **project-scaffold** — create `.venv`, pyproject.toml (runtime + dev
  extras incl. ruff, mypy, hypothesis, pre-commit, pytest-cov),
  `src/iphone_archive/` layout, root README, `.gitignore`,
  `.pre-commit-config.yaml` (ruff + mypy + hygiene), and
  `.github/workflows/ci.yml` (windows-latest: ruff, `mypy --strict` on
  core/catalog, pytest headless + coverage gate ~85%).
  _Depends on: docs-approval-gate._
- [x] **config-logging** — `config.py`, `logging_setup.py`.
  _Depends on: project-scaffold._
- [x] **name-safety** — Windows-safe album/file names, collisions, no symlinks.
  _Depends on: project-scaffold._
- [x] **device-access** — `pymobiledevice3` AFC wrapper, device detection,
  media enumeration (DCIM + PhotoData). _Depends on: project-scaffold._
- [x] **catalog-schema** — SQLite schema (assets, asset_files, albums,
  asset_albums, import_sessions, deletion_marks), models, repository.
  _Depends on: project-scaffold._
- [x] **hashing-layout** — streaming SHA-256 + album-folder layout, atomic
  copy/hardlink placement. _Depends on: name-safety, project-scaffold._
- [x] **sidecar** — per-asset JSON sidecar read/write. _Depends on:
  catalog-schema._
- [x] **importer** — incremental import (copy→verify→place→sidecar→commit),
  append-only album growth (superseded 2026-10-10 by **album-reconcile**
  below). _Depends on: catalog-schema, device-access,
  hashing-layout, sidecar._
- [x] **dedup** — duplicate detection + report. _Depends on: catalog-schema,
  hashing-layout._
- [x] **verifier** — re-hash all on-disk copies vs catalog. _Depends on:
  catalog-schema, hashing-layout._
- [x] **albums** — parse `Photos.sqlite`, map to album folders; `_Unsorted`
  fallback. _Depends on: catalog-schema, device-access, name-safety._
- [x] **phone-diff** — detect archived assets no longer on the phone
  (read-only). _Depends on: catalog-schema, device-access, importer._
- [x] **reclaim** — verify-before-delete phone space reclamation
  (dry-run/confirm). _Depends on: device-access, importer, verifier._
- [x] **recycle-bin** — `Deleted/` folder: move/restore/purge; keep catalog in
  sync. _Depends on: catalog-schema, hashing-layout._
- [x] **browse-gallery** — album listing/counts (no HTML generator).
  _Depends on: catalog-schema._
- [x] **thumbnails** — generate + cache thumbnails under `.ibackup/thumbnails/`
  (HEIC via `pillow-heif`), reuse cache, never modify originals. _Depends on:
  hashing-layout._
- [x] **service-layer** — headless facade (`app_service.py`) + progress/cancel
  + result DTOs, exposing all operations. _Depends on: albums, browse-gallery,
  dedup, importer, phone-diff, reclaim, recycle-bin, thumbnails, verifier._
- [x] **archive-edit** — multi-select move/delete + mark-for-delete primitives.
  _Depends on: catalog-schema, hashing-layout, recycle-bin._
- [x] **cli-wiring** — wire all subcommands to the service layer. _Depends on:
  albums, archive-edit, browse-gallery, dedup, importer, reclaim,
  service-layer, verifier._

## Core-hardening checkpoint (complete offline)

- [x] **device-identity-safety** — device-scoped multiple identities, transactional
  schema migrations and legacy rescan behavior; complete-scan-only absence;
  bounded AFC streaming and cleanup; fail-closed real AFC reclaim.
  _Depends on: importer, phone-diff, reclaim, catalog-schema._
- [x] **archive-recovery-safety** — path confinement, multi-copy/sidecar/catalog
  failure handling, recycle/restore/purge recovery and album-copy semantics.
  _Depends on: archive-edit, recycle-bin._
- [x] **service-safety-parity** — process/session lock, worker-owned SQLite,
  Event cancellation, typed DELETE for permanent operations, selected reclaim,
  cache clear, marks clear, operation logs/log level.
  _Depends on: service-layer, cli-wiring._
- [x] **settings-store** — store/CLI and service consumers implemented; closed
  by `gui-settings`, which added the GUI editor and gave `reopen_last_archive`
  and `default_deleted_action` real consumers. _Depends on: service-layer._
- [x] **core-validation** — final targeted/full configured quality gates and
  report in `progress.md`, without duplicating brittle counts across docs.
  _Depends on: device-identity-safety, archive-recovery-safety, service-safety-parity._
- [!] **windows-iphone-validation** — Windows/iPhone read, album and large-video
  matrix, then separately controlled destructive/recovery checks. Keep real AFC
  deletion gated until approved evidence exists. _Depends on: core-validation._

## UI sketch gate (before any GUI code, including Mica probe)

- [x] **ui-sketch** — written at `docs/ui-sketch/README.md`; produce UI sketch/wireframe (main window, album nav,
  picture grid + multi-select, deleted-on-phone review, reclaim, progress) under
  `docs/ui-sketch/`. _Depends on: service-layer._
- [x] **ui-sketch-approval-gate** — **passed 2026-09-11.** The sketch and its
  clickable mock were reviewed and explicitly approved, unblocking `gui-theme`
  and `gui-frontend`.

## Phase 2 — GUI (approved 2026-09-11, in progress)

`gui-frontend` was too large to track as one item, so it is split into the
ordered steps below. Each is one commit, built bottom-up with tests; a step
never starts before the layer beneath it is proven. Descriptions live in
`plan.md` §2b.

- [x] **gui-scaffold** — `src/iphone_archive/gui/` package, `application.py`
  bootstrap, `main_window.py` shell, restored `ibackup-gui` entry point and
  headless `tests/test_gui.py`. A test asserts importing the gui package does
  not import Qt, so a broken PySide6 install cannot take the CLI down with it.
  _Depends on: ui-sketch-approval-gate._
- [x] **gui-theme** — implemented offline: WinUI tokens/type ramp/metrics,
  scoped QSS, persisted `theme=system|light|dark`, live native theme/accent
  updates and high-contrast preservation. Native Windows style fallbacks and
  DWM attributes are build-guarded with logged failures. Normal launches keep
  solid client painting; `ibackup-gui --mica-probe` is an opt-in rendering
  experiment, not validated Mica support. Live Windows 11 22H2+ probe/chrome
  qualification remains pending before transparent painting can be the default.
  _Depends on: gui-scaffold, core-validation._
- [x] **gui-worker** — implemented offline in `gui/worker.py`: lazy dedicated
  thread owning `AppService` and its archive lock, bounded FIFO requests,
  detached DTOs, coalesced queued progress/result/error delivery, direct Event
  cancellation and same-thread resource cleanup. The window defers close until
  the worker joins; application exit also joins. Real fake-device import/verify
  and lifecycle/error/cancellation regressions cover the foundation; operation
  views remain later steps. _Depends on: gui-scaffold, service-layer._
- [x] **gui-models** — implemented offline in `gui/models.py`: paged asset and
  album models owned by the window, cached roles, shared selection and
  exact-copy parameters for all/album/unsorted/recycled scopes. Default pages
  contain 128 rows plus one lookahead; queries run only on the service worker.
  Tested with 1 297 assets, stale replies/indexes, mutation barriers, Qt
  notification reentrancy and album-copy recycle/restore isolation.
  _Depends on: gui-worker, browse-gallery._
- [x] **gui-thumbnail-loader** — implemented offline in `gui/previews.py`:
  `PreviewLoader` renders previews on its own bounded thread pool instead of the
  archive worker, coalesces requests per hash/size key, cancels scrolled-past
  work, bounds decoded pixmaps with an LRU cache and remembers failures so a
  broken file is not retried on every repaint. Shutdown waits for a safe
  boundary without forcing threads. Thumbnail staging files are now uniquely
  named so parallel and cross-process writers cannot corrupt a cache entry.
  _Depends on: gui-models, thumbnails._
- [x] **gui-shell** — implemented offline in `gui/shell.py`, `gui/navigation.py`,
  `gui/commands.py` and `gui/icons.py`: navigation pane with live counts and
  album rows pumped from the paged album model, page stack bound to the asset
  model's scope, command bar replacing the menu bar with every verb mapped to a
  service operation, and a status line covering phone and archive state. Counts
  refresh after mutations rather than going stale, and worker errors are no
  longer overwritten by the next routine status update.
  _Depends on: gui-theme, gui-models._
- [x] **gui-gallery** — icon-mode grid, rubber-band and Ctrl/Shift selection,
  selection bar, viewer dialog, context menu. The grid binds to the shared paged
  model and paints tiles with a delegate, so only visible tiles cost anything and
  painting never reads the disk. Selections are captured as exact asset+file IDs
  on the GUI thread, and the viewer owns a second large-preview loader.
  _Depends on: gui-shell, gui-thumbnail-loader._
- [x] **gui-ops-safe** — import, verify, scan-phone, dedup report, stats and
  move-to-album behind a progress dialog that can be cancelled or hidden.
  Cancellation is offered only where the service method actually takes a
  progress handle, and that set is derived from the real signatures. Hiding
  keeps the operation running; a hidden run's summary is held in the status bar
  and an erroring one re-opens the dialog. Destructive verbs are still refused
  and name the step that will gate them. _Depends on: gui-gallery._
- [x] **gui-ops-destructive** — typed-DELETE confirmation, deleted-on-phone
  keep/move/purge, recycle-bin restore/purge, marks commit and reclaim, always
  dry-run first. Nothing destructive is submitted by a button press: the press
  builds a spec describing exactly what would happen, and only the confirmation
  dialog's approval reaches the worker. Permanent verbs demand the typed word
  and re-check it when the button is pressed; reversible ones ask without it, so
  the word keeps its meaning. A recycle-bin purge sets `recycled_only=True`, and
  a refreshed report drops its ticks. _Depends on: gui-ops-safe, recycle-bin,
  phone-diff, marks._
- [x] **gui-settings** — the six settings panels bound to the service; also
  closes the aggregate `settings-store` item. The dialog never touches the
  settings file: it edits a detached copy and hands it back to the window, which
  is the only object that talks to the worker. Settings operations run with no
  archive open, against a preferences-only service bound to a sentinel root that
  cannot be an archive, so an operation added to that set by mistake fails
  closed. Safety options may only add friction: the typed word and the
  dry-run-first rule are shown ticked and disabled, and the saved value is
  forced on regardless of widget state. `reopen_last_archive` and
  `default_deleted_action` finally have consumers - startup reopens the last
  archive only when it is still an archive, and the §3 review only *suggests*
  the preferred button. _Depends on: gui-shell, service-layer._
- [x] **gui-parity-tests** — a test that fails if any CLI command or service
  method has no GUI surface, plus end-to-end `pytest-qt` flows run offscreen.
  `gui/parity.py` declares the surface behind every operation and
  `tests/test_gui_parity.py` checks it against the real Typer app, the real
  `AppService` and the real GUI source: an operation with no surface, a surface
  naming an operation that no longer exists, a declared surface that never
  submits its operation and an undeclared submission all fail. Only two
  capabilities are covered indirectly and each records why. Writing the test
  closed the last gap it found - album-scoped and copy-scoped marks now exist in
  the GUI, with the narrower scope as the default. _Depends on:
  gui-ops-destructive, gui-settings._
- [x] **gui-packaging** — PyInstaller executable, icon, version resource and a
  smoke test of the built artifact. `packaging/ibackup.spec` freezes the
  `ibackup-gui` entry point (via a one-line `run_gui.py` shim, so the frozen
  app is not a second implementation) into a **one-directory** Windows app -
  Qt ships as replaceable DLLs, keeping the LGPL relink right intact
  (ADR-0011). The icon is rendered from the GUI's own drawn glyph by
  `make_icon.py`, so no third-party icon set is bundled, and
  `version_info.txt` carries the Windows version resource.
  `packaging/smoke_test.py` launches the built `.exe` offscreen and fails on an
  early exit or a traceback; `tests/test_packaging.py` checks the build inputs
  against the real project metadata and exercises the smoke test against real
  child processes. Built and smoke-tested on Windows 11 with PyInstaller 6.22;
  a `package` CI job repeats both. Signing, an installer and a clean-machine
  install test remain release work. _Depends on: gui-parity-tests._

- [~] **gui-frontend** — PySide6 `gui/` (main_window, navigation_pane,
  command_bar, picture_grid_view w/ multi-select, thumbnail_loader,
  operations_controller, reclaim_view, deleted_on_phone_view, marks_view,
  settings_dialog, Qt models); `ibackup-gui` entry point; progress/cancel via
  QThread with worker-owned SQLite, queued UI signals and Event cancellation;
  serialized mutations and bounded thumbnail queues.
  **No menu bar** — NavigationView + command bar per the sketch.
  Aggregate tracked by the `gui-*` step list above; all twelve steps are
  complete offline (step 12 additionally built and smoke-tested on Windows).
  It is not a separate implementation task.
  _Depends on: archive-edit, browse-gallery, gui-theme, phone-diff,
  recycle-bin, service-layer, ui-sketch-approval-gate._

## Verification

- [~] **tests** — pytest suite (unit + mocked device + pytest-qt GUI +
  `hypothesis` property tests + golden E2E/crash-resume `test_e2e.py`), **run
  after each module during development** and as a final full-suite gate.
  _Depends on: archive-edit, dedup, gui-frontend, hashing-layout, importer,
  name-safety, phone-diff, recycle-bin, service-layer, thumbnails, verifier._
  Status: offline core/CLI and recovery regressions pass; see `progress.md`.
  GUI tests (including parity) exist and run offscreen; Windows/hardware
  qualification remains a separate future gate.

## Scheduled release milestone

- [ ] **windows-cli-release** — the GUI now has a PyInstaller recipe
  (`packaging/ibackup.spec`), but the CLI does not: create a CLI-only recipe,
  then build it on
  Windows, smoke-test on a clean machine without Python, validate licenses/
  notices and versioned artifacts. A recipe alone is not a release.
  _Depends on: core-validation, windows-iphone-validation._
- [ ] **windows-gui-release** — package the approved, tested GUI and Qt/icon
  notices/replacement obligations; installer/signing strategy and release docs.
  _Depends on: windows-cli-release, gui-frontend, tests._

## UI mock (2026-09-10)

- [x] **ui-mock** — clickable PySide6 mock of every sketch screen under
  `docs/ui-sketch/mockup/`, with light/dark reference screenshots. Review
  artifact only; does not open the approval gate.

## Found by real-device testing (2026-09-10)

- [ ] **device-delete-validation** — `reclaim` lists candidates then fails on
  every item: `AfcDevice.device_delete` refuses unconditionally because a raw
  AFC unlink under `/DCIM` would not update the Photos library. **Space
  reclamation therefore frees nothing on a real phone today.** Find a supported
  deletion path and validate it on Windows before enabling.
- [ ] **future-photosdb-cache** — every run pays a fixed ~36 s cost dominated by
  copying the phone's 1 GB `Photos.sqlite`, even when nothing is imported.
  Cache it on size+mtime, or skip it when album data is not needed.
- [x] **future-video-thumbnails** — **done.** `thumbnail` now extracts a poster
  frame from videos with PyAV (bundled FFmpeg, no system install). The frame is
  rotated into display orientation using the container's display matrix — pinned
  against the ffmpeg CLI's own autorotate output for all four orientations, since
  iPhone clips record landscape and would otherwise show sideways — and a
  nearly-black poster frame triggers a short scan for a brighter one so clips that
  open on a fade-in do not become black tiles.

## Delivered after Phase 2 (2026-09-16 – 2026-10-10)

Recorded in `progress.md`; docs reconciled 2026-10-11.

- [x] **album-exact-paths** (`7c7b477`, `c0f2f91`) — album membership and
  capture dates keyed by `ZDIRECTORY` + filename; legacy bare filenames only
  when unique across the whole database and USB inventory. Settings saves use
  unique staging files and propagate publication failures.
- [x] **offloaded-previews** (`22fa9ae`, `66420ac`) — import the phone's cached
  `/PhotoData/Thumbnails/V2` JPEG for offloaded album members (schema v3
  `is_offloaded_preview`); resolved lookups cached per device in
  `.ibackup-device-cache/offloaded-preview-cache.json`.
- [x] **offloaded-preview-upgrade** (`30db3e2`) — upgrade a preview in place
  when its original returns (schema v4 `offloaded_original_path`,
  `ImportResult.upgraded_count`).
- [x] **album-reconcile** (`d7eea11`) — import makes `Photos/` copies match the
  phone's current album membership, removing stale album/`_Unsorted` copies.
- [x] **gps-map** (`2237104`, `26b3d7c`, `aa0086b`) — schema v5 GPS,
  `app_service_list_locations`, per-view **Map** button; now a Leaflet/
  OpenStreetMap map via Qt WebEngine (the app's only network use).
- [x] **map-trip-details** (2026-10-12) — Start/End pins, per-segment
  direction arrows (Web Mercator angle, ≥ 40 px segments only, refreshed on
  zoom) and a photo popup per point (picture rendered from the archived copy
  as a `data:` URI off the GUI thread, file name, capture time, "n of N",
  preview/video note); `MapDialog` 900×640, delete-on-close.
- [x] **map-travel-modes** (2026-10-12) — click a trip leg to tag it Car /
  Plane / On foot / Bike / Tuk-tuk / Bus / Taxi / Boat (or clear it); styled
  per mode, stored per view in `trip_segments` (schema v7, cascade on asset
  delete) and reconciled on every map open (`core/trip.py`); service
  `app_service_trip_modes` / `app_service_set_trip_mode`; GUI-only.- [x] **exif-camera-metadata** (`549556c`, `77ec30a`) — schema v6 camera/lens/
  ISO/aperture/focal length from EXIF; backfill onto existing assets.
- [x] **gui-sizing-review-pages** (`66420ac`, `9cc2bb1`, `3827515`) — larger
  tiles/buttons/icons; Marked and Deleted-from-phone pages laid out correctly
  with real thumbnails.
- [x] **shared-albums** (`0cf5b4f`, fixed 2026-10-11) — iCloud Shared Albums
  imported into `Photos/_Shared Albums/<name>/` (`albums.kind = shared`, no
  schema change); separate GUI "Shared albums" section,
  `ibackup albums --shared`, `(shared)` tag; excluded from reclaim;
  `tests/test_shared_albums.py`. The first version (`ZKIND = 1505` only) found
  nothing on a real iOS 26.4 phone; iOS 26 stores them in `ZSHARE`, linked by
  `ZASSET.ZCOLLECTIONSHARE`, now read first (`ZKIND = 1505` kept as a fallback).
- [x] **shared-album-preview-fallback** (2026-10-11) — uncached shared-album
  members are imported as thumbnail-cache previews and upgraded in place when
  the original is downloaded; a WARNING summary reports the split.

Follow-ups found while reconciling (not scheduled):

- [ ] **reconcile-guard** — skip album reconciliation when `Photos.sqlite`
  could not be read; today an unreadable database moves album copies of
  still-present assets into `_Unsorted` until the next good import.
- [ ] **map-packaging-check** — rebuild the `.exe` with Qt WebEngine and the
  web assets, open a map in it, and assert the `webassets` `datas` entry in
  `tests/test_packaging.py`.
- [ ] **map-notices** — ship Leaflet's licence, Qt WebEngine/Chromium notices
  and OSM attribution in the release notice set (ADR-0011 note); revisit the
  tile provider before a public release.
- [ ] **metadata-display** — camera/lens/ISO fields are stored but not shown
  in the GUI or written to sidecars.
- [ ] **review-page-map** — the Marked and Deleted-from-phone pages have no
  map.
- [ ] **preview-cache-location** — the offloaded-preview cache and the
  temporary `Photos.sqlite` copy live under the process working directory,
  not a per-user or per-archive location.
- [~] **shared-albums-hardware** — partially done 2026-10-11 on an iPhone 12
  (iOS 26.4): schema (`ZSHARE`), `PhotoCloudSharingData/<personId>/<GUID>/
  100CLOUD` layout and AFC reads validated (18 albums, 6,150 items). Still to
  check: a full end-to-end import run, and that shared copies differ in bytes
  from the owner's DCIM originals (identical bytes would merge them into one
  asset whose album copies the two phone items keep reconciling). The
  `ZKIND = 1505` fallback for older iOS remains unvalidated.
- [ ] **shared-album-owner** — record the shared album's owner/subscriber
  status (not captured today). `ZSHARE` showed no owner-name column; possibly
  available via `ZSHAREPARTICIPANT` (unverified).
- [ ] **shared-album-absence** — shared-album items with neither an original
  nor a thumbnail, or in albums the user left, count as "not seen" and can
  appear in the deleted-from-phone review; decide whether that is wanted. Also
  check what happens when a cached original is later evicted: the phone then
  reports only a preview at a different (thumbnail) path, which is not
  matched to the existing full-resolution asset.
- [ ] **pre-existing-lint-type** — `ruff format --check` still flags
  `tests/test_importer.py` (`gui/review.py` and `gui/shell.py` were
  reformatted 2026-10-12, no behaviour change), and `mypy --strict` reports 2
  errors in `core/exif.py`; two `tests/test_gui_settings.py` path-separator
  tests fail on Windows.
- [ ] **flaky-recycle-restart** — `tests/test_recycle.py::
  test_restart_finalizes_catalog_committed_before_cleanup[restore]` failed
  once in a full run on 2026-10-12, then passed on 3 reruns and at HEAD;
  investigate (likely order/timing dependent on Windows).
- [ ] **flaky-worker-archive-switch** — `tests/test_gui_worker.py::
  test_close_then_open_serializes_archive_switches` failed once (2026-10-12)
  with a Windows "Access is denied" renaming the `settings.json` staging file,
  then passed on 3 reruns; likely another process/thread holding the target.
- [ ] **travel-modes-cli-export** — travel modes are GUI-only and catalog-only:
  no CLI command, no export (e.g. GPX/GeoJSON) and not in sidecars, so a
  catalog rebuild from sidecars would lose them.
- [ ] **travel-mode-pair-check** — `trip_set_mode` accepts any two existing
  assets, not only a currently consecutive pair; the GUI only sends
  consecutive pairs, and reconciliation drops stray rows on the next open.
- [ ] **phone-asset-uuid** — capture `Photos.sqlite` `ZASSET.ZUUID` into
  `assets.phone_asset_id` so a photo keeps one identity across byte-changing
  edits and preview/original swaps at different paths (and travel modes
  follow it). Caution: `repository_find_by_phone_identity` matches
  `phone_asset_id IS ?`, so filling it would make every existing source miss
  the fast-skip once and re-read the whole phone (hash dedup still prevents
  duplicates); needs a migration that backfills it first.
- [ ] **map-popup-timezone** — popup capture times are the stored
  `captured_at` truncated to minutes, with no local time-zone conversion.

## Future backlog (agreed, not scheduled)

Architect recommendations captured for later — not part of the current build:

- [ ] **future-audit-log** — structured logging + append-only operation audit log
  in `.ibackup/logs/` (distinct from implemented diagnostic operation logging).
- [ ] **future-catalog-repair** — rebuild/repair `catalog.sqlite` from sidecars.
- [ ] **future-dep-hygiene** — pinned lockfile + `pip-audit` / Dependabot.
- [ ] **future-html-gallery** — US-D4 static browser gallery, explicitly
  deferred; read models do not implement HTML generation.
- [ ] **future-expanded-previews** — additional optional dry-run previews for
  reversible edits; basic permanent-deletion guardrails are mandatory now.
