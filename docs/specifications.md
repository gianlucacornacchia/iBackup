# iPhone Archive (`ibackup`) — Specifications

Status: living requirements, not an implementation/compliance report.
Core/CLI hardening is complete offline. The UI sketch was approved on
2026-09-11 and the GUI (Phase 2 steps 1-12, including a PyInstaller build
recipe) is implemented; the Mica probe, Windows release and destructive
Windows/iPhone validation are pending. See `progress.md` for executed evidence.

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
10. Operate entirely locally, without mandatory cloud services. The single
    exception is the optional GUI trip map (§16.4), which downloads
    OpenStreetMap tiles while open; no archive operation needs the network.
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
- All archive operations are local and privacy-preserving. Media and catalog
  data are never uploaded; the only network traffic is the optional map's
  tile requests (§16.4), which reveal the viewed map area to the tile server.
- Stored media must remain usable with **no dependency on this application**.

## 5. System Overview

- **Target platform:** Windows 10/11 (64-bit).
- **Language / runtime:** Python 3.11+.
- **Interface:** a **command-line interface (CLI)** and a **graphical interface
  (GUI)**, both first-class and both implemented from source; parity is
  enforced by `tests/test_gui_parity.py`.
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
    _Shared Albums/<Album Name>/  # iCloud Shared Albums, real files
  Deleted/                        # "recycle bin" for items removed from Photos/
    <Album Name>/                 #   original album subpath is preserved
    _Unsorted/YYYY/MM/
  .ibackup/                       # hidden application internals
    catalog.sqlite                # source-of-truth index
    sidecars/<sha256>.json        # per-asset metadata
    thumbnails/<sha256>_<size>.jpg # cached still-image thumbnails
    tmp/                          # staging area for atomic writes
    logs/                         # per-run logs
