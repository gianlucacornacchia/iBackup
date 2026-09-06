# iPhone Archive — Unit Test Plan

Status: Draft for review (Phase 0 documentation)

This document lists the unit tests to run, what each covers, and how to execute
them. Tests use **pytest**. Device access is mocked with a fake source so the
suite runs without a phone and without network access.

**Workflow requirement:** tests are written alongside each module and **`pytest`
is run after writing code for every module/todo**. A module is not considered
done until its targeted tests pass; the full suite is run before completing a
phase.

## 1. How to run

```bash
# From the project root, after installing dev dependencies
pip install -e ".[dev]"        # installs pytest, pytest-qt, PySide6, and the package
pytest                          # run the whole suite
pytest -q tests/test_hashing.py # run a single file
pytest -k dedup                 # run tests matching a keyword
pytest --cov=iphone_archive     # optional coverage (if pytest-cov installed)

# GUI tests run headless via Qt's offscreen platform:
QT_QPA_PLATFORM=offscreen pytest tests/test_gui.py
```

All tests are self-contained: they create temporary archives in `tmp_path` and
use in-memory or temporary SQLite databases. No real iPhone is required.

## 2. Test files and coverage

| Test file | Module under test | What it verifies |
|---|---|---|
| `tests/test_hashing.py` | `core/hashing.py` | Correct SHA-256 over known inputs; streaming matches one-shot; empty file; large/chunked input. **Property-based (`hypothesis`):** for arbitrary byte content, streamed chunked hashing equals `hashlib.sha256` regardless of chunk size. |
| `tests/test_name_safety.py` | `core/name_safety.py` | Reserved-char replacement; reserved device names; trailing dot/space stripping; case-insensitive collision resolution; path-length limiting; safe names preserved unchanged. **Property-based (`hypothesis`):** for arbitrary unicode names, the sanitized result always contains no reserved chars/names, has no trailing dot/space, stays within the length limit, and is deterministic/idempotent. |
| `tests/test_archive_layout.py` | `core/archive_layout.py` | Correct album-folder path computation; `_Unsorted/YYYY/MM` for album-less; atomic write (temp then rename); copy mode; hardlink mode with fallback to copy; no symlinks created. |
| `tests/test_catalog.py` | `catalog/database.py`, `repository.py` | Schema creation/migration; insert asset + asset_files; lookup by hash; list files to verify; album membership queries; uniqueness on `sha256`. |
| `tests/test_sidecar.py` | `catalog/sidecar.py` | Sidecar written with expected fields; round-trip read equals write; JSON is valid and stable. |
| `tests/test_importer.py` | `core/importer.py` | New asset imported and committed; **fast-skip pass** recognizes already-imported items by phone identity without transferring/re-hashing; duplicate content under a new identity is linked not re-stored; album-less asset filed under `_Unsorted`; multi-album asset placed in each album folder; interrupted/resumed import is idempotent; import summary counts. |
| `tests/test_dedup.py` | `core/dedup.py` | Duplicate detection by hash; multi-album storage-cost report; no files deleted. |
| `tests/test_verifier.py` | `core/verifier.py` | Passing verification on intact files; detects modified file (hash mismatch); detects missing file; `--full` checks all copies. |
| `tests/test_albums.py` | `core/albums.py` | Parses a sample `Photos.sqlite` into album membership; graceful fallback when DB missing/unreadable (assets -> `_Unsorted`). |
| `tests/test_reclaim.py` | `core/reclaim.py` | Only archived AND verified assets are eligible; dry-run deletes nothing; confirm path deletes only phone files via the fake device; archive never modified. |
| `tests/test_phone_diff.py` | `core/phone_diff.py` | Detects assets in the catalog but absent from the latest phone scan (matched by hash/identifier); ignores assets still present; detection changes no files. |
| `tests/test_recycle.py` | `core/recycle.py` | Move-to-`Deleted/` relocates all copies preserving album subpath and sets `archive_state=deleted`; moved items excluded from album browsing but still verify; restore returns to original `Photos/` path; purge permanently removes after confirmation. |
| `tests/test_gallery.py` | `browse/gallery.py` | Album listing and counts; optional HTML gallery references archived files; browsing does not depend on the app. |
| `tests/test_thumbnails.py` | `browse/thumbnails.py` | Generates a thumbnail for JPEG and HEIC (via `pillow-heif`); caches under `.ibackup/thumbnails/<sha256>.jpg`; second request reuses the cache without re-decoding; originals are never modified. |
| `tests/test_service.py` | `service/app_service.py` | Facade exposes every operation; returns structured DTOs (`results.py`); progress/cancel handle is honored (progress emitted, cancellation stops safely); the CLI and GUI share this single API. |
| `tests/test_marks.py` | `service/marks.py` | Mark/unmark asset and album for delete; staged items listed; nothing removed until commit; commit removes only staged files after confirmation. |
| `tests/test_selection.py` | `service/selection.py` | Multi-select move between albums (atomic, content unchanged); multi-select delete/mark applies to all; picture shared across albums handled correctly. |
| `tests/test_cli.py` | `cli.py` | Each subcommand is a thin adapter that calls the right `service/` operation and renders its result; error messages for missing device/archive. |
| `tests/test_gui.py` | `gui/` | With `pytest-qt`: main window builds; album list and picture grid populate from service DTOs; multi-select drives batch move/delete/mark; reclaim view lists safe-to-delete items; deleted-on-phone view lists absent items and offers purge / move-to-Deleted; progress/cancel wired to the service handle. GUI logic only — no business logic under test here. |
| `tests/test_e2e.py` | full pipeline (`service/` + `core/` + `catalog/`) over the **fake device** | **Golden end-to-end:** init → import → verify → dedup (second import transfers nothing) → deleted-on-phone review (move-to-`Deleted/` and purge) → reclaim, asserting the archive/catalog invariants (byte-for-byte files, album folders, append-only, `sha256 UNIQUE`, sidecar/catalog consistency). **Crash-resume:** an import interrupted mid-asset (simulated failure) leaves no partial file committed; re-running resumes cleanly and the final archive equals the uninterrupted result (idempotent). |

