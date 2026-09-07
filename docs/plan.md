# Implementation Plan — iPhone Archive (`ibackup`)

This is the authoritative, consolidated plan. It reflects all decisions to date.
Companion docs: `specifications.md`, `readme-user.md`, `user-stories.md`,
`structure.md`, `unit-tests.md`, `development.md`, `progress.md`, the ADRs under
`adr/`, the root `README.md`, and the build checklist in `todos.md`.

## 1. Summary

A **Windows** desktop application (CLI **and** GUI) that creates a permanent,
**append-only** archive of photos and videos from a **USB-connected iPhone**,
accessed via the `pymobiledevice3` AFC media domain. The archive — not the phone
— is the long-term source of truth. Media is stored as **plain files in plain
album folders**, fully browsable in **File Explorer without the app**.

Key decisions:
- **Target:** Windows 10/11 (64-bit). (Linux support dropped.)
- **Language:** Python 3.11+.
- **Frontends:** CLI (`ibackup`) + GUI (`ibackup-gui`), both thin adapters over a
  headless `service/` layer, guaranteeing full parity.
- **GUI framework:** PySide6 **6.7+** (Qt for Python, LGPL). Native WinUI/C#
  rejected because it would require rewriting the whole Python core (incl.
  `pymobiledevice3`).
- **GUI look:** a **modern Windows 11 Fluent** app, not a default Qt window —
  Qt's native `windows11` style + our own WinUI design tokens + DWM Mica /
  rounded corners / dark caption. No GPL widget library (ADR-0010).
- **Device access:** `pymobiledevice3` over USB (Apple Mobile Device driver from
  iTunes / "Apple Devices").
- **Catalog:** SQLite (source of truth) + per-asset JSON sidecars in hidden
  `.ibackup/`. Plain files stay usable without them.
- **Hash:** SHA-256 for dedup and integrity.
- **Packaging:** PyInstaller Windows `.exe` (optional MSIX); `pip` also works.

## 2. Delivery gates (hard stops)

1. **Phase 0 — Documentation only.** All docs under `docs/`, then **STOP for
   approval**. No source code. (Status: **DONE, approved**.)
2. **Phase 1 — Build core + CLI.** Only after docs are approved.
   (Status: **DONE** — 205 tests, 91% coverage.)
3. **UI sketch gate.** Before any GUI code, produce a **UI sketch/wireframe**
   under `docs/ui-sketch/` and **STOP for explicit approval**.
   (Status: **sketch written, HOLDING HERE**.)
4. **Phase 2 — Build GUI.** Only after the UI sketch is approved.

## 3. Archive layout (plain, album-organized, append-only)

```
<archive_root>/
  Photos/
    <Album Name>/                 # one directory per phone album, real files
    _Unsorted/YYYY/MM/            # assets that belong to no album, by date
  Deleted/                        # recycle bin (items removed from Photos/)
    <Album Name>/                 #   original album subpath preserved
    _Unsorted/YYYY/MM/
  .ibackup/                       # hidden: catalog.sqlite, sidecars/, tmp/, logs/
```

- **Real files only** (no symlinks) so the archive stays valid on any disk.
- Multi-album assets are placed in **each** album folder (self-contained
  browsing); `--album-link-mode copy|hardlink` (auto-fallback to copy).
- **Windows-safe names** (reserved chars/names, trailing dots/spaces,
  case-insensitive collisions, <260-char paths).
- Import is transactional per file (temp → hash-verify → atomic rename →
  sidecar → commit). Files immutable once committed.

## 4. Module structure (see `structure.md` for detail)

```
src/iphone_archive/
  cli.py                # thin adapter over service/
  config.py, logging_setup.py
  service/              # headless API for CLI + GUI
    app_service.py, progress.py, results.py, selection.py, marks.py
  device/               # afc_client, device_manager, media_source
  catalog/              # database, models, repository, sidecar
  core/                 # hashing, name_safety, archive_layout, importer,
                        #   dedup, verifier, albums, reclaim,
                        #   phone_diff, recycle
  browse/               # gallery (listing + optional HTML) + thumbnails (cache)
  gui/                  # PySide6 (built only after UI sketch approval)
tests/
```

## 5. Catalog schema (outline)

- `assets(id, sha256 UNIQUE, size, original_name, captured_at, imported_at,
  verified_at, media_type, first_seen_on_phone_at, last_seen_on_phone_at,
  present_on_phone, archive_state)`  — `archive_state` = active | deleted
- `asset_files(id, asset_id, path, album_id NULL, link_mode, location)` —
  `location` = photos | deleted
- `albums(id, phone_album_id, name, safe_name, kind)`
- `asset_albums(asset_id, album_id)`
- `import_sessions(...)`, `deletion_marks(...)`

## 6. CLI commands (first release)