```

Rules:

- **Real files only.** Media is stored as ordinary files. **Symlinks are never
  used**, so files remain valid when the archive is copied to another disk or to
  an exFAT/FAT drive.
- **Album folders are self-contained.** An asset that belongs to one or more
  albums is placed as a real file inside **each** of its album folders. An
  asset with no album is placed under `_Unsorted/YYYY/MM/`. For assets still
  on the phone, placement follows the phone's *current* membership (§12).
- **Multi-album duplication is intentional.** A photo in N albums exists as N
  files so each album folder can be browsed independently. On-phone duplicate
  detection still prevents re-importing the same asset.
- **Optional link mode.** `--album-link-mode` may be `copy` (default; maximum
  portability) or `hardlink` (space-saving, only where the filesystem supports
  it, e.g. NTFS). It automatically falls back to `copy` on exFAT/FAT.
- **Immutability.** Files are immutable once committed; imports never modify or
  overwrite existing archive files. Imports may *remove* two kinds of file:
  a `Photos/` album or `_Unsorted` copy whose placement the phone no longer
  reports (§12), and the low-resolution file of an offloaded preview being
  upgraded to its original (§9). Neither removes an asset's last copy.
- **Offloaded previews.** A preview is stored as
  `<original stem> (offloaded preview).<ext>` (normally `.jpg`) in the same
  album folders as a full-resolution copy would be.
- **Shared albums.** iCloud Shared Albums live one level down, in
  `Photos/_Shared Albums/<sanitized name>/` (`archive_layout.SHARED_ALBUMS_DIR_NAME`),
  so a shared album never merges with a same-named user album. Their catalog
  row has `albums.kind = 'shared'` and `safe_name = '_Shared Albums/<name>'`;
  albums are upserted by `safe_name`, which keeps the two apart. No schema
  change: `albums.kind` already existed (default `'user'`), and
  `SCHEMA_VERSION` was 6 at the time (now 7, §8).
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

## 8. Catalog Schema (conceptual; see database.py for implemented version)

The following outline describes the original entities, not a migration script.
Hardening requires device-scoped, many-to-one source identities separate from
content identity. Never trust global phone-path fields for deletion or mark
another device's assets absent. Versioned transactional migrations, legacy
rescan/import handling and unknown-newer-version rejection are required before
reusing an existing catalog.

- `assets(id, sha256 UNIQUE, size, original_name, captured_at, imported_at,
  verified_at, media_type, first_seen_on_phone_at, last_seen_on_phone_at,
  present_on_phone, archive_state, phone_asset_id, phone_path, phone_size,
  phone_modified_at)` — the last four form the lightweight **phone identity**
  used for fast incremental skip; `archive_state` is `active` (in `Photos/`) or
  `deleted` (moved to `Deleted/`); `present_on_phone` and `last_seen_on_phone_at`
  track whether the asset still exists on the phone.
- `asset_files(id, asset_id, path, album_id NULL, link_mode, location)` —
  every on-disk copy of an asset; `location` is `photos` or `deleted`.
- `albums(id, phone_album_id, name, safe_name, kind)` — `kind` is `user`
  (default) or `shared` (iCloud Shared Album, §12.1); import upserts albums
  by `safe_name` (no UNIQUE constraint).
- `asset_albums(asset_id, album_id)` — many-to-many membership.
- `import_sessions(id, device_udid, started_at, finished_at, added_count,
  skipped_count, error_count)` — a session also records the scan that updates
  `present_on_phone` / `last_seen_on_phone_at`.
- `deletion_marks(id, target_type, target_id, marked_at, reason NULL,
  committed_at NULL)` — staged "mark-for-delete" items (asset, album or file copy) awaiting
  an explicit commit; supports a GUI "review before delete" workflow.
- Schema v2 adds `source_identities(device_udid, phone_path, asset_id,
  phone_asset_id, phone_size, phone_modified_at, present, last_seen_at)`, keyed
  by device/path/asset, and `import_commits(journal_id)`. Edit commit markers
  live in `meta`. Legacy asset phone fields are not trusted device provenance.
- Schemas v3-v6 add nullable/defaulted `assets` columns and v7 and v8 add a table;
  the current `SCHEMA_VERSION` is **8**. Each migration is forward-only,
  idempotent against a column that already exists, and leaves existing rows'
  new columns empty:
  - v3 `is_offloaded_preview` (0/1): the copy is the phone's cached
    low-resolution thumbnail of an offloaded original, not the original.
  - v4 `offloaded_original_path`: the album-member phone path a preview stands
    in for; cleared when the preview is upgraded (§9).
  - v5 `latitude`, `longitude` (REAL): from the phone's `Photos.sqlite`, with
    the file's EXIF GPS as fallback.
  - v6 `camera_model`, `lens_model`, `iso`, `aperture`, `focal_length_mm`:
    from the archived file's EXIF.
  These facts live only in the catalog; sidecars do not carry them yet.
- Schema v7 adds `trip_segments(scope, from_asset_id, to_asset_id, mode,
  PRIMARY KEY(scope, from_asset_id, to_asset_id))`; both asset columns
  reference `assets(id) ON DELETE CASCADE` (connections enable
  `PRAGMA foreign_keys`). The migration from v6 is the `CREATE TABLE IF NOT
  EXISTS` in the schema statements; no column changes. Travel modes for the
  trip map (§16.4).
- Schema v8 adds `trip_ignored_points(scope, asset_id, PRIMARY KEY(scope,
  asset_id))`; `asset_id` references `assets(id) ON DELETE CASCADE`. Photos
  the user left out of one view's trip map (§16.4). The migration from v7 is
  the `CREATE TABLE IF NOT EXISTS`; no column changes.
- Indexes on `assets.sha256`, `assets.present_on_phone`, `asset_albums.album_id`,
  `asset_files.path`, `deletion_marks.committed_at`.
- Location is also tracked per copy: an asset with both active and recycled
  copies remains active overall. Normal browsing uses active copy paths/counts;
  recycled browsing includes its deleted copies. Never hide or mislabel an
  active album copy because a different copy was recycled.
- For fast incremental scans, the catalog also records a lightweight **phone
  identity** per asset — `phone_asset_id` (from `Photos.sqlite` when available)
  and/or `phone_path` + `phone_size` + `phone_modified_at` — so already-imported
  items are recognized **without re-reading their bytes**.

Each asset also has a sidecar `.ibackup/sidecars/<sha256>.json` describing its
hash, size, original name, source path on the phone, capture time, and album
memberships. Current sidecars also contain `archive_state` and actual copy
paths, locations, album IDs/names and link modes; older sidecars remain readable.

## 9. Import Workflow

1. Detect and pair the device; open an AFC session.
2. Enumerate media from the AFC media domain (`/DCIM` and, best-effort,
   `PhotoData/Photos.sqlite` for album membership, capture time and GPS).
   Enumeration reads only metadata (name, size, dates, identifier), not file
   contents. Photo-database facts are keyed by exact AFC path
   (`/<ZDIRECTORY>/<ZFILENAME>`); a bare filename is used only for legacy
   schemas without `ZDIRECTORY`, and only when unique across the whole asset
   table and the USB inventory. Coordinates of `(-180, -180)` (no location)
   are ignored.
   Album members recorded in `Photos.sqlite` but absent from `/DCIM`
   (typically offloaded by "Optimize iPhone Storage") are looked up under
   `/PhotoData/Thumbnails/V2/<same path>/`; when a cached thumbnail exists it
   is enumerated as an **offloaded preview** item carrying the original's
   albums, capture time and GPS. Lookup failures leave the path missing and
   never break enumeration; a warning reports recovered vs. unrecoverable
   paths. Resolved lookups are cached per device UDID in
   `.ibackup-device-cache/offloaded-preview-cache.json` under the process
   working directory (not the archive), so later imports skip those AFC calls.
   **Shared-album items** (§12.1) are enumerated last, from
   `/PhotoData/PhotoCloudSharingData`, and only when the same `Photos.sqlite`
   copy reported shared-album membership; they carry `shared_album_names`
   plus capture time and GPS by exact path. Members not cached there fall
   back to the same thumbnail-cache preview lookup as offloaded originals
   (`/PhotoData/Thumbnails/V2/PhotoData/PhotoCloudSharingData/.../<file>/`),
   with `offloaded_original_path` set to the shared path, so step 4b upgrades
   them in place once the original is downloaded.
3. **Fast skip pass (no data transfer):** for each enumerated item, look up its
   phone identity (`phone_asset_id`, or `phone_path`+`phone_size`+
   `phone_modified_at`) in the catalog. If it matches an already-imported asset
   with a valid copy, **skip the transfer** entirely. The asset is still
   (a) backfilled: missing `latitude`/`longitude` are taken from the phone item,
   and if `camera_model` is empty the archived copy's EXIF is read locally;
   existing values are never overwritten; and (b) album-reconciled (§12).
   This keeps re-runs on large libraries fast, since unchanged items are never
   re-copied.
4. **Import pass (new/changed items only):** for each remaining candidate:
   a. Stream it from the phone into `.ibackup/tmp` while computing SHA-256.
   b. If it is a real (non-preview) item and the catalog holds an offloaded
      preview whose `offloaded_original_path` equals this phone path and that
      was imported from **this same device** (a `source_identities` row with
      this UDID; since 2026-10-23, because another or reset phone can hold an
      unrelated photo at the same `/DCIM` path), **upgrade that asset in
      place** — unless the new bytes' hash already belongs to a different
      asset, in which case the preview is kept and the item takes the
      duplicate path (step c) instead of failing on `UNIQUE(sha256)`: delete every stored file of the preview (in
      `Photos/` and `Deleted/`), rewrite the same asset
      row's content/phone identity and metadata, clear the preview flags and
      place the new copies. Asset id, album links and marks are kept; the
      result counts it in `ImportResult.upgraded_count`.
   c. If the resulting hash already exists (same content under a different phone
      identity), **skip** as a duplicate, link the identity, backfill missing
      metadata and reconcile albums (§12).
   d. Otherwise verify the staged file's hash and exclusively publish each
      destination album copy (or `_Unsorted`), recording ownership for recovery.
      Publication strategy and visibility depend on filesystem support. Read
      camera/lens/ISO/aperture/focal length (and fallback GPS) from the placed
      file's EXIF; a read failure yields empty fields, never an import error.
   e. Write the sidecar and commit the catalog rows (including phone identity).
5. Record an `import_sessions` summary (added / skipped / errors) and update
   `present_on_phone` / `last_seen_on_phone_at` for the deleted-from-phone review.
   The CLI and GUI summaries report added, skipped, duplicates, upgraded and
   errors.

Idempotent retry is a requirement. Test partial placement, sidecar/catalog
failure and recovery explicitly: SQLite transactions and atomic renames do not
form one transaction across disk and database. Ambiguous or incomplete legacy
identities may require rereading bytes; do not fast-skip a missing archive copy.
Current hardening uses per-item `.ibackup/import-journals/` and schema-v2
`import_commits` markers. Archive opening must run import recovery under its
exclusive lock; imports also recover before starting. Sidecars derive from
catalog state, including current memberships and copy metadata.
Private staging ownership is durable before media creation; bounded per-file
ownership records persist file identity before final publication. Ordinary
creation/ownership-record failures can roll back without blocking archive open.
Windows rename or POSIX hardlink publishes without overwriting; unsupported
publication fails explicitly rather than using an unsafe public-copy fallback.
Externally replaced or ambiguous recovery paths fail closed. Filesystem
power-loss guarantees vary; Windows lacks the same directory-fsync guarantee.

## 10. Duplicate Detection

- Duplicates are identified by identical SHA-256 content hash.
- `ibackup dedup` reports duplicate counts and the storage cost of
  intentional multi-album copies.
- Dedup never deletes files; it only reports.

## 11. Integrity Verification

- After every copy, the stored file is re-hashed and compared to the source
  hash before the import is committed.
- `ibackup verify` re-hashes on-disk copies (every `asset_files` row) and
  compares against the catalog, reporting any mismatches or missing files.
- `verify` checks all cataloged copies, including recycled files. There is no
  `--full` option or rolling-subset mode.

## 12. Album Preservation

- Album membership is read best-effort from the phone's `PhotoData/Photos.sqlite`
  via AFC (user albums, `ZKIND = 2`, where `ZKIND` exists; iCloud Shared
  Albums separately, §12.1), keyed by exact AFC path
  (§9 step 2). A reused filename never transfers albums between photos.
- If album data cannot be read (iOS version, pairing state, permissions),
  import still succeeds and new assets are filed under `_Unsorted/YYYY/MM/`.
- **Reconciliation with the phone (since 2026-10-10).** Every import that sees
  an already-archived asset (fast-skip or duplicate path) makes its `Photos/`
  copies match the phone item's *current* album list:
  1. add a copy for each reported album that has none (multi-album growth
     keeps every copy);
  2. if the item reports no album, add an `_Unsorted` copy when none exists;
  3. then delete each existing `Photos/` copy whose album (or `_Unsorted`) is
     no longer reported — its file, its `asset_files` row and its
     `asset_albums` link.
  New copies are created before stale ones are removed. A stale copy's file
  is only *retired* in the item's import journal (path + file identity); it
  is deleted after the item's catalog commit, by the post-commit recovery
  pass (or by the next import's recovery after a crash). An item that rolls
  back therefore keeps its old copy, and an interrupted reconciliation never
  leaves the asset without a valid copy (fixed 2026-10-23; before that a
  failure after reconciliation, e.g. a sidecar write error, could delete the
  only copy). The old file(s) of an upgraded offloaded preview (§9 step 4b)
  are retired the same way. `Deleted/`
  copies are never touched, and assets not enumerated in this import (e.g.
  deleted from the phone) keep their placement.
- Consequences: an archive-side `move` of an asset still on the phone is
  reverted by the next import when the phone's albums differ; the phone's
  albums win. Earlier wrong (filename-matched) album copies are corrected
  the same way.
- **Known limitation:** when `Photos.sqlite` is unavailable for a whole import
  (logged as "Photos metadata unavailable"), every item reports no albums, so
  reconciliation moves the album copies of still-present assets into
  `_Unsorted`. No asset loses its last copy, and the next import with readable
  metadata restores the album copies, but the folder churn is real. A guard
  that skips reconciliation when membership could not be read is not
  implemented. Shared-album items are simply not enumerated in that case, so
  their archived copies are left where they are.

### 12.1 iCloud Shared Albums (2026-10-11)

- **Source (iOS 26+, hardware-validated 2026-10-11).** Shared albums are rows
  of `ZSHARE` (Core Data entity `CollectionShare`, `Z_ENT` 67 and
  `ZCOLLECTIONSHAREKIND = 2` on the test phone) with a `ZTITLE`; their media
  link via `ZASSET.ZCOLLECTIONSHARE -> ZSHARE.Z_PK`, **not** through the
  `Z_nnASSETS` album join. `ZSHARE.ZSCOPEIDENTIFIER` is the GUID folder name in
  `/PhotoData/PhotoCloudSharingData/<personId>/<GUID>/100CLOUD/`.
  `albums_collection_share_query()` requires `ZASSET.ZCOLLECTIONSHARE`,
  `ZSHARE.ZTITLE` and `ZASSET.ZDIRECTORY`, and skips trashed shares and
  trashed assets (`ZTRASHEDSTATE`).
- **Source (older iOS, unvalidated fallback).** `ZGENERICALBUM` rows with
  `ZKIND = 1505` (`SHARED_ALBUM_KIND`) read through the runtime-discovered
  `Z_nnASSETS` join: `albums_membership_query(connection, kind)` /
  `albums_parse_photos_database(path, kind)` take a `kind`
  (`USER_ALBUM_KIND = 2` by default, unchanged); schemas without `ZKIND` yield
  none. The iOS 26.4 phone has **no** `ZKIND = 1505` row (kinds seen: 2, 1506,
  1510, 16xx, 35xx, 39xx, 400x), so this path found nothing there.
- `albums_parse_shared_albums()` merges both sources and keeps only keys under
  `/PhotoData/PhotoCloudSharingData` (`SHARED_MEDIA_ROOT`,
  `albums_is_shared_path`).
- **Device.** `AfcDevice` parses shared membership from the same
  `Photos.sqlite` copy (no second transfer) into `shared_album_membership`.
  `afc_device_shared_items()` walks `SHARED_MEDIA_ROOT` only when that
  membership is non-empty and yields only files the database names as
  shared-album members, so cache-internal files are never imported and an
  unreadable database imports no shared media (never `_Unsorted`). A walk
  failure logs "shared albums unavailable" and yields no shared items (not
  even previews); enumeration continues. Members not cached on the phone go
  through `afc_device_offloaded_preview()`: the thumbnail under
  `/PhotoData/Thumbnails/V2<shared path>/` (e.g. `5005.JPG`) becomes an item
  with `is_offloaded_preview = True` and `offloaded_original_path` = the shared
  path, named `<stem> (offloaded preview).<ext>`, using the on-disk preview
  cache; it is upgraded in place (§9 step 4b) once the original is cached.
  Every enumeration with shared membership logs a WARNING summary: "Shared
  albums: N albums, M items; X full-resolution copies cached on the phone, Y
  imported as low-resolution previews, Z unavailable. Open a shared album in
  Photos to download its originals, then import again." Shared items are not
  part of `device_album_map()`. `PhoneItem.shared_album_names` carries
  membership, separate from `album_names`; `FakeDevice(shared_album_map=...)`
  mirrors it.
- **Placement.** `importer_album_targets(item)` returns `(name, kind)` pairs:
  user albums first (so the primary copy keeps its place), then shared
  albums, de-duplicated. The primary copy goes to the first target; extra
  copies and §12 reconciliation treat shared membership like any other
  album, so leaving a shared album (or its removal of a photo) removes that
  copy on the next import, never the asset's last copy.
- **Identity.** Shared-album files are iCloud's re-encoded copies, so they
  are separate assets from the owner's `/DCIM` originals (different bytes and
  SHA-256). A photo in both a user album and a shared album gets a copy in
  each.
- **Move-to-album** (`service/selection.py`): when a user album and a shared
  album share a name, the user album is chosen; a name that exists only as a
  shared album still resolves to it.
- **Listing.** `AlbumSummary.kind` (`"user"` default, or `"shared"`) is
  returned by `albums_list`. `ibackup albums` appends `  (shared)`;
  `ibackup albums --shared` lists only shared albums ("No shared albums
  yet." when none). The GUI lists them in a separate "Shared albums"
  navigation section (§16.2).
- **Presence.** Shared-album items absent from an enumeration (no original
  or thumbnail, album left, or membership unreadable) count as not seen, like any
  phone item, so they can appear in the deleted-from-phone review (§18).
- **Hardware validation (iPhone 12, iOS 26.4, 2026-10-11).** Diagnosed from a
  copy of the phone's `Photos.sqlite`: 18 shared albums and 6,150 items are
  found (e.g. "India 2024", 1,473 items). Only a small fraction is cached
  (13 of 1,473 files in that album's `100CLOUD` folder), but 35 of 35 sampled
  items had a thumbnail, so most shared media is imported as previews until
  the user opens the album in Photos. Still unverified: a full end-to-end
  import run, whether shared copies' bytes differ from the owner's DCIM
  originals, and the older `ZKIND = 1505` schema. The album owner is not
  captured (`ZSHARE` showed no owner-name column; possibly via
  `ZSHAREPARTICIPANT`, unverified). Access is still local USB/AFC, with no
  iCloud login or network.
## 13. Space Reclamation (Safety Model)

- A phone-side file is eligible only with a freshly verified active archive
  copy and a current device-scoped source identity/content match. Recycled-only
  copies, stale metadata and historical verification are insufficient.
- `ibackup reclaim` previews candidates without deletion; there is no
  `--dry-run` flag. Repeated `--asset <id>` narrows the selection.
  `--device <UDID>` selects the source device.
- `reclaim_find_candidates` never offers files under
  `/PhotoData/PhotoCloudSharingData`: a shared-album copy is iCloud's cache,
  not the user's library, so deleting it frees nothing durable and would
  alter the shared album. It also never offers low-resolution previews
  (`is_offloaded_preview`, phone paths under `/PhotoData/Thumbnails/V2/`):
  those are the phone's thumbnail cache, never the original.
- `ibackup reclaim --confirm` requires interactive typed `DELETE`, with no
  automation bypass, and execution-time candidate revalidation.
- Real AFC deletion stays disabled until the Windows/iPhone read, album,
  large-video and separately controlled destructive-recovery matrix passes
  (`unit-tests.md` §4). Confirmation does not override this gate.
- Rechecking content does not eliminate a hash-to-unlink race. AFC removal and
  phone Photos database consistency must be evaluated on hardware rather than
  describing verification alone as proof of safe phone deletion.
- Deletion never runs automatically and never touches archive files.

## 14. Error Handling & Logging

- The CLI emits a rotating archive command start/completion/error log under
  `.ibackup/logs/`, using `log_level`, and closes its handler at command end.
  Structured per-asset immutable audit logging remains future work.
- Errors on individual assets are recorded and counted; a failing asset does not
  abort the whole import.
- Catalog transactions must be paired with recoverable filesystem/sidecar
  changes; failure-injection tests define the supported recovery boundary.

## 15. Constraints & Assumptions

- Requires a trusted (paired) USB connection to an unlocked iPhone.
- Requires the **Apple Mobile Device USB driver** on Windows (installed by
  Apple's iTunes or "Apple Devices" app).
- Album extraction depends on AFC access to `Photos.sqlite`, which is not
  guaranteed on all iOS versions. Shared albums additionally depend on AFC
  access to `/PhotoData/PhotoCloudSharingData` (full resolution) or to its
  thumbnail mirror under `/PhotoData/Thumbnails/V2` (previews); both read
  correctly on iOS 26.4 (§12.1).
- GPS is read from `ZLATITUDE`/`ZLONGITUDE` on the `ZASSET`/`ZGENERICASSET`
  table only; an iOS version storing location elsewhere yields no phone GPS
  (EXIF GPS may still fill it). A backfill on one real iOS 26.4 archive found
  GPS for 5,396 of 6,641 assets (`progress.md`); other iOS versions are
  unqualified.
- Offloaded previews depend on iOS keeping `/PhotoData/Thumbnails/V2`
  path-mirrored thumbnails; confirmed on iOS 26.4 only. USB/AFC cannot make
  the phone download an iCloud original.
- The trip map requires Qt WebEngine (part of PySide6) and network access to
  `tile.openstreetmap.org` for imagery, under OpenStreetMap's tile usage policy.
- Recommended archive filesystems: **NTFS** (supports hardlinks) or **exFAT**
  (copy mode) for large external drives.

## 16. Frontend Architecture (CLI + GUI)

The application specifies **two first-class frontends** over one
headless core; full parity is an acceptance requirement, enforced by
`tests/test_gui_parity.py` against `gui/parity.py`:

- A headless **service/application layer** exposes every capability (import,
  verify, dedup, album browsing/query, selection, move, delete, mark-for-delete,
  reclaim) as UI-agnostic operations that return structured result objects.
- The **CLI** (`ibackup`) and the **GUI** (`ibackup-gui`) are **both thin
  adapters** over this layer; acceptance tests must establish that the GUI can
  perform every CLI operation and expose matching operation semantics.
- Long-running operations (`import`, `verify`, `reclaim`) report **progress** and
  support **cancellation** through a small handle; the CLI shows a progress line
  and the GUI a progress dialog with a cancel button.
- Read/query operations return data suitable for a GUI (album summaries, asset
  records including on-disk paths usable for thumbnails, paginated listings).

### 16.1 GUI framework and packaging

- **Framework:** PySide6 (Qt for Python), LGPL. Chosen for efficient thumbnail
  grids, built-in multi-selection, context menus/drag-and-drop, and Qt threading
  for responsive long operations. (Keeping the GUI in Python preserves the whole
  Python core, including `pymobiledevice3` device access. WinUI/C# could bridge
  Python via IPC/embedding, but adds a second runtime/toolchain; no rewrite is
  inherently required. See ADR-0011.)
- **Packaging target:** a future distribution provides `ibackup` and
  `ibackup-gui`. `packaging/ibackup.spec` freezes the GUI (one-directory,
  including the vendored Leaflet `webassets/`); a CLI recipe, signing, an
  installer and release validation remain a scheduled milestone. Source
  installation provides both entry points; no release is available.
- **GUI keeps no business logic:** all actions call `service/`; the GUI only
  binds widgets, renders result DTOs, and forwards progress/cancel.
- **Worker ownership:** create/open/use/close each service and SQLite connection
  in its owning worker thread, never share across QThreads. The OS-exclusive
  archive lock permits one service session, including reads, and rejects busy
  sessions rather than queueing. Cancellation uses `threading.Event`; queued
  Qt signals carry progress/results to widgets. Bound thumbnail workers,
  pending queues and caches; paginate library metadata.
  Current progress snapshots retain only the last 256 events.

### 16.2 GUI capabilities (must match the CLI)

- Browse pictures as a thumbnail grid; browse albums (including `_Unsorted`),
  with iCloud Shared Albums in their own "Shared albums" navigation section
  (`shared-album` glyph, tooltip "(iCloud Shared Album)").
- Multi-select pictures (Ctrl/Shift/rubber-band) for batch actions.
- Move selected pictures between albums.
- Delete, or mark-for-delete, individual pictures and whole albums; staged marks
  require an explicit commit before anything is removed.
- View which phone assets are safe to delete (archived + verified) and run the
  reclaim workflow with confirmation.
- **Review assets that were deleted from the phone** and decide, per item, to
  purge them from the archive or move them to the `Deleted/` folder (see §18).
- Run import/verify/dedup with visible progress and cancellation.
- Show a trip map of the located photos of any gallery view (§16.4).

### 16.3 UI sketch approval gate (required before building the GUI)

Before any GUI code is written, a **UI sketch / wireframe** of the main window
and key views (album navigation, picture grid with multi-select, deleted-on-phone
review, reclaim, progress dialog) is produced and saved under `docs/ui-sketch/`.
Implementation of the PySide6 GUI **must not begin until the user explicitly
approves the sketch**. This is a hard gate in the build plan. _(Passed
2026-09-11.)_

The sketch also fixes the **visual language: a modern Windows 11 Fluent
application** — Qt's native `windows11` style, DWM Mica backdrop, rounded
corners, system dark mode and accent color, the WinUI type ramp and color
tokens, and a NavigationView + command bar layout with **no classic menu bar**.
No GPL widget dependency is selected for this distribution. DWM failures must
be logged and fall back to solid colors. The Windows Mica probe is unperformed
and remains behind approval. See `ui-sketch/README.md` §0 and ADR-0010/0011.

### 16.4 Trip map (GUI only)

- `app_service_list_locations(album_id=None, only_unsorted=False,
  include_deleted=False)` → `gallery_list_located()` returns `AssetView`s with
  non-null `latitude`/`longitude` for one scope (album, unsorted, recycled or
  all active), ordered by `captured_at` (oldest first), then name and id.
- `gui/mapview.py` `MapDialog`/`WebMapWidget` embed a `QWebEngineView` whose
  page is generated locally: vendored Leaflet (`gui/webassets/leaflet/`,
  BSD-2-Clause) and the point list (label, capture time, note) are inlined,
  escaped so they cannot close the script tag; with no points it shows a
  world view. With points the page draws (enhanced 2026-10-12):
  - the trip in capture order (oldest first, from `gallery_list_located`),
    drawn since the travel-mode change as one polyline per leg styled by its
    mode (untagged: blue solid), on a Leaflet canvas renderer
    (`preferCanvas`) so thousands of legs stay fast; circle markers (first
    green, last red, larger) and a metric/imperial scale, fitted to the bounds;
  - labelled `divIcon` pins: **Start** (green, above its point) and **End**
    (red, below it, so a round trip shows both); a single point shows
    **Start / End**. Clicking a pin opens its point's popup;
  - one direction arrow per segment at the segment midpoint, rotated to the
    travel direction. The angle is computed once in Web Mercator
    (`EPSG:3857`), which is conformal, so it holds at every zoom level.
    Zero-length segments (consecutive photos at the same spot) get none;
    arrows are shown only for segments ≥ 40 px on screen and refreshed on
    `zoomend`. An arrow takes its leg's mode colour and an emoji badge;
  - a popup per point: picture, file name, capture time (`YYYY-MM-DD HH:MM`,
    the first 16 characters of the stored `captured_at`, no time-zone
    conversion), "n of N", and a note: "Low-resolution preview (original not
    on the phone)" when the name carries the `" (offloaded preview)"` marker
    (offloaded and shared-album previews), else "Video (poster frame)" for
    videos. Popup elements are built once per point and cached, because
    Leaflet re-runs content functions on `update()`.
- **Popup pictures** are rendered from the asset's first **archived** copy
  (for a preview that copy is the phone's own thumbnail) with
  `browse.thumbnails.thumbnails_get` at 320 px, which also fills the normal
  `.ibackup/thumbnails/` cache, on a 2-thread `QThreadPool` off the GUI
  thread, and pushed into the page as a `data:image/jpeg;base64,…` URI via
  `runJavaScript`. Nothing is fetched from the phone and the page gets no
  file access. The request channel is a console message
  `ibackup-photo:<index>`, intercepted by `MapPage`
  (`QWebEnginePage.javaScriptConsoleMessage`); `mapview_parse_request`
  accepts only in-range numeric indices, and each point is rendered at most
  once per plot, then cached in the page. Without an open archive the popup
  says "No archive open"; without a stored copy "No archived copy"; on a
  render failure "No preview available (…)".
- `MapDialog` opens at 900×640, deletes itself on close and waits for
  in-flight renders (`mapview_shutdown`). Caption: "N located photos, plotted
  in capture order from Start to End. Click a point to see its photo, or a
  line to set how you travelled." The window passes `archive_root` from the
  worker.
- **Travel modes (2026-10-12).** The user can tag each leg (two consecutive
  plotted photos) with one of `core/trip.py` `TRIP_MODES`: `car`, `plane`,
  `foot`, `bike`, `tuktuk`, `bus`, `taxi`, `boat`. `mapview.MODE_STYLES` gives
  each a label, emoji, colour and dash: Car 🚗, Plane ✈️ (dashed), On foot 🚶
  (dotted), Bike 🚲, Tuk-tuk 🛺, Bus 🚌, Taxi 🚕 (dashed), Boat ⛴️ (dashed).
  - **Editing.** A wide invisible twin line makes each leg easy to click; its
    hover tooltip is "<emoji> <label> · Click to set how you travelled".
    Clicking opens "How did you travel from photo n to n+1?" with a 3-column
    grid of mode buttons plus **Clear**, the current mode highlighted.
    Choosing restyles the leg at once and logs the console message
    `ibackup-mode:<leg>:<mode|none>`; `MapPage` forwards it,
    `mapview_parse_mode_change` accepts only known modes and legs
    `0..count-2`, and `WebMapWidget.mode_changed(from_asset_id, to_asset_id,
    mode)` reaches `MapDialog`'s `on_mode_changed`, which the window wires to
    `app_service_set_trip_mode`. Zero-length legs are not drawn and cannot be
    tagged. `mapview_points(assets, segments)` sets `MapPoint.mode` (the mode
    of the leg starting at that point) only for the exact consecutive pair.
  - **Storage.** Catalog table `trip_segments` (§8), one row per
    `(scope, from_asset_id, to_asset_id)`. `scope` is the map's navigation
    view key — `all`, `unsorted`, `recycled` or `album:<id>` — so modes are
    per view: the same pair can differ between albums. `trip_set_mode`
    validates the scope (non-empty, ≤ 64 characters), distinct positive ids,
    a known mode and that both assets exist; it does not check that the pair
    is currently consecutive. `None` deletes the row.
  - **Reconciliation** (`trip_reconcile`, run every time a map with ≥ 2
    located photos opens, against the exact plotted capture-ordered asset
    ids, then committed; rolled back on error): a stored pair still
    consecutive keeps its mode; a stored pair whose photos are both still
    present and in order but no longer adjacent (photos inserted between) is
    deleted, and every leg it now spans inherits its mode unless that leg
    already has its own; a pair with a photo gone (purged, recycled, moved
    out of the album, lost its location) or in reversed order is deleted, so
    the joined leg starts untagged and the mode does not return if the photo
    comes back. Purging an asset also deletes its rows by `ON DELETE
    CASCADE`. An offloaded preview upgraded in place keeps its asset id and
    therefore its modes.
  - **Service.** `app_service_trip_modes(scope, asset_ids)` →
    `list[TripSegment]` and `app_service_set_trip_mode(scope, from_asset_id,
    to_asset_id, mode | None)` → `TripSegment | None`, both committing and
    rolling back on error. GUI-only (no CLI command), declared in
    `gui/parity.py`. Window flow: **Map** → `app_service_list_locations` →
    (≥ 2 located) `app_service_trip_modes` → `MapDialog(segments=…,
    on_mode_changed=…)`; if reading modes fails or is cancelled, the map
    opens without them. Status lines: "Map ready: N legs have a travel
    mode.", "Travel mode saved.", "Travel mode cleared.".
  - Travel modes live only in the catalog; sidecars do not carry them.
  - **Persistence across imports.** Rows are keyed by catalog `assets.id`,
    and an asset is identified by the SHA-256 of its content (`assets.sha256`
    UNIQUE): an import fast-skips a known phone identity or dedups by hash
    onto the existing row, so re-importing the same photos (any device) never
    creates new ids and every mode survives. An offloaded preview upgraded to
    its original keeps its id (`importer_upgrade_offloaded_preview`); album
    rows keep their id (upsert by `safe_name`), so `album:<id>` scopes are
    stable. Newly imported photos inside a tagged leg split it (reconciliation
    above). Identity is lost, and modes start empty, only when the bytes
    differ: a phone-side edit that changes the file, or a shared-album
    original evicted from the phone and re-imported as a thumbnail preview at
    another path. The phone's own stable id (`Photos.sqlite` `ZASSET.ZUUID`)
    is not captured; `assets.phone_asset_id` stays NULL. Covered by
    `tests/test_trip.py` (re-import, insertion by import, preview upgrade,
    album scope).
- **Ignored points and Previous/Next (2026-10-16).**
  - **Ignoring.** The point popup has **Ignore this point** / **Include this
    point**. An ignored point stays on the map, greyed (grey dashed dot), but
    is not part of the trip: legs, direction arrows and the Start/End pins
    are drawn from the other points only, and no line joins the neighbours
    of an ignored point (the line is simply broken there). The page logs `ibackup-ignore:<index>:<0|1>`;
    `MapPage.ignore_changed` forwards it, `mapview_parse_ignore_change`
    accepts only in-range indices and `0`/`1`, and
    `WebMapWidget.ignore_changed(asset_id, ignored)` reaches `MapDialog`'s
    `on_point_ignored`, which the window wires to
    `app_service_set_trip_ignored`. `MapPoint.ignored` and
    `mapview_points(assets, segments, ignored)` carry the saved state in;
    the caption appends "(N ignored)".
  - **Modes across ignored points.** Ignoring never changes `trip_segments`
    and reconciliation still runs on every located photo. Only legs between
    adjacent photos are drawn, so every drawn leg is one saved pair and the
    modes around an ignored point are kept untouched.
  - **Storage and service.** `trip_ignored_points` (§8), per view `scope`
    (same keys as modes). `trip_set_ignored` validates scope, a positive id,
    a real `bool` and that the asset exists; `trip_ignored` returns the
    ignored ids among the plotted ones. `app_service_trip_ignored(scope,
    asset_ids)` → `list[int]` and `app_service_set_trip_ignored(scope,
    asset_id, ignored)` → `bool`, committing and rolling back on error;
    GUI-only, declared in `gui/parity.py`. Window flow: **Map** →
    `app_service_list_locations` → (≥ 2 located) `app_service_trip_modes` →
    `app_service_trip_ignored` → `MapDialog(segments=…, ignored=…)`; if
    either read fails the map opens with what was read. Status lines: "Map
    ready: N points are ignored.", "Point ignored on this map.", "Point
    included on this map again.".
  - **Previous / Next.** `WebMapWidget` has **Previous point** / **Next
    point** buttons above the map. They call the page's `mapStep(±1)`, which
    pans to the next/previous point that is not ignored (in capture order,
    wrapping at the ends) and opens its popup; with no popup yet, Next goes to
    the first and Previous to the last point. The page tracks the last opened
    point in `current`, so stepping continues from it even after it is
    ignored. Both buttons are disabled when no point is left to visit.
- Tiles come from `https://tile.openstreetmap.org/{z}/{x}/{y}.png` (max zoom
  19, © OpenStreetMap contributors attribution) through one named, persistent
  `QWebEngineProfile` `ibackup-map-tiles` with a 200 MB disk HTTP cache and a
  descriptive User-Agent. This is the app's only network use. Offline, the
  map controls, markers, line, pins, arrows and photo popups still work
  without imagery.
