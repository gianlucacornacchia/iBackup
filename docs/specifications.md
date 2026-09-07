# iPhone Archive (`ibackup`) — Specifications

Status: Draft for review (Phase 0 documentation)

## 1. Purpose

`ibackup` (product name: **iPhone Archive**) is a **Windows** desktop
application, offered as both a CLI and a GUI, that creates a permanent,
append-only archive of photos and videos from a USB-connected iPhone. It is a
**preservation** tool, not a synchronization tool. The archive — not the phone —
is the long-term source of truth.

## 2. Primary Objectives

1. Create reliable backups of photos and videos from a USB-connected iPhone.
2. Preserve original files byte-for-byte, without modification or re-encoding.
3. Create a permanent archive independent of the phone.
4. Ensure photos deleted on the phone remain safely stored in the archive.
5. Detect duplicates using content hashes (SHA-256).
6. Support incremental imports.
7. Verify the integrity of every imported asset.
8. Preserve album information whenever available.
9. Provide safe workflows for freeing storage space on the phone.
10. Operate entirely locally, without mandatory cloud services.
11. Store media as **plain files in plain directories organized by album**, so
    the archive is fully browsable and viewable in **Windows File Explorer**
    **without this application**.

## 3. Non-Goals

- Not a synchronization tool.
- Does not mirror deletions from the phone.
- Does not edit images or videos.
- Does not re-encode media.
- Does not replace Apple Photos.
- Does not require cloud storage.

## 4. Core Design Principles

- The archive is **append-only**.
- Once imported, an asset remains stored until explicitly removed by the user.
- Deleting content from the phone never automatically deletes content from the
  archive.
- The archive is the source of truth.
- Integrity and verification take priority over speed.
- All operations are local and privacy-preserving.
- Stored media must remain usable with **no dependency on this application**.

## 5. System Overview

- **Target platform:** Windows 10/11 (64-bit).
- **Language / runtime:** Python 3.11+.
- **Interface:** a **command-line interface (CLI)** and a **graphical interface
  (GUI)**, both first-class and shipped together.
- **GUI framework:** **PySide6 (Qt for Python, LGPL)** — with efficient
  thumbnail grids (`QListView` icon mode), built-in multi-selection, context
  menus/drag-and-drop, and `QThread`/`QProgressDialog` for progress and
  cancellation.
- **Frontend-agnostic core:** all operations are exposed through a headless
  **service/application layer**. The CLI and the GUI are **both thin adapters**
  over this same layer, so every operation is available identically in both.
- **Device access:** the `pymobiledevice3` Python library, using the AFC (Apple
  File Conduit) media domain over USB. On Windows this uses the **Apple Mobile
  Device USB driver** installed by Apple's **iTunes / "Apple Devices"** app; no
  drive mount is required.
- **Catalog:** a SQLite database plus per-asset JSON sidecars, stored in a
  hidden `.ibackup/` folder. These are an index/recovery aid only — the plain
  media files remain fully usable without them.
- **Hashing:** SHA-256 for both duplicate detection and integrity verification.

## 6. Archive Layout

The archive lives under a user-chosen `<archive_root>`:

```
<archive_root>/
  Photos/
    <Album Name>/                 # one directory per phone album, real files
        IMG_0001.HEIC
        IMG_0002.MOV
    _Unsorted/YYYY/MM/            # assets that belong to no album, by date
  Deleted/                        # "recycle bin" for items removed from Photos/
    <Album Name>/                 #   original album subpath is preserved
    _Unsorted/YYYY/MM/
  .ibackup/                       # hidden application internals
    catalog.sqlite                # source-of-truth index
    sidecars/<sha256>.json        # per-asset metadata
    thumbnails/<sha256>.jpg       # cached thumbnails (for the GUI grid)
    tmp/                          # staging area for atomic writes
    logs/                         # per-run logs
```

Rules:

- **Real files only.** Media is stored as ordinary files. **Symlinks are never
  used**, so files remain valid when the archive is copied to another disk or to
  an exFAT/FAT drive.
