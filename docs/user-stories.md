# iPhone Archive — User Stories

Status: living requirements and acceptance criteria, not a passed-test report.
Core/CLI exists but is undergoing hardening; GUI stories are blocked on explicit
sketch approval. Hardware/release validation is pending (`unit-tests.md`).

Format: each story has an ID, a role/goal/benefit statement, and acceptance
criteria (Given/When/Then). "The archive" refers to the local append-only store.

---

## Epic A — Setup & Device Connection

### US-A1 — Initialize an archive
**As** a user, **I want** to create a new archive at a location I choose **so
that** all my imports have a permanent home.

Acceptance criteria:
- Given a writable target path, when I run `ibackup init <path>`, then a
  `Photos/` folder and a hidden `.ibackup/` folder with an empty catalog are
  created.
- Given a path that already contains an archive, when I run `init`, then the
  existing archive is detected and not overwritten.

### US-A2 — Detect the connected iPhone
**As** a user, **I want** to confirm my iPhone is connected and trusted **so
that** I know I can import.

Acceptance criteria:
- Given a trusted, unlocked iPhone over USB, when I run `device-info`, then its
  device identifier (UDID) and full enumerated media count are shown via the
  service. Name/model/iOS-version reporting is not currently implemented.
- Given no device or an untrusted device, when I run `device-info`, then a clear
  message explains how to connect/trust the phone.

---

## Epic B — Import & Preservation

### US-B1 — Import photos and videos
**As** a user, **I want** to import all photos and videos from the phone **so
that** they are safely archived.

Acceptance criteria:
- Given a connected phone, when I run `import`, then every photo/video is copied
  byte-for-byte into the archive.
- Given the import completes, then a summary shows counts of added, skipped, and
  errored items.

### US-B2 — Incremental import
**As** a user, **I want** re-running import to copy only new items **so that**
repeated backups are fast and don't duplicate work.

Acceptance criteria:
- Given assets already in the archive, when I run `import` again, then those
  assets are skipped (identified by content hash).
- Given new assets on the phone, when I run `import` again, then only the new
  assets are copied.

### US-B3 — Originals are never modified
**As** a user, **I want** my files preserved exactly **so that** the archive is
a faithful copy.

Acceptance criteria:
- Given an imported asset, then its content hash equals the source hash.
- Given any import, then no re-encoding, resizing, or metadata rewriting occurs.

### US-B4 — Phone deletions never affect the archive
**As** a user, **I want** archived items to persist **so that** deleting on the
phone is safe.

Acceptance criteria:
- Given an asset in the archive, when it is deleted from the phone, then it
  remains in the archive on the next import.
- Given any operation, then the app never deletes archive files automatically.

---

## Epic C — Integrity & Duplicates

### US-C1 — Verify integrity after import
**As** a user, **I want** each imported file verified **so that** I trust the
backup.

Acceptance criteria:
- Given an asset is copied, when it is committed, then its stored copy is
  re-hashed and must match before commit.
- Given a mismatch, then the asset is not committed and the error is reported.

### US-C2 — Verify the whole archive on demand
**As** a user, **I want** to re-check the archive later **so that** I can detect
bit rot or accidental changes.

Acceptance criteria:
- Given an archive, when I run `verify`, then every on-disk copy is re-hashed and
  compared to the catalog.
- Given a corrupted or missing file, then it is reported with its path.

### US-C3 — See duplicates and storage cost
**As** a user, **I want** a duplicate report **so that** I understand storage
usage, including multi-album copies.

Acceptance criteria:
- Given an archive, when I run `dedup`, then duplicate counts and the
  storage cost of intentional multi-album copies are shown.
- Given the report, then no files are deleted.

---

## Epic D — Albums & App-Free Browsing

### US-D1 — Preserve albums
**As** a user, **I want** my albums preserved **so that** the archive mirrors my
organization.

Acceptance criteria:
- Given album data is available on the phone, when I import, then each asset is
  placed in a folder named after each album it belongs to.
- Given album data is unavailable, then assets are placed under
  `_Unsorted/YYYY/MM/` and the import still succeeds.

### US-D2 — Browse by album without the app
**As** a user, **I want** to open album folders directly **so that** I don't
need this app to view my photos.

Acceptance criteria:
- Given an archive, when I open `Photos/<Album>/` in any file manager, then I see
  the real media files for that album.