- The **Map** button is shown on gallery-backed pages only (All photos,
  Unsorted, Recycle bin, each album) while an archive is open; the Marked and
  Deleted-from-phone review pages have none. There is no CLI equivalent; the
  operation is declared in `gui/parity.py`.
- "Trip" means located photos in capture order; there is no automatic
  segmentation into separate trips.

## 17. Archive Editing: Move, Delete, and Mark-for-Delete

These are **explicit, user-initiated** operations, distinct from the append-only
*automatic* guarantee (the app never deletes an asset on its own; import's
album reconciliation in §12 only removes redundant placement copies):

- **Mark-for-delete:** the user may mark individual pictures or whole albums for
  deletion. Marks are staged in `deletion_marks` and change nothing on disk until
  the user explicitly commits them. Marks can be listed and un-marked.
  `marks add <file-id> --file` scopes intent to one copy; `--file` and `--album`
  are mutually exclusive. `list --files` exposes copy IDs with paths filtered
  by the current album/location. Committing a file mark must preserve other
  copies and album memberships.
- **Delete (commit):** committing marked items (or a direct delete request)
  removes the selected archive files after an explicit confirmation. Deleting an
  album removes that album folder's copies; a picture that also lives in other
  albums remains in those other albums.
- **Move:** the user may move selected pictures between albums (i.e. change album
  membership / folder placement). Moves preserve bytes and require recoverable
  per-asset placement/catalog changes; do not imply whole-batch atomicity.
  CLI moves default to all active copies of selected assets; `--from-album`
  limits changes to one source album. A move of an asset still on the phone
  lasts only until the next import if the phone's albums differ (§12).