- **Album folders are self-contained.** An asset that belongs to one or more
  albums is placed as a real file inside **each** of its album folders. An
  asset with no album is placed under `_Unsorted/YYYY/MM/`.
- **Multi-album duplication is intentional.** A photo in N albums exists as N
  files so each album folder can be browsed independently. On-phone duplicate
  detection still prevents re-importing the same asset.
- **Optional link mode.** `--album-link-mode` may be `copy` (default; maximum
  portability) or `hardlink` (space-saving, only where the filesystem supports
  it, e.g. NTFS). It automatically falls back to `copy` on exFAT/FAT.
- **Immutability.** Files are immutable once committed; imports never modify or
  overwrite existing archive files.
- **`Deleted/` recycle bin.** The `Deleted/` tree holds items the user removed
  from `Photos/` via the "deleted from phone" review (§18). It mirrors the album
  subpath, retains the original bytes, and is excluded from normal album
  browsing. Items here can be restored to `Photos/` or permanently purged.

Album names and file names are sanitized so every path is valid on Windows
(NTFS/exFAT) and in File Explorer:

- Replace reserved characters `< > : " / \ | ? *` and control characters
  (0x00–0x1F) with `_`.
- Strip trailing dots and spaces from each path component.
- Avoid Windows reserved device names (case-insensitive): `CON`, `PRN`, `AUX`,
  `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`; if encountered, prefix with `_`.
- Resolve case-insensitive collisions (Windows treats `IMG.JPG` and `img.jpg`
  as identical).
- Keep total path length within the legacy Windows limit (< 260 characters).
- Preserve the original name when it is already safe; append a short content-
  hash suffix (e.g. `IMG_0001~a1b2c3.HEIC`) only to break a collision.

## 8. Catalog Schema (SQLite)

- `assets(id, sha256 UNIQUE, size, original_name, captured_at, imported_at,
  verified_at, media_type, first_seen_on_phone_at, last_seen_on_phone_at,
  present_on_phone, archive_state, phone_asset_id, phone_path, phone_size,
  phone_modified_at)` — the last four form the lightweight **phone identity**
  used for fast incremental skip; `archive_state` is `active` (in `Photos/`) or
  `deleted` (moved to `Deleted/`); `present_on_phone` and `last_seen_on_phone_at`
  track whether the asset still exists on the phone.
- `asset_files(id, asset_id, path, album_id NULL, link_mode, location)` —
  every on-disk copy of an asset; `location` is `photos` or `deleted`.
- `albums(id, phone_album_id, name, safe_name, kind)`
- `asset_albums(asset_id, album_id)` — many-to-many membership.
- `import_sessions(id, device_udid, started_at, finished_at, added_count,
  skipped_count, error_count)` — a session also records the scan that updates
  `present_on_phone` / `last_seen_on_phone_at`.
- `deletion_marks(id, target_type, target_id, marked_at, reason NULL,
  committed_at NULL)` — staged "mark-for-delete" items (asset or album) awaiting
  an explicit commit; supports a GUI "review before delete" workflow.
- Indexes on `assets.sha256`, `assets.present_on_phone`, `asset_albums.album_id`,
  `asset_files.path`, `deletion_marks.committed_at`.
- For fast incremental scans, the catalog also records a lightweight **phone
  identity** per asset — `phone_asset_id` (from `Photos.sqlite` when available)
  and/or `phone_path` + `phone_size` + `phone_modified_at` — so already-imported
  items are recognized **without re-reading their bytes**.

Each asset also has a sidecar `.ibackup/sidecars/<sha256>.json` describing its
hash, size, original name, source path on the phone, capture time, and album
memberships.

## 9. Import Workflow

1. Detect and pair the device; open an AFC session.
2. Enumerate media from the AFC media domain (`/DCIM` and, best-effort,
   `PhotoData/Photos.sqlite` for album membership). Enumeration reads only
   metadata (name, size, dates, identifier), not file contents.
