# iPhone Archive — User Guide

> **Source CLI / core-hardening preview, not a validated Windows release.**
> Offline fake-device tests do not establish real-iPhone compatibility.
> There is no implemented GUI, installer, or published portable build.
> See [progress](progress.md) and the [hardware gate](unit-tests.md#4-windowsiphone-validation-gate)
> before using a real phone. Keep an independent backup.

**iPhone Archive** (`ibackup`) copies the photos and videos from your
USB-connected iPhone into a permanent archive on your computer or external
drive. It is built for **long-term preservation**: once a photo is in the
archive, it stays there even if you later delete it from your phone.

Your archived photos are stored as **ordinary files in ordinary folders,
organized by album** — so you can open and view them in **Windows File
Explorer** and any photo viewer, **without needing this app**.

---

## What it does

- Backs up photos and videos from an iPhone connected over USB.
- Keeps your **original files unchanged** — no editing, no re-encoding.
- Builds a **permanent, append-only archive**: it never deletes your archived
  photos automatically, and deleting a photo on the phone does **not** remove it
  from the archive.
- Skips photos that are already archived (**incremental** backups).
- **Verifies** every file after import so you know it copied correctly.
- **Preserves your albums** when the information is available.
- Provides a reclaim preview; real-phone destructive reclaim remains gated
  pending Windows/iPhone validation.
- Runs **entirely on your machine** — no cloud, no iCloud required.

## What it does NOT do

- It is **not** a sync tool and does **not** mirror deletions from the phone.
- It does **not** edit or re-encode your media.
- It does **not** replace Apple Photos.
- It does **not** require any cloud service.

---

## Requirements

- A Windows 10 or 11 (64-bit) PC.
- Python 3.11 or newer for the current source installation.
- An iPhone with a USB cable.
- Apple's **iTunes** or **"Apple Devices"** app installed — it provides the
  Apple Mobile Device USB driver used to talk to the iPhone.

### Install

Currently available: install from a checkout in an activated virtual environment:

```powershell
pip install .
```

Windows packaging is a scheduled release milestone, not an available download.
No PyInstaller spec is included in this remediation.

### First-time device setup

1. Connect the iPhone via USB.
2. Unlock the phone.
3. When the phone asks **"Trust This Computer?"**, tap **Trust** and enter your
   passcode.
4. Check the connection:

   ```powershell
   ibackup device-info
   ```

---

## Getting started

### 1. Create an archive

Pick a folder (a large internal disk or an external drive):

```powershell
ibackup init D:\iphone-archive
```

### 2. Import your photos and videos

```powershell
ibackup import --archive D:\iphone-archive
```

This copies new photos and videos, verifies each one, and organizes them into
album folders. Running it again later only copies **new** items.

### 3. Browse your archive (no app needed)

Open the archive folder in **File Explorer**. Inside `Photos\` you will find one
folder per album:

```
iphone-archive\
  Photos\
    Favorites\
    Family\
    Screenshots\
    _Unsorted\2026\09\     <- photos that weren't in any album
```

Just open a folder and view the pictures like any other files.

> The hidden `.ibackup\` folder holds the app's index and logs. You can ignore
> it — your photos are the plain files in `Photos\`.

---

## Commands

| Command | What it does |
|---|---|
| `ibackup init <path>` | Create and initialize a new archive. |
| `ibackup device-info` | Show the device identifier (UDID) and full enumerated media count; no name/model/iOS fields. |
| `ibackup import` | Import new photos/videos and organize them by album. |
| `ibackup verify` | Re-check that archived files are intact. |
| `ibackup dedup` | Show duplicate and storage statistics. |
| `ibackup albums` | List albums and their photo counts. |
| `ibackup list` | List archived photos (`--album`, `--unsorted`, `--recycled`, `--limit`). |
| `ibackup list --files` | Show aligned file IDs and paths for the current album/location filter; use file IDs for per-copy marks. |
| `ibackup stats` | Show headline archive counts. |
| `ibackup scan-phone` | Refresh which archived photos are still on the phone. |
| `ibackup thumbnail <asset-id>` | Generate a cached preview image for a photo. |
| `ibackup move <album> <asset-ids...>` | Move all active copies of the selected assets into the destination album by default. |
| `ibackup move <album> <asset-ids...> --from-album <source-album-id>` | Move only the selected assets' copies in the source album; preserve their other album copies. |
| `ibackup reclaim` | Preview verified deletion candidates; nothing is deleted. |
| `ibackup reclaim --confirm` | Request deletion with typed `DELETE`; real AFC deletion is gated. |
| `ibackup reclaim --asset <id>` | Limit preview/deletion to selected archive IDs; repeat the option for multiple IDs. |
| `ibackup deleted-on-phone list` | Show archived photos that no longer exist on the phone. |
| `ibackup deleted-on-phone to-deleted <asset-ids...>` | Move selected photos into the `Deleted\` recycle-bin folder. |
| `ibackup deleted-on-phone restore <asset-ids...>` | Restore photos from `Deleted\` back into the album tree. |
| `ibackup deleted-on-phone purge <asset-ids...> --confirm` | Permanently delete selected photos from the archive. |
| `ibackup deleted-on-phone purge <asset-ids...> --recycled-only --confirm` | Permanently delete only their `Deleted/` copies, preserving active `Photos/` copies. |
| `ibackup marks add <id> [--album \| --file]` | Stage an asset (default), album, or individual file copy; `--album` and `--file` are mutually exclusive. Nothing is deleted yet. |
| `ibackup marks list` | Show staged marks. |
| `ibackup marks remove <mark-id>` | Cancel a staged mark. |
| `ibackup marks clear` | Clear all staged marks without changing media. |
| `ibackup marks commit --confirm [--purge]` | Apply staged marks: recycle them, or delete permanently with `--purge`. |
| `ibackup clear-thumbnails` | Remove regenerable previews, never originals. |
| `ibackup config list` | Show all settings and where they are stored. |
| `ibackup config get <key>` | Show one setting. |
| `ibackup config set <key> <value>` | Change one setting. |
| `ibackup config reset` | Restore all settings to their defaults. |
| `ibackup config path` | Show the settings file location. |
| `ibackup config forget <path>` | Drop an archive from the recent list (no files are touched). |

### Choosing a device

`device-info`, `import`, `scan-phone`, `reclaim`, and `deleted-on-phone list`
accept `--device <UDID>`. Use the identifier from `device-info` to select the
intended phone. For `deleted-on-phone list`, the option scopes the stored
report and also selects the device when `--rescan` is requested:

```powershell
ibackup deleted-on-phone list --device "YOUR_DEVICE_UDID" --rescan --archive D:\iphone-archive
```

### Settings

The first archive you create becomes your default, so you can drop `--archive`
entirely. Settings live in `%APPDATA%\ibackup\settings.json` — outside the
archive, so the archive folder stays portable.

| Setting | Default | Meaning |
|---|---|---|
| `default_archive` | *(first archive created)* | Archive used when `--archive` is omitted. |
| `reopen_last_archive` | `true` | Stored preference for the future GUI; no current GUI startup behavior. |
| `recent_archives` | *(managed)* | Recently opened archives; set automatically. |
| `album_link_mode` | `copy` | `copy` or `hardlink` for photos in several albums. |
| `scan_phone_after_import` | `true` | Refresh the deleted-on-phone list after each import. |
| `thumbnail_size` | `256` | Preview size: 128, 256 or 512 px. |
| `confirm_word_required` | `true` | Require typing `DELETE` for permanent deletion. **Cannot be turned off.** |
| `default_deleted_action` | `recycle` | Stored preference for the future GUI review; does not select a CLI action. |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`; applied to the CLI rotating archive log. |

Settings are **preferences only** — none of them can weaken the append-only
guarantee or cause anything to be deleted automatically.
`album_link_mode`, `thumbnail_size` and `scan_phone_after_import` defaults are
applied by the service, not only CLI parsing, so future adapters inherit them.
Settings are validated on load and save: malformed JSON warns and retains
defaults; invalid recognized setting values raise an error rather than silently
weakening a setting.
Use `ibackup config reset` to recover an invalid configuration by restoring
defaults; archive media is not changed.

Archive-scoped commands accept `--archive <path>` (not `init`, `device-info`,
or the user-level `config` commands). To avoid repeating it, set the
`IBACKUP_ARCHIVE` environment variable once per session:

```powershell
$env:IBACKUP_ARCHIVE = "D:\iphone-archive"
ibackup import
```

Commands that delete anything are **safe by default**: `reclaim`,
`deleted-on-phone purge`, and `marks commit` only report what *would* happen
until you add `--confirm`. Permanent archive purge, `marks commit --purge`,
and confirmed reclaim additionally require typing exactly `DELETE` at the
interactive prompt. Missing/mismatched input aborts; there is no automation
bypass. Reversible `marks commit --confirm` keeps its explicit flag without
the permanent-deletion prompt. Direct move-to-Deleted and restore commands
are explicit actions and take effect immediately.

### Asset scope versus individual copies

An asset can have copies in several albums. Plain `marks add <asset-id>` stages
the asset; `marks add <album-id> --album` scopes the action to that album's
copies. Use `list --files` (optionally filtered by album/location), then
`marks add <file-id> --file` to stage just one copy. Mark commit applies that
scope: recycling or purging one copy preserves unselected copies and their
album membership. Permanent commit still requires `--purge --confirm` and
typed `DELETE`.

`move <destination-album> <asset-ids...>` moves all active copies by default;
add `--from-album <source-album-id>` to move only copies from that album and
retain the asset's other album copies. Existing `Deleted/` copies are unchanged.
Direct asset-ID purge is asset-wide unless `--recycled-only` or explicit
`--file` options restrict it. Use file-scoped marks to review intent before
commit, or directly select exact copies as follows.
Both permanent-purge scopes require `--confirm` and typed `DELETE`.

`move` and `deleted-on-phone to-deleted|restore|purge` accept repeatable
`--file <file-id>` options. **Asset IDs remain required positional arguments**;
each file must match those assets and the requested source album/location or
the operation fails instead of broadening the selection. For example, if
`list --files` shows asset 12 owns file 34:

```powershell
ibackup deleted-on-phone to-deleted 12 --file 34 --archive D:\iphone-archive
```

This immediate reversible action moves only copy 34. On editing commands
`--file` takes an ID; on `marks add <id> --file` it is a boolean target-type flag.

### Import options

- `--album-link-mode copy` (default): store a real copy of a photo in each of
  its album folders. Most portable; works on any drive including exFAT.
- `--album-link-mode hardlink`: save space by linking instead of copying, on
  filesystems that support it (NTFS). Automatically falls back to `copy` on
  exFAT/FAT.

---

## Previewing phone space reclamation

Preview against a test device:

```powershell
# See what could be deleted (nothing is deleted yet)
ibackup reclaim --archive D:\iphone-archive

# Narrow the preview to selected archive asset IDs
ibackup reclaim --archive D:\iphone-archive --asset 12 --asset 13
```

Eligibility requires a freshly verified active archive copy and a current,
device-scoped source match, not merely a historical hash. A preview is not
permission to delete: candidates must be revalidated at execution. Real AFC
deletion must stay disabled until read/album/large-video and destructive
recovery checks pass on Windows with a disposable test phone/library.
`--confirm` plus typed `DELETE` is necessary, not a way around that gate.
Reclaim never removes archive files.
Fresh hashes cannot eliminate the time gap between checking a phone file and
unlinking it. AFC deletion/Photos database consistency, including WAL-backed
album metadata, still require hardware validation; this is another reason the
real-device deletion gate remains closed.

---

## Reviewing photos you deleted from your phone

Because the archive keeps everything, photos you delete on the phone stay in the
archive. You can review those and decide what to do with each one:

```powershell
# Show archived photos that are no longer on the phone (--rescan checks the phone first)
ibackup deleted-on-phone list --rescan --archive D:\iphone-archive
```

For the ones you select, choose either:

- **Move to the Deleted folder (safe, reversible):**

  ```powershell
  ibackup deleted-on-phone to-deleted 12 13 14 --archive D:\iphone-archive
  ```

  The photos are moved out of `Photos\` into a `Deleted\` folder (a recycle bin).
  Nothing is lost — you can restore or purge them later.

- **Delete from the local archive (permanent):**

  ```powershell
  ibackup deleted-on-phone purge 12 13 14 --confirm --archive D:\iphone-archive
  ```

  This permanently removes those photos from the archive after you confirm.

The planned GUI will provide the same review as a multi-select thumbnail list.
It is not implemented and remains blocked on explicit sketch approval.

---

## Frequently asked questions

**Do I need iCloud?**
No. Device access is over USB. However, cloud-only originals that are not
available through AFC are not guaranteed to be imported; an accessible DCIM
inventory is not proof that the complete Apple Photos/iCloud library is local.

**Will it change or compress my photos?**
No. Files are copied exactly as they are on the phone.

**If I delete a photo on my phone, does it disappear from the archive?**
No. The archive is append-only and keeps it.

**Why do some photos appear in more than one folder?**
If a photo is in several albums, a copy is placed in each album folder so every
folder is complete on its own. Use `dedup` to see the storage impact,
or use `--album-link-mode hardlink` to save space where supported.

**Can I open the archive in File Explorer?**
Yes. The photos are plain files in plain folders with Windows-safe names, so you
can browse and view them without this app.

**Is there a graphical interface?**
Not yet. A PySide6 interface with full CLI parity is specified in
[`ui-sketch/README.md`](ui-sketch/README.md), but all GUI code and its entry
point remain blocked on explicit approval. Use CLI listings or File Explorer.

---

## Troubleshooting

- **`device-info` shows no device:** unlock the phone, replug the cable, and tap
  **Trust** on the phone. Make sure iTunes / "Apple Devices" is installed so the
  Apple Mobile Device USB driver is present.
- **Media directory access fails:** treat this as an incomplete scan, not an
  empty phone. Resolve access/connectivity errors before trusting absence data.
- **Albums are missing (photos went to `_Unsorted`):** album information could
  not be read or its schema was unsupported. This does not prove the entire
  phone library was accessible; review import errors and verify copied files.
- **Permission errors on an external drive:** make sure you can write to the
  drive, and prefer NTFS or exFAT for large drives.

### Recovery and safety

- Keep `Photos/`, `Deleted/`, and `.ibackup/` together when copying an archive.
  Sidecars help inspection; an automatic catalog rebuild command is not
  currently available.
- After an interrupted import/edit, preserve the archive and logs, reopen it
  and run `verify`. Do not delete staging or recovery material by hand or run
  purge/reclaim to "clean up" an inconsistency.
- Archive edits keep recovery journals under `.ibackup/operations/`.
  Reopening the service attempts rollback/finalization only when recorded file
  ownership can be verified; preserve any
  `.ibackup/operation_conflicts/` files for inspection. Recovery is not an
  independent backup and its Windows/power-loss behavior still needs validation.
  In particular, directory-flush guarantees differ on Windows; a journal is
  not a guarantee against every storage-device or power-loss failure.
- Imports keep separate per-item journals under `.ibackup/import-journals/`.
  Preserve this directory and `.ibackup/import-staging/`; startup/import recovery uses catalog commit
  markers to distinguish work to finish from work to roll back.
  Ambiguous or unowned recovery files cause an error instead of being deleted;
  preserve them and inspect the report rather than force-cleaning the journal.
- Moves/recycle/restore and staged purge may temporarily require extra disk
  space: originals remain while exclusive destination/staging copies are made,
  until the catalog commit permits cleanup. Do not remove these copies manually
  to make room during an interrupted operation.
- A postcommit cleanup error explicitly requires recovery: reopen the archive
  to attempt cleanup before continuing. Destination-name collisions use suffixes
  rather than overwriting; unsafe or symlinked paths are refused.
  Recovery verifies hashes and recorded file identities; unowned, ambiguous or
  externally replaced files are refused even if replacement bytes are identical.
  Private staging lets ordinary interrupted creation and ownership-record writes
  roll back; external interference or damaged content can still require manual
  investigation. Preserve journals, staged files and conflicts. The archive lock
  does not hide intermediate file copies from File Explorer or prevent external
  programs from changing them.
- Failed/cancelled scans must not turn unseen items into "deleted on phone".
  Check the selected device identity; an identical path on another phone is
  not the same source. Schema-v2 migration preserves legacy content but does
  not trust old unscoped identities; rerun import/content validation for the
  selected device before relying on incremental matching.
- A fresh integrity error or missing copy blocks destructive work. Restore
  from an independent backup rather than overwriting a known-good original.
- An OS-exclusive lock allows only one open service session per archive,
  including read operations. A competing session is rejected as busy, not
  queued; close the existing session before retrying. Do not bypass the lock.
- `.ibackup/logs/` contains a rotating CLI diagnostic operation log governed by
  `log_level`, recording command start/completion/error. Its handler closes at
  command end. This is not structured per-asset or immutable audit logging;
  that remains future work. Review paths/device data before sharing logs.