- **Exact copy selection:** move/recycle/restore/purge service calls accept
  `file_ids`; corresponding CLI commands accept repeated `--file <id>` and
  still require positional asset IDs. IDs must match the requested assets and
  source location/album; mismatches fail instead of broadening the action.
- **Batch/selection:** move, delete, and mark operations accept **multiple
  selected items** at once, supporting a GUI multi-select workflow.
- **Safety:** these operations never touch the phone. The separate `reclaim`
  workflow is the only path that deletes phone-side files, and only for archived
  + verified assets on explicit confirmation.
- **Recovery/resources:** immutable edit intent owns private staging before
  file creation; bounded per-file identity records precede publication.
  Journal metadata writes scale linearly with selection size, not one full
  batch rewrite per copy. Originals remain until the SQLite operation marker and file/mark rows
  commit; recovery rolls back precommit work or finishes committed cleanup and
  sidecars. Purge uses staged copies too, so allow temporary extra disk space.
  Recovery requires recorded source/destination identity as well as content:
  ambiguous, unowned or replaced files fail closed, including byte-identical
  replacements. Ordinary staging creation/claim-write interruptions roll back;
  external interference or changed content can still require investigation.
  This design still requires Windows and failure-boundary validation.

## 18. Review of Assets Deleted from the Phone