3. **Fast skip pass (no data transfer):** for each enumerated item, look up its
   phone identity (`phone_asset_id`, or `phone_path`+`phone_size`+
   `phone_modified_at`) in the catalog. If it matches an already-imported asset,
   **skip the transfer** entirely — only reconciling album membership if new
   albums were discovered (append-only album growth). This keeps re-runs on large
   libraries fast, since unchanged items are never re-copied.
4. **Import pass (new/changed items only):** for each remaining candidate:
   a. Stream it from the phone into `.ibackup/tmp` while computing SHA-256.
   b. If the resulting hash already exists (same content under a different phone
      identity), **skip** as a duplicate and just link the identity/album.
   c. Otherwise verify the staged file's hash, then **atomically rename** it into
      each destination album folder (or `_Unsorted`).
   d. Write the sidecar and commit the catalog rows (including phone identity).
5. Record an `import_sessions` summary (added / skipped / errors) and update
   `present_on_phone` / `last_seen_on_phone_at` for the deleted-from-phone review.

The import is idempotent: interrupted runs resume cleanly using the catalog and
the temp-file discipline. Only genuinely new bytes are transferred on each run.

## 10. Duplicate Detection

- Duplicates are identified by identical SHA-256 content hash.
- `ibackup dedup --report` reports duplicate counts and the storage cost of
  intentional multi-album copies.
- Dedup never deletes files; it only reports.

## 11. Integrity Verification

- After every copy, the stored file is re-hashed and compared to the source
  hash before the import is committed.
- `ibackup verify` re-hashes on-disk copies (every `asset_files` row) and
  compares against the catalog, reporting any mismatches or missing files.
- `verify --full` checks all files; a default run may check a rolling subset.

## 12. Album Preservation

- Album membership is read best-effort from the phone's `PhotoData/Photos.sqlite`
  via AFC.
- If album data cannot be read (iOS version, pairing state, permissions),
  import still succeeds and affected assets are filed under `_Unsorted/YYYY/MM/`.
- Album membership discovered on a later import is added (append-only); existing
  files are never moved or deleted automatically.

## 13. Space Reclamation (Safety Model)

- A phone-side file is eligible for deletion **only** if it is present in the
  catalog **and** passes a fresh integrity verification.
- `ibackup reclaim --dry-run` lists eligible files without deleting anything.
- `ibackup reclaim --confirm` deletes eligible phone-side files after explicit
  confirmation.
- Deletion never runs automatically and never touches archive files.

## 14. Error Handling & Logging

- All operations are logged per run under `.ibackup/logs/`.
- Errors on individual assets are recorded and counted; a failing asset does not
  abort the whole import.
- The catalog is updated transactionally so a crash cannot leave a half-recorded
  asset.

## 15. Constraints & Assumptions

