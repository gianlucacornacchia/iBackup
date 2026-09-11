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
  headless `service/` layer, with full parity required and tested.
- **GUI framework:** PySide6 **6.7+** (Qt for Python, LGPL). Native WinUI/C#
  could bridge the Python core; rejected for additional interop/toolchain cost,
  not because a rewrite is unavoidable (ADR-0011).
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
2. **Phase 1 — Core + CLI baseline implemented offline.** Historical tests
   establish a baseline, not hardware readiness.
3. **Core-hardening checkpoint — complete offline.** Closed source identity,
   migrations, bounded device streaming, scan/reclaim safety, archive recovery,
   service locking/cancellation, typed confirmation, CLI parity and log wiring
   gaps. Final lint/type/test evidence is recorded in `progress.md`.
4. **Windows/iPhone gate — pending.** Read/album/large-video matrix must pass
   before enabling real-phone destructive reclaim. Offline tests cannot lift
   this gate; see `unit-tests.md` §4.
5. **UI sketch gate — PASSED (2026-09-11).** The sketch under `docs/ui-sketch/`
   plus the clickable PySide6 mock in `docs/ui-sketch/mockup/` were reviewed and
   **approved**, unblocking `gui-theme` and `gui-frontend`.
6. **Phase 2 — Build GUI (in progress).** Broken into the twelve steps in §2b,
   built bottom-up with tests and one commit per step. Mica remains unverifiable
   off Windows.
7. **Release milestone — scheduled after validation.** Windows-build and
   clean-machine smoke-test CLI packaging, notices and versioned artifacts.
   First add a CLI packaging recipe; no spec is added during this remediation.
   GUI packaging follows GUI implementation/tests; no release is available now.

## 2b. Phase 2 GUI step breakdown

Twelve steps, each one commit, built bottom-up with tests. Dependencies mean a
step never starts before the layer beneath it is proven.

**Phase A — foundations (nothing visible yet)**

1. `gui-scaffold` — `src/iphone_archive/gui/` package, `ibackup-gui` entry
   point, QApplication bootstrap, empty main window, offscreen smoke test.
2. `gui-theme` — WinUI light/dark tokens promoted from the mock, system-follow
   via settings, DWM Mica and rounded corners on Windows with honest fallback.
   Implemented offline: persisted `theme=system|light|dark`, live accent and
   high-contrast handling, guarded DWM calls. Normal launches retain solid
   painting; `--mica-probe` explicitly opts into unverified translucent Qt
   painting. Live Windows qualification is still pending.
3. `gui-worker` — **the highest-risk step.** `AppService` is single-thread
   affine and holds an exclusive archive lock, so a dedicated worker thread owns
   it and every call is marshalled, with queued progress/result/error signals,
   cancellation and clean shutdown. Isolated here deliberately rather than
   sprinkling thread calls through the views.

**Phase B — data plumbing**

4. `gui-models` — lazy-paging list model over `AssetView` (the test phone holds
   1 297 items, so eager loading would stall the window), album model, and the
   selection mapping that preserves album-copy scope rather than silently
   promoting a selection to every copy of an asset.
5. `gui-thumbnail-loader` — background thumbnail pipeline with a bounded LRU
   cache, request coalescing, cancel-on-scroll and pending/failed placeholders.

**Phase C — interface**

6. `gui-shell` — navigation pane with live counts, stacked pages, command bar,
   status bar, phone connected/disconnected state.
7. `gui-gallery` — grid, rubber-band and Ctrl/Shift selection, selection bar,
   viewer, context menu.
8. `gui-ops-safe` — import, verify, scan-phone, dedup, stats, move to album,
   behind a progress dialog that can be cancelled or hidden.
9. `gui-ops-destructive` — typed-DELETE confirmation, deleted-on-phone
   keep/move/purge, recycle-bin restore/purge, marks commit and reclaim, always
   dry-run first.
10. `gui-settings` — the six settings panels; also closes `settings-store`.

**Phase D — proof**

11. `gui-parity-tests` — a test that fails if any CLI command or service method
    has no GUI surface, plus end-to-end `pytest-qt` flows run offscreen.
12. `gui-packaging` — PyInstaller executable, icon, version resource and a
    smoke test of the built artifact.

Mica, native window chrome and the Apple USB driver path cannot be validated on
the Linux development machine; they are built to spec and marked unverified
until a Windows run.

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
- Import uses per-item recovery journals (stage → hash-verify → exclusive
  placement → sidecar/catalog commit). Private staging ownership is durable
  before media creation; final publication preserves identity without overwrites
  using Windows rename or POSIX hardlink. Unsupported publication fails safely.
  Files are immutable once committed; power-loss guarantees require
  filesystem-specific validation.

## 4. Module structure (see `structure.md` for detail)