This workflow lets the user see which archived pictures/videos **no longer exist
on the phone** and decide, per item, what to do with the archived copy. It never
deletes anything automatically; the archive stays the source of truth.

### 18.1 Detection

- On each import/scan the app records, for every catalog asset, whether it was
  seen on the selected device this session. Publish absence only after a
  complete successful inventory; failure/cancellation must preserve prior state.
- An asset is considered **deleted from the phone** when it exists in the catalog
  with `archive_state = active` but was **not** seen in the latest complete scan
  of the same device. Unknown/legacy identity is not evidence of deletion.
- Matching an archived asset to a phone asset is done by **content hash**
  (reliable) and, when available, the phone asset identifier. Hash matching
  uses device-scoped identities for metadata-only inventory reconciliation.
  A stored content hash is not proof of current phone bytes; changed/ambiguous
  identities need renewed content checks before destructive use.
- Detection is **read-only**: it changes no files.

### 18.2 Presentation

- `deleted-on-phone list` (CLI) and a dedicated GUI view show the assets that are
  in the archive but gone from the phone, with thumbnails, album, and the date
  last seen on the phone.
- `deleted-on-phone list --device <UDID>` scopes the report to one device and,
  with `--rescan`, selects that device for the inventory refresh.
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
  explicitly-confirmed product requirement; today select asset IDs for purge.
  `deleted-on-phone purge <ids...> --recycled-only --confirm` removes only
  their Deleted copies and preserves any active Photos copies. Without
  `--recycled-only`, asset-ID purge remains asset-wide.