- Requires a trusted (paired) USB connection to an unlocked iPhone.
- Requires the **Apple Mobile Device USB driver** on Windows (installed by
  Apple's iTunes or "Apple Devices" app).
- Album extraction depends on AFC access to `Photos.sqlite`, which is not
  guaranteed on all iOS versions.
- Recommended archive filesystems: **NTFS** (supports hardlinks) or **exFAT**
  (copy mode) for large external drives.

## 16. Frontend Architecture (CLI + GUI)

The application ships **two first-class frontends** over one headless core:

- A headless **service/application layer** exposes every capability (import,
  verify, dedup, album browsing/query, selection, move, delete, mark-for-delete,
  reclaim) as UI-agnostic operations that return structured result objects.
- The **CLI** (`ibackup`) and the **GUI** (`ibackup-gui`) are **both thin
  adapters** over this layer, guaranteeing the GUI can perform **every**
  operation the CLI can, and vice versa.
- Long-running operations (`import`, `verify`, `reclaim`) report **progress** and
  support **cancellation** through a small handle; the CLI shows a progress line
  and the GUI a progress dialog with a cancel button.
- Read/query operations return data suitable for a GUI (album summaries, asset
  records including on-disk paths usable for thumbnails, paginated listings).

### 16.1 GUI framework and packaging

- **Framework:** PySide6 (Qt for Python), LGPL. Chosen for efficient thumbnail
  grids, built-in multi-selection, context menus/drag-and-drop, and Qt threading
  for responsive long operations. (Keeping the GUI in Python preserves the whole
  Python core, including `pymobiledevice3` device access; a native WinUI/C# GUI
  would require rewriting that core and is therefore not adopted.)
- **Packaging:** a single distribution provides both console entry points —
  `ibackup` (CLI) and `ibackup-gui` (GUI). A portable Windows build (`.exe`,
  optionally an MSIX installer) is produced with PyInstaller; `pip install` also
  exposes both.
- **GUI keeps no business logic:** all actions call `service/`; the GUI only
  binds widgets, renders result DTOs, and forwards progress/cancel.

### 16.2 GUI capabilities (must match the CLI)

- Browse pictures as a thumbnail grid; browse albums (including `_Unsorted`).
- Multi-select pictures (Ctrl/Shift/rubber-band) for batch actions.
- Move selected pictures between albums.
- Delete, or mark-for-delete, individual pictures and whole albums; staged marks
  require an explicit commit before anything is removed.
- View which phone assets are safe to delete (archived + verified) and run the
  reclaim workflow with confirmation.
- **Review assets that were deleted from the phone** and decide, per item, to
  purge them from the archive or move them to the `Deleted/` folder (see §18).
- Run import/verify/dedup with visible progress and cancellation.

### 16.3 UI sketch approval gate (required before building the GUI)

Before any GUI code is written, a **UI sketch / wireframe** of the main window
and key views (album navigation, picture grid with multi-select, deleted-on-phone
review, reclaim, progress dialog) is produced and saved under `docs/ui-sketch/`.
Implementation of the PySide6 GUI **must not begin until the user explicitly
approves the sketch**. This is a hard gate in the build plan.

The sketch also fixes the **visual language: a modern Windows 11 Fluent
application** — Qt's native `windows11` style, DWM Mica backdrop, rounded
corners, system dark mode and accent color, the WinUI type ramp and color
tokens, and a NavigationView + command bar layout with **no classic menu bar**.
No GPL-licensed widget library is used. See `ui-sketch/README.md` §0 and
ADR-0010.

## 17. Archive Editing: Move, Delete, and Mark-for-Delete

These are **explicit, user-initiated** operations, distinct from the append-only
*automatic* guarantee (the app never deletes on its own):

- **Mark-for-delete:** the user may mark individual pictures or whole albums for
  deletion. Marks are staged in `deletion_marks` and change nothing on disk until
  the user explicitly commits them. Marks can be listed and un-marked.
- **Delete (commit):** committing marked items (or a direct delete request)
  removes the selected archive files after an explicit confirmation. Deleting an
  album removes that album folder's copies; a picture that also lives in other
  albums remains in those other albums.
- **Move:** the user may move selected pictures between albums (i.e. change album
  membership / folder placement). Moves are performed atomically and never modify
  file content.
- **Batch/selection:** move, delete, and mark operations accept **multiple
  selected items** at once, supporting a GUI multi-select workflow.
- **Safety:** these operations never touch the phone. The separate `reclaim`
  workflow is the only path that deletes phone-side files, and only for archived
  + verified assets on explicit confirmation.

## 18. Review of Assets Deleted from the Phone

This workflow lets the user see which archived pictures/videos **no longer exist
on the phone** and decide, per item, what to do with the archived copy. It never
deletes anything automatically; the archive stays the source of truth.

### 18.1 Detection

- On each import/scan the app records, for every catalog asset, whether it was
  seen on the phone this session (`present_on_phone`, `last_seen_on_phone_at`).
- An asset is considered **deleted from the phone** when it exists in the catalog
  with `archive_state = active` but was **not** seen in the latest phone scan.
- Matching an archived asset to a phone asset is done by **content hash**
  (reliable) and, when available, the phone asset identifier. Hash matching
  reuses hashes already stored in the catalog, so detection does not re-copy
  media; a scan reads the phone's inventory, not full file contents, where a
  stable identifier is available.
- Detection is **read-only**: it changes no files.

### 18.2 Presentation

- `deleted-on-phone list` (CLI) and a dedicated GUI view show the assets that are
  in the archive but gone from the phone, with thumbnails, album, and the date
  last seen on the phone.
- The list supports **multi-select** for batch decisions.

### 18.3 Per-item decisions

For each selected asset the user chooses one of:

1. **Delete from the local archive** — permanently removes all archive copies of
   the asset (all album-folder files and any `_Unsorted` copy) after an explicit
   confirmation. This is the same underlying operation as §17 "Delete".
2. **Move to the `Deleted/` folder** — relocates all copies from `Photos/…` into
   `Deleted/…`, preserving the original album subpath, and sets
   `archive_state = deleted`. This is a **non-destructive** "recycle bin": the
   bytes are retained and the item can be restored to `Photos/` later. Items in
   `Deleted/` are excluded from normal album browsing but remain integrity-
   verified.

### 18.4 Safety and defaults

- No default action is taken automatically; the user must choose per item (or per
  multi-selection).
- Moving to `Deleted/` is preferred as the safe, reversible option; purging from
  the archive requires explicit confirmation.
- Emptying `Deleted/` (permanent purge of everything inside) is a separate,
  explicitly-confirmed operation.
- This workflow only ever affects the **archive**; it never deletes from the
  phone (that is the separate `reclaim` workflow).

## 19. Performance & Scalability

The app is designed for large libraries (tens of thousands of items, tens to
hundreds of GB). Behavior and expected timing:

### 19.1 What dominates the time

- **First full import is bound by USB transfer speed**, not by CPU. Every byte
  must be copied from the phone over AFC. SHA-256 hashing (~0.5–1 GB/s per core)
  and SQLite writes are negligible next to USB throughput, because hashing is
  done **in-stream** while copying (single read of each file).
- **Lightning iPhones use USB 2.0**, so effective AFC throughput is typically
  **~20–40 MB/s** regardless of the PC. USB-C iPhones (15 Pro and later) can be
  faster, but AFC over `pymobiledevice3` is often still the practical limit.

### 19.2 Rough first-import estimates (copy + verify)

Assuming ~30 MB/s effective AFC throughput:

| Library size | Approx. data | Approx. first-import time |
|---|---|---|
| 10,000 photos (mostly HEIC) | ~30 GB | ~15–30 min |
| 25,000 mixed photos+videos | ~80 GB | ~45–90 min |
| 50,000 mixed + many videos | ~200 GB | ~2–3.5 hours |

Videos dominate size, so a library's minutes-per-item varies widely. These are
one-time costs; the archive persists.

### 19.3 Incremental runs are fast

- Subsequent imports use the **fast skip pass** (§9 step 3): the phone inventory
  is enumerated (metadata only) and matched against stored **phone identity**, so
  **already-archived items are never re-transferred or re-hashed**.
- Time for a re-run ≈ (metadata enumeration of the whole library, seconds to a
  couple of minutes) + (transfer of only the new items). Adding a day's photos to
  a 30,000-item archive typically completes in well under a minute of transfer.

### 19.4 Catalog, memory, and detection

- **Catalog:** SQLite with the indexes in §8 handles hundreds of thousands of
  rows comfortably; lookups for skip/dedup are indexed and O(log n).
- **Memory:** copying and hashing are **streamed in fixed-size chunks**, so peak
  memory is constant regardless of file or library size.
- **Deleted-from-phone detection** (§18) is a set-difference between the phone
  inventory and the catalog — metadata only, no content reads.

### 19.5 GUI at scale

- The picture grid uses **virtualized/lazy rendering** (only visible thumbnails
  are materialized), so tens of thousands of items scroll smoothly.
- Thumbnails are **generated once and cached** under `.ibackup/thumbnails/`
  (HEIC decoded via `pillow-heif`), so browsing does not re-decode originals.
- Thumbnail generation for a large library is incremental and backgrounded; the
  first browse of a new archive builds the cache progressively.

### 19.6 Tunables

- Copy/hash **chunk size** and the number of **background thumbnail workers** are
  configurable.
- `--album-link-mode hardlink` avoids duplicating bytes for multi-album assets on
  NTFS, reducing both time and space for heavily-albumed libraries.
