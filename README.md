# iPhone Archive (`ibackup`)

A **Windows-targeted** photo archive project (CLI and GUI implemented from
source; no release yet) that creates a permanent,
**append-only** archive of photos and videos from a USB-connected iPhone. Media
is stored as **plain files in album folders**, browsable in File Explorer
without the app. The archive — not the phone — is the source of truth.

> Status: **offline core-hardening complete; Phase 2 GUI steps 1-12 done**.
> Core and CLI implementations have offline fake-device tests; the read/import
> path has also been exercised against a real iPhone 12 (iOS 26.4) on Windows
> 11, which is not Windows release validation. The GUI sketch was approved on
> 2026-09-11; `ibackup-gui` opens a
> themed window with navigation, a command bar, live counts, a thumbnail grid
> with multi-select and a full-size viewer, and it can now open an archive and
> run every archive operation, including recycling, restoring, purging, marking
> and previewing phone-space reclamation behind a typed-`DELETE` confirmation.
> Every stored preference is editable in the settings dialog, which can never
> weaken a confirmation. Reclamation cannot yet free space on a real
> phone: device-side deletion remains disabled pending hardware validation.
> Mica is an opt-in Windows probe; normal launches use solid backgrounds. No
> downloadable Windows release is available. See
> [`docs/progress.md`](docs/progress.md) for validation evidence and remaining
> gates.

The GUI worker foundation serializes archive work off the UI thread, with
cooperative cancellation and safe shutdown. Paged asset/album models,
copy-scoped selection, a background preview pipeline, the application shell, the
photo gallery, the safe and destructive operations and the settings dialog are
implemented (Phase 2 steps 1-11). Import, verify, scan, the duplicate report and
move-to-album run behind a progress dialog that can be cancelled where the
backend supports it, or hidden. A parity test now fails the build if any CLI
command or service method has no GUI surface, so the two front ends cannot drift
apart. Windows packaging (step 12) is in place: `packaging/ibackup.spec` freezes
the GUI into `dist/ibackup-gui/ibackup-gui.exe`, which CI builds and launches as
a smoke test. A signed, downloadable release is still a later milestone.

Since then (commits of 2026-09-16 to 2026-10-10, plus the 2026-10-11 shared
albums work; see `docs/progress.md`):

- **Exact album paths.** Album membership and capture dates are keyed by the
  phone's `ZDIRECTORY` + filename; a reused filename never assigns albums.
- **Offloaded previews.** Album members whose originals were offloaded
  ("Optimize iPhone Storage") are imported from the phone's cached
  `/PhotoData/Thumbnails/V2` JPEG, named `… (offloaded preview).jpg` and
  flagged in the catalog. When the original returns to the phone, the next
  import upgrades that asset in place (`upgraded` count) instead of adding a
  duplicate. Resolved preview paths are cached per device in
  `.ibackup-device-cache/offloaded-preview-cache.json`.
- **Album reconciliation.** Each import makes an asset's `Photos/` copies match
  its *current* phone album membership: new album copies are added and copies
  for albums the phone no longer reports (including a stale `_Unsorted` copy)
  are removed. Recycle-bin copies are untouched.
- **Location and camera metadata.** GPS from `Photos.sqlite` (EXIF GPS as a
  fallback) and EXIF camera/lens/ISO/aperture/focal length are stored in the
  catalog (schema v6) and backfilled onto already-archived assets on reimport.
- **Trip map.** Every gallery view (All photos, Unsorted, Recycle bin, each
  album) has a **Map** button opening a zoomable Leaflet/OpenStreetMap map of
  its located photos in capture order. **This is the only feature that uses
  the network:** it downloads map tiles from `tile.openstreetmap.org` while
  the map is open. Everything else, including import, stays local.
- **GUI fixes.** Larger tiles/buttons/navigation icons; the Marked and
  Deleted-from-phone pages now lay out correctly and show real thumbnails.
- **iCloud Shared Albums (2026-10-11).** Shared albums (`Photos.sqlite`
  `ZKIND = 1505`) are imported from the phone's local shared-album cache
  (`/PhotoData/PhotoCloudSharingData`) over USB into
  `Photos/_Shared Albums/<album>/`, listed separately in the GUI ("Shared
  albums") and by `ibackup albums --shared`. Only media already downloaded to
  the phone can be imported; no iCloud login or network is used. Not yet
  validated on a real iPhone.

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/readme-user.md`](docs/readme-user.md) | End-user guide (install, commands, browsing). |
| [`docs/specifications.md`](docs/specifications.md) | Functional & technical specification. |
| [`docs/structure.md`](docs/structure.md) | Architecture & module layout. |
| [`docs/user-stories.md`](docs/user-stories.md) | User stories & acceptance criteria. |
| [`docs/unit-tests.md`](docs/unit-tests.md) | Test plan. |
| [`docs/development.md`](docs/development.md) | Dev environment, libraries, running tests. |
| [`docs/plan.md`](docs/plan.md) | Consolidated implementation plan. |
| [`docs/todos.md`](docs/todos.md) | Build checklist with dependencies/status. |
| [`docs/progress.md`](docs/progress.md) | Resumable progress log (update as you work). |
| [`docs/ui-sketch/`](docs/ui-sketch/README.md) | Approved GUI wireframes and clickable reference mock. |

## Quick start (developers)

See [`docs/development.md`](docs/development.md) for full details.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Quick start (users)

From a source installation (see the developer setup above). Use a disposable
archive and non-destructive checks until the Windows/iPhone validation matrix
passes; do not rely on this project as your only backup.

```powershell
ibackup init D:\iphone-archive
ibackup import --archive D:\iphone-archive
ibackup verify --archive D:\iphone-archive
```

See [`docs/readme-user.md`](docs/readme-user.md) for the full command reference.

## Tech stack

- Python 3.11+ · Typer (CLI) · PySide6 (GUI, including Qt WebEngine for the
  map) · `pymobiledevice3` (iPhone/AFC) · SQLite · Pillow + `pillow-heif`
  (HEIC thumbnails, EXIF) · PyAV (video poster frames) · vendored Leaflet
  (BSD-2-Clause, `src/iphone_archive/gui/webassets/leaflet/`) ·
  pytest / hypothesis / pytest-qt · ruff · mypy · PyInstaller.

## License

MIT.

Bundled dependencies retain their own licenses. A future Qt/icon distribution
must satisfy the notice and redistribution obligations in
[`ADR-0011`](docs/adr/0011-licensing-and-gui-contract-addendum.md), including
its 2026-10-11 note on Leaflet, Qt WebEngine and OpenStreetMap tiles.