- Permanent purge and `marks commit --purge --confirm` require interactive
  typed `DELETE`, never a configurable bypass. Reversible marks commit uses
  its explicit `--confirm` flag; direct recycle/restore remain explicit actions.
- This workflow only ever affects the **archive**; it never deletes from the
  phone (that is the separate `reclaim` workflow).

## 19. Performance & Scalability

The target is large libraries (tens of thousands of items, tens to hundreds
of GB). The following are hypotheses for benchmark design, **not measured
hardware performance or service guarantees**.

### 19.1 What dominates the time

- USB/AFC transfer may dominate a first import, but source hashing, archive
  verification rereads, destination speed, album copies, antivirus and metadata
  extraction can also dominate. Measure each phase rather than assume CPU and
  SQLite costs are negligible.
- Connector type alone does not establish effective throughput. Record phone
  model, USB mode/cable, Windows driver, AFC version and destination filesystem.

### 19.2 Illustrative transfer-only calculation

For a hypothetical constant 30 MB/s, the **transfer-only lower bounds** below
exclude verification, album copies and metadata work:

| Example library | Decimal data | Transfer-only estimate |
|---|---|---|
| Mostly photos | 30 GB | ~17 min |
| Photos and videos | 80 GB | ~44 min |
| Video-heavy library | 200 GB | ~111 min |

