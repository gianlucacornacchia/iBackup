# Build Checklist — iPhone Archive (`ibackup`)

Tracked todos with dependencies. Legend: [x] done · [~] in progress ·
[!] blocked/gate · [ ] pending. "Depends on" must complete first.

> **Workflow rule:** run `pytest` **after writing code for every module/todo**.
> A todo is not done until its targeted tests pass; run the full suite before
> completing a phase.

## Phase 0 — Documentation (done)

- [x] **doc-specifications** — `docs/specifications.md`.
- [x] **doc-readme-user** — `docs/readme-user.md`.
- [x] **doc-user-stories** — `docs/user-stories.md`.
- [x] **doc-structure** — `docs/structure.md`.
- [x] **doc-unit-tests** — `docs/unit-tests.md`.
- [!] **docs-approval-gate** — STOP: await explicit user approval of the docs
  before any code. _Depends on: all doc-* above._

## Phase 1 — Core + CLI (after docs approval)

- [ ] **project-scaffold** — pyproject.toml, `src/iphone_archive/` layout,
  README, lint/test tooling. _Depends on: docs-approval-gate._
- [ ] **config-logging** — `config.py`, `logging_setup.py`.
  _Depends on: project-scaffold._
- [ ] **name-safety** — Windows-safe album/file names, collisions, no symlinks.
  _Depends on: project-scaffold._
- [ ] **device-access** — `pymobiledevice3` AFC wrapper, device detection,
  media enumeration (DCIM + PhotoData). _Depends on: project-scaffold._
- [ ] **catalog-schema** — SQLite schema (assets, asset_files, albums,
  asset_albums, import_sessions, deletion_marks), models, repository.
  _Depends on: project-scaffold._
- [ ] **hashing-layout** — streaming SHA-256 + album-folder layout, atomic
  copy/hardlink placement. _Depends on: name-safety, project-scaffold._
- [ ] **sidecar** — per-asset JSON sidecar read/write. _Depends on:
  catalog-schema._
- [ ] **importer** — incremental import (copy→verify→place→sidecar→commit),
  append-only album growth. _Depends on: catalog-schema, device-access,
  hashing-layout, sidecar._
- [ ] **dedup** — duplicate detection + report. _Depends on: catalog-schema,
  hashing-layout._
- [ ] **verifier** — re-hash all on-disk copies vs catalog. _Depends on:
  catalog-schema, hashing-layout._
- [ ] **albums** — parse `Photos.sqlite`, map to album folders; `_Unsorted`
  fallback. _Depends on: catalog-schema, device-access, name-safety._
- [ ] **phone-diff** — detect archived assets no longer on the phone
  (read-only). _Depends on: catalog-schema, device-access, importer._
- [ ] **reclaim** — verify-before-delete phone space reclamation
  (dry-run/confirm). _Depends on: device-access, importer, verifier._
- [ ] **recycle-bin** — `Deleted/` folder: move/restore/purge; keep catalog in
  sync. _Depends on: archive-edit, catalog-schema, hashing-layout._
- [ ] **browse-gallery** — album listing/counts + optional HTML gallery.
  _Depends on: catalog-schema._
- [ ] **thumbnails** — generate + cache thumbnails under `.ibackup/thumbnails/`
  (HEIC via `pillow-heif`), reuse cache, never modify originals. _Depends on:
  hashing-layout._
- [ ] **service-layer** — headless facade (`app_service.py`) + progress/cancel
  + result DTOs, exposing all operations. _Depends on: albums, browse-gallery,
  dedup, importer, phone-diff, reclaim, recycle-bin, thumbnails, verifier._
- [ ] **archive-edit** — multi-select move/delete + mark-for-delete queue.
  _Depends on: catalog-schema, hashing-layout, service-layer._
- [ ] **cli-wiring** — wire all subcommands to the service layer. _Depends on:
  albums, archive-edit, browse-gallery, dedup, importer, reclaim,
  service-layer, verifier._

## UI sketch gate (before any GUI code)

- [ ] **ui-sketch** — produce UI sketch/wireframe (main window, album nav,
  picture grid + multi-select, deleted-on-phone review, reclaim, progress) under
  `docs/ui-sketch/`. _Depends on: service-layer._
- [!] **ui-sketch-approval-gate** — STOP: await explicit user approval of the
  sketch before implementing the GUI. _Depends on: ui-sketch._

## Phase 2 — GUI (after sketch approval)

- [ ] **gui-frontend** — PySide6 `gui/` (main_window, album_list_view,
  picture_grid_view w/ multi-select, thumbnail_loader, operations_controller,
  reclaim_view, deleted_on_phone_view, Qt models); `ibackup-gui` entry point;
  progress/cancel via QThread. _Depends on: archive-edit, browse-gallery,
  phone-diff, recycle-bin, service-layer, ui-sketch-approval-gate._

## Verification

- [ ] **tests** — pytest suite (unit + mocked device + pytest-qt GUI), **run
  after each module during development** and as a final full-suite gate.
  _Depends on: archive-edit, dedup, gui-frontend, hashing-layout, importer,
  name-safety, phone-diff, recycle-bin, service-layer, thumbnails, verifier._