- Given the archive, then no symlinks are used and files open directly.

### US-D3 — Access the archive on Windows
**As** a user, **I want** the archive to work on Windows **so that** I can view
it on any computer.

Acceptance criteria:
- Given the archive is opened on Windows, then all album and file names are valid
  (no reserved characters/names, path length within limits).
- Given a name collision or reserved name, then the app produces a safe,
  unique name.

### US-D4 — Optional HTML gallery
**Deferred, not implemented or scheduled for the current checkpoint.**
`browse/gallery.py` provides read models only; no `gallery` command exists.

**As** a user, **I want** an optional gallery page **so that** I can browse an
album visually in a browser.

Acceptance criteria:
- Given an album, when I run `gallery <album>`, then a static `index.html` is
  generated that references the archived files.
- Given no such command is run, then browsing still works via plain folders.

---

## Epic E — Space Reclamation

### US-E1 — Preview what can be freed
**As** a user, **I want** a dry run **so that** I can see what is safe to delete
from the phone before doing it.

Acceptance criteria:
- Given a backed-up phone, when I run `reclaim`, then only assets that
  are archived AND pass a fresh verification are listed, and nothing is deleted.

### US-E2 — Safely delete from the phone
**As** a user, **I want** to delete backed-up photos from the phone **so that** I
can free space, with confirmation.

Acceptance criteria:
- Given eligible assets, when I run `reclaim --confirm`, then I am asked to
  type `DELETE`; absent/wrong input aborts without an automation bypass.
- Given repeated `--asset` options, only the selected, freshly revalidated
  device-scoped source files may be deleted; stale/recycled-only copies fail.
- Given the Windows/iPhone read/album/large-video and destructive-recovery gate
  is not validated, real AFC deletion is refused even with confirmation.
- Given any reclaim run, then archive files are never touched and deletion never
  runs automatically.

---

## Epic F — Local & Private

### US-F1 — Operate without cloud
**As** a user, **I want** everything to run locally **so that** my data stays
private.

Acceptance criteria:
- Given any command, then no network/cloud service is required or contacted.
- Given the phone has iCloud disabled, then import and all features still work.

---

## Epic G — Graphical User Interface (PySide6)

> The GUI is a first-class frontend, a thin adapter over the same headless
> service layer as the CLI, built with PySide6 for Windows.
> Requirement **US-G1 (full CLI parity)** governs the whole epic.

### US-G1 — Full parity with the CLI
**As** a user, **I want** the GUI to perform every operation the CLI can **so
that** I never have to drop to the terminal.

Acceptance criteria:
- Given any CLI-supported operation (init, device-info, import, verify, dedup,
  albums, list, stats, thumbnail/cache clear, scan-phone, move, recycle/restore/
  purge, marks including clear, reclaim selection, and all config operations),
  then the GUI can
  invoke it through the same service layer.
- Given a new service operation is added, then it is available to both CLI and
  GUI without duplicating business logic.

### US-G2 — Browse pictures
**As** a user, **I want** to browse my archived pictures in a grid **so that** I
can view them visually.

Acceptance criteria:
- Given an archive, when I open the GUI, then pictures are shown as thumbnails
  loaded from the plain archive files.
- Given many pictures, then the view paginates or lazy-loads without freezing.

### US-G3 — Browse albums
**As** a user, **I want** to browse by album **so that** I can navigate my
organization.

Acceptance criteria:
- Given albums exist, when I open the album view, then each album and its picture
  count is listed, including `_Unsorted`.
- Given I select an album, then its pictures are shown.

### US-G4 — Delete or mark a picture for deletion
**As** a user, **I want** to delete a picture or mark it for later deletion **so
that** I can curate the archive safely.

Acceptance criteria:
- Given a selected picture, when I choose "mark for delete", then it is staged
  and nothing is removed until I commit.
- Given staged pictures, when I commit with confirmation, then only those files
  are removed from the archive; the phone is untouched.
- Given a picture in multiple albums, when it is deleted from one album, then it
  remains in the others (unless explicitly deleted everywhere).
- Given `list --files`, the exposed file IDs align with the displayed paths
  and current album/location. `marks add <file-id> --file` stages one copy,
  while default asset marks and `--album` marks retain their distinct scope.