These arithmetic examples are not predicted completion times. Retry,
verification and multi-album storage can increase elapsed time substantially.

### 19.2b Measured on real hardware (2026-09-10)

First measurements from a physical device — iPhone 12 (iPhone13,2), iOS 26.4,
1297 items, 5.55 GB, USB, Linux host:

| Phase | Measurement |
|---|---|
| Enumeration + album metadata | **~36 s, fixed** (independent of new content) |
| Sustained read + SHA-256, large files | **~34 MB/s** |
| Import of 40 mixed items (77.5 MB) | 44 s total, of which ~36 s was enumeration |
| Re-run with nothing new | 39 s, **0 bytes retransferred** |

Two consequences worth designing around:

- The ~34 MB/s figure makes the §19.2 arithmetic examples roughly realistic for
  large files, but small photos transfer slower because per-file AFC overhead
  dominates.
- The **fixed ~36 s cost is mostly copying the phone's 1 GB `Photos.sqlite`** to
  read album membership, and it is paid even when nothing needs importing. For
  frequent incremental runs this is the dominant cost, not the media transfer.
  Caching or conditionally skipping that copy is the highest-value optimisation.
- Offloaded-preview lookups cost two AFC round-trips (`listdir` + `stat`) per
  album path missing from `/DCIM`; with 5,263 such paths (2026-10-09 run) that
  is ~10,500 calls. Resolved paths are therefore cached per device
  (§9 step 2), so only never-resolved paths cost AFC calls on later imports.
  The `Photos.sqlite` copy is still uncached.