```
src/iphone_archive/
  cli.py                # thin adapter over service/
  config.py, settings.py, logging_setup.py
  service/              # headless API for CLI + GUI
    app_service.py, archive_lock.py, progress.py, selection.py, marks.py
  device/               # interface.py, afc_device.py, fake_device.py
  catalog/              # database, models, repository, sidecar
  core/                 # hashing, name_safety, archive_layout, importer,
                        #   dedup, verifier, albums, reclaim,
                        #   phone_diff, recycle, file_operations
  browse/               # gallery (read models only) + thumbnails (cache)
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
- Schema v2 `source_identities(device_udid, phone_path, asset_id,
  phone_asset_id, phone_size, phone_modified_at, present, last_seen_at)`,
  keyed by `(device_udid, phone_path, asset_id)`: device-scoped many-to-one
  content provenance and complete-scan presence, not global path matching.
- `import_commits(journal_id)` and `meta` file-operation commit markers support
  import/edit journal recovery. Legacy v1 content is retained without invented
  source identities; newer unsupported schema versions fail closed.
- `asset_albums` reflects active copies; deleted copies retain album IDs in
  `asset_files`. Any active copy keeps its asset active.

## 6. CLI commands (first release)

Implemented source CLI (not a shipped binary): `init`, `device-info`,
`import [--album-link-mode ...]`, `verify`,
`dedup`, `albums`, `list`, `stats`, `scan-phone`, `thumbnail`,
`move [--from-album ALBUM_ID] [--file FILE_ID ...]`,
`reclaim [--asset ID ...] [--confirm]`,
`deleted-on-phone list|to-deleted|restore|purge`, `clear-thumbnails`,
`marks add|list|remove|clear|commit`, `config get|set|list|reset|path|forget`.
`device-info`, `import`, `scan-phone`, `reclaim` and `deleted-on-phone list`
accept `--device UDID`; the latter scopes both the report and optional rescan.
Move/recycle/restore/purge accept repeated `--file ID` with required asset IDs;
purge additionally supports `--recycled-only`. `marks add <id> --file` instead
marks one copy for later commit and is mutually exclusive with `--album`.
Permanent deletion requires interactive typed `DELETE`; reversible marks
commit keeps explicit `--confirm`. No `gallery`, `dedup --report`,
`verify --full`, or `reclaim --dry-run` command exists.

## 7. Feature: review of assets deleted from the phone

- **Detection (read-only):** import/scan records `present_on_phone` /
  `last_seen_on_phone_at`; assets active in the archive but absent from the
  latest complete successful scan of the same device are "deleted from phone".
  Unknown legacy identity and interrupted scans must not create absence.
- **Per-item decision** (multi-select): (1) delete from the local archive
  (permanent, confirmed) or (2) move to `Deleted/` (non-destructive recycle bin;
  restore or purge later). Never automatic; never touches the phone.

## 8. Build order (high level)

scaffold → name-safety → device-access → catalog-schema → hashing-layout →
sidecar → importer → dedup → verifier → albums → phone-diff → reclaim →
recycle-bin + archive-edit primitives → browse-gallery → thumbnails →
service-layer → cli-wiring → settings-store → **core hardening** →
**UI sketch approval (gate)** → gui-theme
(`theme.py` + `win32_effects.py`; solid painting until the Windows Mica probe
is validated) → gui-frontend →
tests → Windows release validation. Device read/album/large-video validation
separately gates real-phone destructive reclaim. US-D4 HTML gallery is deferred.

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
    coverage; the exact paths/threshold in configuration are authoritative.
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
  phone_diff, recycle, thumbnails, service, marks, selection, cli; GUI coverage
  is planned, not implemented. See
  `unit-tests.md`.

## 10. Performance & scalability (see `specifications.md` §19)

- Designed for tens of thousands of items / tens–hundreds of GB.
- Throughput estimates are hypotheses, not hardware measurements. Benchmark
  transfer, verification, metadata and album-copy costs separately.
- Fast-skip can avoid transfers for trusted unchanged device identities; stale
  or migrated identities and missing copies require revalidation.
- Chunked file reads bound media buffers, not total library metadata memory.
  GUI virtualization, pagination and bounded thumbnail queues remain planned.

## 11. Progress

- **Phase 0 (docs): DONE and approved.**
- **Phase 1 baseline and core hardening complete offline.** Offline
  fake-device behavior is not a real-phone or release qualification.
- **UI sketch: approved 2026-09-11** (`docs/ui-sketch/`), including the Windows
  11 Fluent visual spec and clickable mock.
- **Phase 2 (GUI): in progress.** Scaffold and theme layer are implemented
  offline; the worker is next. Live Windows Mica/chrome qualification is pending.
- **Windows hardware and release milestones pending.** Migrations and basic
  destructive guardrails are core hardening, not optional future work. Catalog
  rebuild, tamper-proof audit logging, dependency automation and HTML gallery
  remain separately tracked enhancements.

See `progress.md` for the detailed, resumable status.