- Given a file-scoped mark is committed, only that copy is recycled/purged;
  other copies, memberships and metadata remain consistent.

### US-G5 — Delete or mark an album for deletion
**As** a user, **I want** to delete or mark a whole album **so that** I can
remove groups at once.

Acceptance criteria:
- Given an album, when I mark it for delete, then all its pictures are staged.
- Given I commit, then that album folder's copies are removed after
  confirmation; pictures shared with other albums remain there.

### US-G6 — Multi-select for move or delete
**As** a user, **I want** to select multiple pictures and move or delete them
together **so that** batch curation is efficient.

Acceptance criteria:
- Given several selected pictures, when I choose "move to album", then all move
  to the chosen album with recoverable per-asset updates and no content change.
- Given CLI `move` without a source filter, all active copies are selected;
  with `--from-album <id>`, only that source album's copies move.
- Given several selected pictures, when I choose delete/mark, then the action
  applies to all of them.

### US-G7 — View what can be safely deleted from the phone
**As** a user, **I want** the GUI to show which phone photos are safe to delete
**so that** I can reclaim space confidently.

Acceptance criteria:
- Given a connected phone, when I open the reclaim view, then it lists only
  assets that are archived AND pass a fresh verification (same result as
  `reclaim` preview).
- Given I confirm deletion in the GUI, then only those phone files are deleted;
  the archive is never modified.

### US-G8 — Progress and cancellation
**As** a user, **I want** progress feedback and the ability to cancel **so that**
long operations are manageable.

Acceptance criteria:
- Given a long operation (import/verify/reclaim), then the GUI shows progress
  from the service layer's progress events.
- Given I click cancel, then the operation stops safely without corrupting the
  archive or catalog.
- Given workers run, each owns its service/SQLite connection; no connection is
  shared across QThreads. Event cancellation and queued UI signals are used.
- Given competing mutations or thumbnail requests, mutations serialize with an
  archive process lock and thumbnail queues/caches remain bounded.

---

## Epic H — Review of Photos Deleted from the Phone

> Lets the user see archived assets that no longer exist on the phone and decide,
> per item, what to do with the archived copy. Read-only detection; explicit,
> user-chosen actions; nothing happens automatically.

### US-H1 — See what was deleted from the phone
**As** a user, **I want** to see archived pictures that are no longer on my phone
**so that** I can review them.

Acceptance criteria:
- Given assets exist in the archive but were not seen in the latest complete,
  successful scan of their own device (not a failed/cancelled scan),
  when I open the "deleted from phone" list/view, then those assets are shown
  with thumbnail, album, and date last seen on the phone.
- Given detection runs, then it changes no files (read-only).

### US-H2 — Multi-select for a batch decision
**As** a user, **I want** to select multiple such pictures **so that** I can act
on them together.

Acceptance criteria:
- Given the list, when I select several items, then a chosen action applies to
  all of them.

### US-H3 — Delete selected from the local archive
**As** a user, **I want** to permanently remove selected pictures from the
archive **so that** I can discard what I no longer want.

Acceptance criteria:
- Given selected items, when I choose "delete from archive" and confirm, then all
  archive copies of those assets are removed.
- Given I do not confirm, then nothing is removed.

### US-H4 — Move selected to the Deleted folder
**As** a user, **I want** to move selected pictures to a Deleted folder **so
that** I set them aside without losing them.

Acceptance criteria:
- Given selected items, when I choose "move to Deleted", then all their copies
  are moved from `Photos/` into `Deleted/`, preserving the album subpath, and the
  bytes are retained.
- Given items are in `Deleted/`, then they are excluded from normal album
  browsing but still pass integrity verification.

### US-H5 — Restore or purge the Deleted folder
**As** a user, **I want** to restore or permanently purge items in the Deleted
folder **so that** I stay in control of the recycle bin.

Acceptance criteria:
- Given an item in `Deleted/`, when I restore it, then it returns to its original
  `Photos/` album location.
- Given items in `Deleted/`, when I purge with confirmation, then they are
  permanently removed from the archive.

### US-H6 — Never automatic, never touches the phone
**As** a user, **I want** guarantees around this workflow **so that** it is safe.

Acceptance criteria:
- Given detection or review, then no action is taken without my explicit choice.
- Given any action here, then the phone is never modified.