## 3. Shared fixtures (`tests/conftest.py`)

- `tmp_archive` — an initialized archive under `tmp_path` (Photos/ + .ibackup/).
- `fake_device` — an in-memory implementation of the `device/` interface that
  serves a set of fake media files and an optional fake `Photos.sqlite`, and
  records delete calls (for reclaim tests).
- `sample_media` — a small set of byte blobs with known SHA-256 values, plus a
  duplicate and a multi-album asset.
- `in_memory_catalog` — a SQLite catalog for repository tests.

## 4. Key scenarios explicitly covered

- **Byte-for-byte preservation:** imported file hash equals source hash.
- **Incremental import / dedup:** second import of the same content is skipped;
  the fast-skip pass matches by phone identity and transfers nothing.
- **Append-only:** phone-side deletion (simulated) does not remove archive files;
  a later album addition adds a copy without moving/removing existing files.
- **Integrity:** verification catches modified and missing files.
- **Album folders:** multi-album asset exists as a real file in each album
  folder; album-less asset lands in `_Unsorted`.
- **Windows safety:** generated names contain no reserved characters/names and
  respect length limits; collisions get unique names.
- **No symlinks:** archive placement never creates symbolic links.
- **CLI parity / service layer:** every CLI operation goes through
  `service/app_service.py`, so the CLI and the PySide6 GUI share one API.
- **Editing operations:** mark-for-delete stages without deleting; commit deletes
  only staged items after confirmation; move changes album placement without
  changing content; multi-select applies to all chosen items.
- **Reclaim safety:** deletion candidates require archive presence + fresh
  verification; dry-run is non-destructive; archive is never touched.
- **Deleted-from-phone review:** assets absent from the latest phone scan are
  detected read-only; the user's per-item choice either purges from the archive
  (after confirmation) or moves copies to `Deleted/` (reversible); the phone is
  never touched and nothing happens automatically.
- **Property-based invariants (`hypothesis`):** name-safety output is always
  Windows-safe/idempotent and hashing is chunk-size-independent for arbitrary
  input.
- **Golden end-to-end + crash-resume:** the full init→import→verify→dedup→
  deleted-review→reclaim pipeline holds all archive/catalog invariants, and an
  interrupted import resumes idempotently with no partial commits.

## 5. Definition of done for the test phase

- All listed test files exist and pass with `pytest`.
- Every `core/` module has at least the scenarios above covered.
- The suite runs offline, with no real device, in a temporary directory.
- **CI is green** on `windows-latest` (lint + type-check + tests) and total
  coverage meets the configured gate (target ~85%, `core/` + `catalog/` highest).
