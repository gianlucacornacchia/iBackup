# Device Compatibility

This page records which iPhone models, iOS versions and Windows setups
iPhone Archive has actually been tested on, what worked, and the known bugs.
A row counts as tested only when a dated run on real hardware is recorded in
[progress.md](progress.md). Passing unit tests, which run against a fake device,
does not count.

**Help wanted:** so far there is one tested phone. If you own a different
model or run another iOS version, a test report is the single most useful
contribution you can make. See [Report your device](#report-your-device).

Legend: ✅ works · ⚠️ partial or with known limits · ❌ not supported ·
❔ untested

## Tested devices

| iPhone | Model ID | iOS | Host | First tested | Result |
|---|---|---|---|---|---|
| iPhone 12 | `iPhone13,2` | 26.4 (`23E246`) | Windows 11 (build 26200), NTFS | 2026-09-16 | ⚠️ Read and import work; see the feature matrix |
| iPhone 12 | `iPhone13,2` | 26.4 | Linux (development host) | 2026-09-10 | ⚠️ First real-device run; found the iOS 26 album bug fixed below |

Software on the Windows run: Python 3.11.9, pymobiledevice3 11.10.4,
PySide6 6.11.2, Pillow 12.3.0, PyAV 18.1.0. The test library held about
1,320 media files (5.6 GB) in 67 albums, plus 18 iCloud Shared Albums.

Every other model and iOS version is ❔ untested. The app reads the phone
over Apple File Conduit, which all iPhones support, but the Photos database
that albums, capture dates and GPS come from changes layout between iOS
versions (see [iOS version notes](#ios-version-notes)).

## Feature matrix

Results for the iPhone 12 on iOS 26.4.

| Feature | Status | Evidence and limits |
|---|---|---|
| Connect, trust, `device-info` | ✅ | Correct UDID and media count; reconnecting in a new USB session works. Locked or untrusted phones, cable pulls and several phones at once are untested. |
| Import of JPEG, HEIC, PNG, MOV, MP4 | ✅ | Every byte count and SHA-256 matched an independent read of the phone. Tested on samples (8 and 12 items, largest video 237 MB), not a full-library import. |
| Incremental import (skip already archived) | ✅ | A second run moved 0 bytes (`added=0, skipped=40`). |
| `verify` | ✅ | All copies matched, with no missing files. |
| User albums | ✅ | Membership matched independent SQL for all 1,318 items, with 0 mismatches. Moving a photo between albums is reconciled on the next import (unit-tested; not yet recorded on hardware). |
| Capture dates | ✅ | Matched independent SQL for every enumerated item. |
| GPS location | ✅ | Backfill found GPS for 5,396 of 6,641 archived assets. |
| "Optimize iPhone Storage" previews | ⚠️ | All 5,263 album photos whose originals were offloaded were recovered as previews, and a 12-item import verified. The in-place upgrade to the original once it is back on the phone is untested on hardware. |
| iCloud Shared Albums | ⚠️ | 18 albums and 6,150 items were found and read. A full end-to-end import is not yet recorded. Most items arrive as previews, because iOS caches few shared originals. |
| HEIC thumbnails | ✅ | Generated from real archived files. |
| Camera details (EXIF) | ⚠️ | Read from archived files and stored, but not yet shown in the GUI. HEIC EXIF has not been checked on hardware. |
| Video poster frames | ❔ | Unit-tested only. |
| Live Photos (photo + video pair) | ❔ | The pairing has not been checked. |
| Multi-GB videos | ❔ | Largest tested file: 237 MB. |
| Hardlink mode, exFAT drives | ❔ | Only NTFS in copy mode has been tested. |
| Packaged GUI (`ibackup-gui.exe`) | ⚠️ | It builds and passes the launch smoke test. Opening the map in the packaged app is untested. |
| Free space on the phone (`reclaim --confirm`) | ❌ | Disabled on purpose: a raw file delete would not update the Photos library. The preview works and deletes nothing. |

Measured speed on the iPhone 12: about 34 MB/s for large files, plus a
fixed cost of about 36 s per run, spent mostly copying the phone's 1 GB
`Photos.sqlite`.

## iOS version notes

The Photos database layout differs between iOS versions, and so does how
albums, shared albums and locations are stored. The app discovers what it
can at runtime and falls back gracefully when it can't. A version it does not
understand produces warnings and puts photos in `_Unsorted`; the photos are
still imported.

| What | iOS 26.4 (tested) | Other versions |
|---|---|---|
| Album ↔ photo join table | `Z_33ASSETS`, found at runtime | Name varies (for example `Z_28ASSETS`); found at runtime, but untested |
| iCloud Shared Albums | `ZSHARE` rows, files under `/PhotoData/PhotoCloudSharingData` | Older iOS is expected to use `ZGENERICALBUM.ZKIND = 1505`; supported in code but never seen on a real phone |
| GPS | `ZLATITUDE` / `ZLONGITUDE` on the asset table | If a version stores location elsewhere, no phone GPS is read; GPS from the photo's EXIF still fills it in |
| Offloaded-original previews | Path-mirrored JPEGs under `/PhotoData/Thumbnails/V2` | Untested |

## Known issues and limitations

Open:

- **Phone-space reclamation frees nothing yet.** Deleting from the phone stays
  disabled until a supported deletion path is validated
  (`device-delete-validation` in [todos.md](todos.md)).
- **Every import pays about 36 s** to copy `Photos.sqlite`, even when nothing
  is new (`future-photosdb-cache`).
- **USB cannot download iCloud originals.** Offloaded photos are archived as
  labelled low-resolution previews until you open them in Photos on the phone
  and import again.
- **Shared albums:** the owner is not recorded, and an original that iOS
  later evicts from its cache is not matched to the full-resolution copy
  already in the archive (`shared-album-owner`, `shared-album-absence`).
- **Map popups** show the stored capture time without converting it to your
  local time zone (`map-popup-timezone`).
- **Camera details** are stored but not displayed (`metadata-display`).

Found on real hardware and fixed:

| Date | Bug | Fix |
|---|---|---|
| 2026-09-10 | Albums were completely empty on iOS 26, because the database join table had a different name | The table name is now discovered at runtime; 750 items across 67 albums were recovered |
| 2026-09-16 | A filename-only fallback put 635 photos in albums they did not belong to | Albums now match on the exact directory + filename only |
| 2026-10-09 | 5,263 album photos were missing, because their originals were offloaded to iCloud | They are imported from the phone's cached thumbnails as labelled previews |
| 2026-10-11 | No iCloud Shared Albums were found on iOS 26 | Shared albums are now read from the iOS 26 `ZSHARE` table |

## Report your device

Testing your own iPhone helps everyone, even if everything works. Results
from other models, older iOS versions and Windows 10 are especially welcome.

1. **Protect your data.** Use a new, disposable archive folder on a drive with
   room for your whole library. Keep your existing backups as they are.
   Nothing in these steps deletes or changes anything on the phone.
2. Install from source (see the [README](../README.md#installation)), connect
   and unlock the phone, and tap **Trust**.
3. Run the checks:

   ```powershell
   ibackup device-info
   ibackup init D:\ibackup-test
   ibackup import --archive D:\ibackup-test --verbose
   ibackup import --archive D:\ibackup-test      # the second run should add 0
   ibackup verify --archive D:\ibackup-test
   ibackup albums --archive D:\ibackup-test
   ibackup stats  --archive D:\ibackup-test
   ```

   Optionally, open the archive in `ibackup-gui` and check that albums,
   thumbnails and the map look right.
4. Open a
   [device compatibility report](https://github.com/gianlucacornacchia/iBackup/issues/new?template=device_report.yml)
   with your iPhone model, iOS version, Windows version, the command output
   and any warnings from `D:\ibackup-test\.ibackup\logs\`. Remove your device
   UDID and any personal file or album names you don't want to share.

The maintainers turn each report into a row in the tables above.

## Contributing features and fixes

You don't need an iPhone to help. Most of the code (catalog, import rules,
GUI, map) is developed and tested against a fake device. Open issues and
planned work are listed in [todos.md](todos.md), and the "Known issues"
section above is a good place to start. See [CONTRIBUTING.md](../CONTRIBUTING.md)
for the setup and the checks a pull request must pass.
