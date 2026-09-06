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

## Phase 1 — Core + CLI (docs approved — complete)

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
  sync. _Depends on: archive-edit, catalog-schema, hashing-layout._
- [x] **browse-gallery** — album listing/counts + optional HTML gallery.
  _Depends on: catalog-schema._
- [x] **thumbnails** — generate + cache thumbnails under `.ibackup/thumbnails/`
  (HEIC via `pillow-heif`), reuse cache, never modify originals. _Depends on:
  hashing-layout._
- [x] **service-layer** — headless facade (`app_service.py`) + progress/cancel
  + result DTOs, exposing all operations. _Depends on: albums, browse-gallery,
  dedup, importer, phone-diff, reclaim, recycle-bin, thumbnails, verifier._
- [x] **archive-edit** — multi-select move/delete + mark-for-delete queue.
  _Depends on: catalog-schema, hashing-layout, service-layer._
- [x] **cli-wiring** — wire all subcommands to the service layer. _Depends on:
  albums, archive-edit, browse-gallery, dedup, importer, reclaim,
  service-layer, verifier._

## UI sketch gate (before any GUI code)

- [x] **ui-sketch** — written at `docs/ui-sketch/README.md`; produce UI sketch/wireframe (main window, album nav,
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

- [~] **tests** — pytest suite (unit + mocked device + pytest-qt GUI +
  `hypothesis` property tests + golden E2E/crash-resume `test_e2e.py`), **run
  after each module during development** and as a final full-suite gate.
  _Depends on: archive-edit, dedup, gui-frontend, hashing-layout, importer,
  name-safety, phone-diff, recycle-bin, service-layer, thumbnails, verifier._
  Status: **179 tests green, 91% coverage** for core + catalog + service + CLI;
  `test_gui.py` still to be written after the GUI exists.

## Future backlog (agreed, not scheduled)

Architect recommendations captured for later — not part of the current build:

- [ ] **future-schema-migrations** — versioned SQLite migrations + upgrade test.
- [ ] **future-audit-log** — structured logging + append-only operation audit log
  in `.ibackup/logs/` (import/delete/reclaim/purge with hashes).
- [ ] **future-catalog-repair** — rebuild/repair `catalog.sqlite` from sidecars.
- [ ] **future-release-checklist** — CHANGELOG/SECURITY/CONTRIBUTING/LICENSE,
  signed reproducible PyInstaller build, `.exe` smoke test, version tagging.
- [ ] **future-dep-hygiene** — pinned lockfile + `pip-audit` / Dependabot.
- [ ] **future-destructive-guardrails** — extend dry-run + explicit-confirm to
  every destructive op (purge/delete/move-to-Deleted).