Shipped: `init`, `device-info`, `import [--album-link-mode ...]`, `verify`,
`dedup`, `albums`, `list`, `stats`, `scan-phone`, `thumbnail`, `move`,
`reclaim [--confirm]`, `deleted-on-phone list|to-deleted|restore|purge`,
`marks add|list|remove|commit`, `config get|set|list|reset|path|forget`.

## 7. Feature: review of assets deleted from the phone

- **Detection (read-only):** import/scan records `present_on_phone` /
  `last_seen_on_phone_at`; assets active in the archive but absent from the
  latest phone scan are "deleted from phone" (matched by hash / phone id).
- **Per-item decision** (multi-select): (1) delete from the local archive
  (permanent, confirmed) or (2) move to `Deleted/` (non-destructive recycle bin;
  restore or purge later). Never automatic; never touches the phone.

## 8. Build order (high level)

scaffold → name-safety → device-access → catalog-schema → hashing-layout →
sidecar → importer → dedup → verifier → albums → phone-diff → reclaim →
recycle-bin → browse-gallery → thumbnails → service-layer → archive-edit →
cli-wiring → settings-store → **UI sketch (gate)** → gui-theme
(`theme.py` + `win32_effects.py`, preceded by a Mica probe) → gui-frontend →
tests.

See `todos.md` for the full checklist with dependencies and status.

## 9. Testing & development workflow

- **Use a Python virtual environment** (`.venv/`, git-ignored) for all
  development; never install into the global interpreter. Setup in
  `development.md`.
- **Run tests after writing code.** Every module is implemented together with its
  unit tests, and `pytest` is **run after each code change / todo** — not only at
  the end. A todo is not "done" until its tests pass locally.
- **Keep docs up to date while coding.** In the same change, update the living
  docs affected: `development.md` (setup / libraries / how to run tests),
  `readme-user.md`, `structure.md`, `unit-tests.md`, the root `README.md`, and any
  other relevant doc.
- **Save progress for resumability.** Update `progress.md` (and `todos.md`)
  whenever a todo changes state, so work can resume after any interruption.
- **Commit incrementally.** Make one logical git commit per step with a clear
  message so a developer can follow the project story from history — never a
  single code dump at the end. Keep the repo updated as work proceeds, but
  **do not push** (local commits only). Use **Conventional Commits**
  (`feat:`/`fix:`/`docs:`/`test:`/`chore:`…).
- **Quality gates (adopted).**
  - **Pre-commit hooks** (`.pre-commit-config.yaml`): `ruff` (lint + format),
    `mypy`, and hygiene hooks run before every commit.
  - **CI** on `windows-latest` (`.github/workflows/ci.yml`): venv + install →
    ruff → `mypy --strict` (core/catalog) → `pytest` (GUI headless) with
    coverage; **coverage gate** ~85% (core/catalog highest).
  - **Property-based tests** (`hypothesis`) for `name_safety` + hashing.
  - **Golden end-to-end + crash-resume test** (`tests/test_e2e.py`) over the fake
    device, asserting append-only/catalog invariants and idempotent resume.
  - **ADRs** under `docs/adr/` record every significant decision.
  These are created during `project-scaffold` (config/CI) and grow with the code.
- The `tests` todo is the final full-suite gate, but targeted tests run
  continuously during Phase 1/2.
- pytest suite (with `pytest-qt` for the GUI) runs offline with a fake device and
  temporary archives. Coverage: hashing, name-safety, archive layout, catalog,
  sidecar, importer (incl. fast-skip), dedup, verifier, albums, reclaim,
  phone_diff, recycle, thumbnails, service, marks, selection, cli, gui. See
  `unit-tests.md`.

## 10. Performance & scalability (see `specifications.md` §19)

- Designed for tens of thousands of items / tens–hundreds of GB.
- **First import is USB-bound** (Lightning = USB 2.0, ~20–40 MB/s): roughly
  ~15–30 min for ~30 GB, ~45–90 min for ~80 GB, a few hours for ~200 GB.
- **Incremental runs are fast:** a metadata-only enumeration + a **fast-skip**
  match on stored phone identity means already-archived items are never
  re-transferred or re-hashed; only new bytes move.
- Streamed chunked copy/hash → constant memory; SQLite indexes → O(log n)
  lookups; GUI grid is virtualized with a `.ibackup/thumbnails/` cache.

## 11. Progress

- **Phase 0 (docs): DONE and approved.**
- **Phase 1 (core + CLI): DONE.** All core, catalog, device, service, browse,
  settings and CLI modules implemented and committed. **205 tests, 91%
  coverage**, ruff + mypy clean. Runs end to end offline against a fake device.
- **UI sketch: written** (`docs/ui-sketch/`), including the Windows 11 Fluent
  visual spec. **Holding at the UI-sketch approval gate.**
- **Phase 2 (GUI): blocked** on that approval. First task on approval is the
  theming layer plus a Mica probe, then the views.
- Deferred by agreement: the 6 `future-*` backlog items.

See `progress.md` for the detailed, resumable status.