### 19.3 Incremental-run behaviour (confirmed)

- Subsequent imports use the **fast skip pass** (§9 step 3): the phone inventory
  is enumerated (metadata only) and matched against stored **phone identity**, so
  unchanged, trusted identities can avoid retransfers. Missing archive copies,
  migrations and ambiguous/changed identities require renewed validation.
- Time includes enumeration of the whole library plus checks and new content
  transfer. There is no established "30,000 items under a minute" result.
- **Confirmed on hardware:** a second import of an unchanged selection reported
  `added=0, skipped=40` and moved no media bytes, so the fast-skip pass works
  against a real Photos library.

### 19.4 Catalog, memory, and detection

- **Catalog:** indexed lookups are intended to scale to large libraries.
  Benchmark actual query plans, transactions and pagination; row count alone
  does not establish responsiveness.
- **Memory:** file copying/hashing should use bounded chunks, independent of
  individual video size. Inventories, album databases, sets, query results and
  caches can still grow with library metadata; total process memory is not
  independent of library size. Measure peak RSS on a representative library.
- **Deleted-from-phone detection** (§18) is a set-difference between the phone
  inventory and the catalog — metadata only, no content reads.
- **Metadata backfill** (§9 step 3) reads one archived copy's EXIF locally for
  each enumerated asset whose `camera_model` is still empty, on every import.
  Once filled it costs nothing, but assets with no EXIF camera data (e.g.
  videos, screenshots) are re-read on each import.

### 19.5 GUI at scale

- The picture grid uses delegate-painted, lazily paged rendering (128-row
  pages); smooth scrolling at scale still needs measurement on Windows.
- Thumbnails are **generated once and cached** under `.ibackup/thumbnails/`
  (HEIC decoded via `pillow-heif`), so browsing does not re-decode originals.
- Background generation bounds pending queues, worker count and decoded
  caches, discards stale requests and supports cancellation
  (`gui/previews.py`).

### 19.6 Tunables

- Chunk sizes are implementation parameters, not advertised CLI settings.
  Background thumbnail worker settings are future GUI design, not implemented
  user preferences.
- `--album-link-mode hardlink` avoids duplicating bytes for multi-album assets on
  NTFS, reducing both time and space for heavily-albumed libraries.
