# Build Checklist — iPhone Archive (`ibackup`)

Tracked todos with dependencies. Legend: [x] done · [~] in progress ·
[!] blocked/gate · [ ] pending. "Depends on" must complete first.

> **Workflow rules (apply throughout):**
> - Use a **Python virtual environment** (`.venv/`) — never the global interpreter.
> - Run `pytest` **after writing code for every module/todo**; a todo is not done
>   until its targeted tests pass (full suite before completing a phase).
> - **Keep docs up to date while coding:** `development.md`, `readme-user.md`,
>   `structure.md`, `unit-tests.md`, root `README.md`, and any other affected doc.
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
  append-only album growth. _Depends on: catalog-schema, device-access,
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
- [x] **settings-store** — store/CLI and current service consumers implemented.
  `reopen_last_archive` and `default_deleted_action` are future GUI preferences,
  not active CLI behavior. _Depends on: service-layer._
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
- [ ] **gui-worker** — worker thread owning `AppService`, which is
  single-thread affine and holds an exclusive archive lock: request marshalling,
  queued progress/result/error signals, cancellation, clean shutdown. The risk
  concentration of Phase 2. _Depends on: gui-scaffold, service-layer._
- [ ] **gui-models** — lazy-paging Qt model over `gallery.AssetView` (the test
  phone holds 1 297 items, so eager loading would stall the window), album
  model, and the selection mapping that preserves album-copy scope instead of
  silently promoting a selection to every copy of an asset.
  _Depends on: gui-worker, browse-gallery._
- [ ] **gui-thumbnail-loader** — background preview pipeline: bounded LRU cache,
  request coalescing, cancel-on-scroll, pending/failed placeholders.
  _Depends on: gui-worker, browse-thumbnails._
- [ ] **gui-shell** — navigation pane with live counts, page stack, command bar,
  status bar, phone connected/disconnected state.
  _Depends on: gui-theme, gui-models._
- [ ] **gui-gallery** — icon-mode grid, rubber-band and Ctrl/Shift selection,
  selection bar, viewer dialog, context menu.
  _Depends on: gui-shell, gui-thumbnail-loader._
- [ ] **gui-ops-safe** — import, verify, scan-phone, dedup report, stats and
  move-to-album behind a progress dialog that can be cancelled or hidden.
  _Depends on: gui-gallery._
- [ ] **gui-ops-destructive** — typed-DELETE confirmation, deleted-on-phone
  keep/move/purge, recycle-bin restore/purge, marks commit and reclaim, always
  dry-run first. _Depends on: gui-ops-safe, recycle-bin, phone-diff, marks._
- [ ] **gui-settings** — the six settings panels bound to the service; also
  closes `settings-store`. _Depends on: gui-shell, settings-store._
- [ ] **gui-parity-tests** — a test that fails if any CLI command or service
  method has no GUI surface, plus end-to-end `pytest-qt` flows run offscreen.
  _Depends on: gui-ops-destructive, gui-settings._
- [ ] **gui-packaging** — PyInstaller executable, icon, version resource and a
  smoke test of the built artifact. _Depends on: gui-parity-tests._

- [ ] **gui-theme** — Windows 11 Fluent look (ADR-0010): a throwaway **Mica
  probe** on Win11 22H2 first, then `gui/theme.py` (WinUI design tokens: type
  ramp, 4/8px radii, light+dark color tokens, system accent, scoped QSS over
  Qt's native `windows11` style) and `gui/win32_effects.py` (DWM Mica, rounded
  corners, dark caption, each build-guarded). Requires PySide6>=6.7.
  Log DWM failure and fall back to solid color; probe is unperformed and needs
  a Windows 11 machine, which is not available on the Linux development host.
  _Depends on: gui-scaffold, core-validation._
- [ ] **gui-frontend** — PySide6 `gui/` (main_window, navigation_pane,
  command_bar, picture_grid_view w/ multi-select, thumbnail_loader,
  operations_controller, reclaim_view, deleted_on_phone_view, marks_view,
  settings_dialog, Qt models); `ibackup-gui` entry point; progress/cancel via
  QThread with worker-owned SQLite, queued UI signals and Event cancellation;
  serialized mutations and bounded thumbnail queues.
  **No menu bar** — NavigationView + command bar per the sketch.
  Now tracked as the `gui-*` step list above rather than as one item.
  _Depends on: archive-edit, browse-gallery, gui-theme, phone-diff,
  recycle-bin, service-layer, ui-sketch-approval-gate._

## Verification

- [~] **tests** — pytest suite (unit + mocked device + pytest-qt GUI +
  `hypothesis` property tests + golden E2E/crash-resume `test_e2e.py`), **run
  after each module during development** and as a final full-suite gate.
  _Depends on: archive-edit, dedup, gui-frontend, hashing-layout, importer,
  name-safety, phone-diff, recycle-bin, service-layer, thumbnails, verifier._
  Status: offline core/CLI and recovery regressions pass; see `progress.md`.
  GUI tests and Windows/hardware qualification remain separate future gates.

## Scheduled release milestone

- [ ] **windows-cli-release** — first create a CLI-only PyInstaller recipe
  (none is included in this remediation), then build it on
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
