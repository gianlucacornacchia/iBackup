# iPhone Archive — User Guide

> **Source CLI/GUI preview, not a validated Windows release.**
> Offline fake-device tests and a limited real-iPhone read/import check do not
> establish general real-iPhone compatibility. The source GUI (`ibackup-gui`)
> runs every archive operation; a Windows build recipe exists, but there is no
> installer or published portable build.
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
- **Preserves your albums** when the information is available, and keeps the
  album folders in step with the phone: if you move a photo to another album
  on the phone, the next import moves its archive copy too (see
  [Albums that change on the phone](#albums-that-change-on-the-phone)).
- Also archives the **iCloud Shared Albums** you see on the phone, in their own
  `_Shared Albums` folder (see [iCloud Shared Albums](#icloud-shared-albums)).
- Records each photo's **location** and **camera details** (camera, lens, ISO,
  aperture, focal length) in its index, and shows located photos on a
  zoomable **map** in the desktop interface.
- Provides a reclaim preview; real-phone destructive reclaim remains gated
  pending Windows/iPhone validation.
- Runs **on your machine** — no cloud, no iCloud required. The only exception
  is the optional map, which downloads map imagery from OpenStreetMap while
  it is open (see the [FAQ](#frequently-asked-questions)).

## What it does NOT do

- It is **not** a sync tool and does **not** mirror deletions from the phone.
- It does **not** edit or re-encode your media.
- It does **not** replace Apple Photos.
- It does **not** require any cloud service, and it never uploads your photos.
  (Viewing the map does tell the OpenStreetMap tile server which map area you
  are looking at; see the FAQ.)

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

Windows packaging now exists as a build recipe (`packaging/ibackup.spec` builds
`ibackup-gui.exe`), but a signed, downloadable release is still a scheduled
milestone - there is no installer to download yet.

### Desktop interface preview

Run `ibackup-gui` to open the window. It can open or create an archive, browse
albums, the unsorted pool and the recycle bin in a thumbnail grid, view a photo
full size, and run the archive operations: import, verify, scan phone, duplicate
report, move to album, move to the `Deleted/` recycle bin, restore, permanent
delete, the deleted-from-phone review, the marks queue and a phone-space
reclamation preview.

**Nothing is deleted without confirming it.** Anything permanent - deleting from
the archive, committing marks permanently, deleting from the phone - asks you to
type `DELETE`, exactly as the CLI requires `--confirm`. Moving to the `Deleted/`
folder is reversible and asks a simple yes/no instead. Freeing phone space always
shows you a checked, re-verified list first; that preview deletes nothing. Note
that device-side deletion is still disabled pending hardware validation, so
reclamation cannot yet free space on a real iPhone.

**Map.** Every photo view (All photos, Unsorted, Recycle bin and each album)
has a **Map** button in its header. It opens a zoomable OpenStreetMap map of
the photos in that view that have a location, joined by a line in the order
they were taken; the first is green, the last red, and clicking a dot shows
the file name. The Marked and Deleted-from-phone pages have no map. The map
needs an internet connection for the map imagery; without one, the dots, line
and zoom still work over a blank background. Viewed map tiles are cached
(up to 200 MB) so revisiting an area needs no new downloads.

**Camera details** (camera, lens, ISO, aperture, focal length) are read from
each photo's own EXIF when it is archived and stored in the archive index.
They are not shown in the interface yet, and they are not added to the photo
files or sidecars (your files are never modified).

**Settings** has its own dialog (the **Settings** button at the bottom of the
navigation pane); every preference below can be edited there, or with
`ibackup config`. Choose the appearance from the dialog or before launching:

```powershell
ibackup config set theme dark       # light or system are also accepted
ibackup-gui
```

The default `system` follows Windows appearance changes while the GUI is open.
System accent colors are used, and high-contrast mode takes precedence over
custom colors. Normal launches use solid backgrounds; native Windows title-bar
effects remain platform-dependent. The experimental Mica probe is described in
the [development guide](development.md#running-the-windows-mica-probe).

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
album folders. Running it again later only copies **new** items, keeps album
folders in step with the phone, and fills in location/camera details for
photos archived before those were recorded. The summary line reports
`Added`, `skipped`, `duplicates`, `upgraded` (offloaded previews replaced by
their full-resolution original) and `errors`.

### 3. Browse your archive (no app needed)

Open the archive folder in **File Explorer**. Inside `Photos\` you will find one
folder per album:

```
iphone-archive\
  Photos\
    Favorites\
    Family\
    Screenshots\
    _Shared Albums\
      Family Trip\         <- an iCloud Shared Album
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
| `ibackup albums` | List albums and their photo counts; iCloud Shared Albums end with `(shared)`. |
| `ibackup albums --shared` | List only iCloud Shared Albums (`No shared albums yet.` when there are none). |
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
| `reopen_last_archive` | `true` | Reopen the last archive when the GUI starts, if that folder is still an archive. |
| `recent_archives` | *(managed)* | Recently opened archives; set automatically. |
| `album_link_mode` | `copy` | `copy` or `hardlink` for photos in several albums. |
| `scan_phone_after_import` | `true` | Refresh the deleted-on-phone list after each import. |
| `thumbnail_size` | `256` | Preview size: 128, 256 or 512 px. |
| `confirm_word_required` | `true` | Require typing `DELETE` for permanent deletion. **Cannot be turned off.** |
| `default_deleted_action` | `recycle` | Which button the GUI's deleted-from-phone review suggests; it never acts on its own and does not select a CLI action. |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`; applied to the CLI rotating archive log. |
| `theme` | `system` | GUI appearance: `system`, `light` or `dark`; applied at startup, with live system appearance updates. |

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

### Albums that change on the phone

Each import compares every photo still on the phone with its album folders in
the archive and makes them match the phone's **current** albums:

- Added to another album on the phone → a copy is added to that album folder;
  existing album copies stay.
- Moved to a different album, or removed from one → the copy in the old
  album folder is removed from `Photos\`.
- Added to its first album → its `_Unsorted` copy is removed.
- Removed from every album → it gets an `_Unsorted` copy again.

New copies are always written before old ones are removed, so a photo never
drops below one copy in the archive. Copies in `Deleted\` are never touched,
and photos no longer on the phone are left exactly where they are.

Because the phone's albums win, an album change you made **in the archive**
(`move`, or Move to album in the GUI) for a photo that is still on the phone
is undone by the next import if the phone's albums differ. To keep a
different arrangement, change the album on the phone as well.

> **Caution:** if the phone's photo database cannot be read during an import
> (the log says "Photos metadata unavailable"), every photo looks album-less,
> and the import currently moves the album copies of photos still on the phone
> into `_Unsorted`. No photo is lost (one copy always remains), and the next
> import that can read the database puts the copies back in their albums, so
> if you see that warning, fix the connection and import again.

### iCloud Shared Albums

Shared albums (the ones under **Shared Albums** in the Photos app, whether you
created them or someone invited you) are imported too, as long as their photos
are **already downloaded on the phone**:

- They are stored in `Photos\_Shared Albums\<album name>\`, so a shared album
  never mixes with one of your own albums that has the same name.
- In the desktop interface they appear in their own **Shared albums** section
  of the navigation pane, below **Albums**, with a "shared" icon; hovering
  shows "(iCloud Shared Album)". They open like any album (grid, viewer, Map,
  marks). **Move to album** with a name that exists both as your album and as
  a shared album always picks your own album.
- In the CLI, `ibackup albums` tags them `(shared)` and
  `ibackup albums --shared` lists only them.
- A photo you took that is also in a shared album is archived twice: your
  original (in your album or `_Unsorted`) and the shared album's copy. iCloud
  re-encodes shared photos, so the two are different files, not duplicates.
- They follow the same rules as [albums that change on the phone](#albums-that-change-on-the-phone):
  if you leave a shared album, or a photo is removed from it, the next import
  removes that shared-album copy (the photo keeps at least one copy).
- **Phone-space reclamation never offers shared-album files**; they are
  iCloud's cache, and deleting them would free nothing lasting.

Limitations:

- Only photos the phone has already cached can be imported. If the log says
  "shared-album items are not cached on the phone and were skipped", open the
  shared album in Photos so the phone downloads them, then import again. There
  is no low-resolution preview fallback for shared albums.
- If the phone's shared-album folder cannot be read, the log says
  "shared albums unavailable" and the rest of the import continues normally.
  If the photo database cannot be read, no shared-album photos are imported
  at all (they are never dumped into `_Unsorted`).
- Shared-album photos that the phone no longer has cached, or albums you have
  left, may then show up on the **Deleted from phone** page, like any photo
  the phone no longer has.
- Who owns a shared album is not recorded.
- This is still plain USB access to files on the phone: no iCloud sign-in and
  no network. It has **not yet been tested on a real iPhone**.

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

The desktop interface provides the same review on its **Deleted from phone**
page, as a multi-select thumbnail list with the same two actions.

---

## Frequently asked questions

**Do I need iCloud?**
No. Device access is over USB. However, cloud-only originals that are not
available through AFC are not guaranteed to be imported at full resolution; an
accessible DCIM inventory is not proof that the complete Apple Photos/iCloud
library is local. Album metadata can remain on the phone even when the
originals have been offloaded ("Optimize iPhone Storage"). For those photos,
iBackup imports the same cached, low-resolution JPEG preview that iOS itself
shows in Photos, clearly named with an " (offloaded preview)" suffix, so the
album is still complete instead of missing that photo entirely. To get the
full-resolution original instead, select **Download and Keep Originals** in
the iPhone's Photos/iCloud settings (or open the photo in Photos so the phone
downloads it), let it finish downloading with enough free storage, then
import again. The next import recognizes the original at the same phone path
and **upgrades the preview in place**: the low-resolution file is deleted and
replaced by the full-resolution copy in the same album folders, keeping the
photo's marks and album links, and the summary counts it as `upgraded`.
iBackup does not fetch originals from iCloud itself; USB/AFC offers no way to
ask for that.

**Does it use the internet?**
Only for the map. Backing up, verifying, browsing and every other operation
work fully offline. When you open a **Map**, the app downloads map tiles from
OpenStreetMap's public tile server (`tile.openstreetmap.org`), which therefore
sees your IP address and the map areas you view. Your photos and the list of
photo locations stay on your computer; the map page is built locally. Tiles
are cached on disk (up to 200 MB) in a separate Qt WebEngine profile named
`ibackup-map-tiles`. Map data © OpenStreetMap contributors. If you do not
want this, simply do not open the map.

**Where do the location and camera details come from?**
The location comes from the phone's photo database; if it has none, from the
GPS block in the photo's own EXIF. Camera, lens, ISO, aperture and focal
length come from the archived file's EXIF. Videos and files without EXIF
simply have none. Photos archived before these were recorded get them filled
in on the next import; values already recorded are never overwritten.

**Can it back up iCloud Shared Albums?**
Yes, the photos and videos of a shared album that are already downloaded on
the phone, read over USB without signing in to iCloud. Open the shared album
in Photos first so the phone caches its contents. They land in
`Photos\_Shared Albums\`; see [iCloud Shared Albums](#icloud-shared-albums).

**Will it change or compress my photos?**
No. Files are copied exactly as they are on the phone.

**If I delete a photo on my phone, does it disappear from the archive?**
No. The archive is append-only and keeps it.

**If I move a photo to another album on my phone, do I get two copies?**
No. The next import moves its archive copy to match; see
[Albums that change on the phone](#albums-that-change-on-the-phone).

**Why do some photos appear in more than one folder?**
If a photo is in several albums, a copy is placed in each album folder so every
folder is complete on its own. Use `dedup` to see the storage impact,
or use `--album-link-mode hardlink` to save space where supported.

**Can I open the archive in File Explorer?**
Yes. The photos are plain files in plain folders with Windows-safe names, so you
can browse and view them without this app.

**Is there a graphical interface?**
Yes: run `ibackup-gui` (see [Desktop interface preview](#desktop-interface-preview)).
It covers every CLI operation; a test fails the build if one is missing. It
is run from a source installation; there is no downloadable build yet.

---

## Troubleshooting

- **`device-info` shows no device:** unlock the phone, replug the cable, and tap
  **Trust** on the phone. Make sure iTunes / "Apple Devices" is installed so the
  Apple Mobile Device USB driver is present.
- **Media directory access fails:** treat this as an incomplete scan, not an
  empty phone. Resolve access/connectivity errors before trusting absence data.
- **Albums are missing or incomplete:** an album can exist in the phone's
  database while none of its originals are available through USB. iBackup now
  falls back to the phone's own cached low-resolution thumbnail for these
  (named with an " (offloaded preview)" suffix) so the album is still
  populated; the log reports how many album paths were recovered this way and
  how many had no cache either. Download originals to the phone and import
  again for full-resolution copies. An empty/missing archive album does not
  prove the album was empty on the phone.
- **Photos went to `_Unsorted`:** no membership could be resolved for that
  exact media path, or the metadata could not be read. Modern Photos databases
  are matched by directory **and** filename, never by a reused filename alone.
- **Wrong albums from earlier builds:** the old filename fallback could attach
  an offloaded photo's albums to an unrelated local photo. The corrected
  importer prevents this for new imports, and because imports now reconcile
  album folders with the phone, reimporting removes those wrong album copies
  for photos that are still on the phone (placing them in their real albums or
  `_Unsorted`). Photos no longer on the phone keep their old placement. As a
  precaution, back up the existing archive before that reimport. Restart the
  GUI after updating.
- **Permission errors on an external drive:** make sure you can write to the
  drive, and prefer NTFS or exFAT for large drives.
- **A second/later import is slow, or I only want new photos:** just click
  **Import** again - it is already incremental and never re-copies a photo
  already in the archive, so it only spends time copying what is actually
  new. There is no separate "new photos only" button to look for. Every import
  still has to re-walk the phone's `/DCIM` folder and re-read its photo
  database to know what is new, so some time is always spent before copying
  starts; that part scales with how many photos and albums are on the phone,
  not with how many are new. If the phone has offloaded ("Optimize iPhone
  Storage") albums, resolving their low-resolution previews used to repeat an
  AFC lookup for every offloaded photo on every import; those lookups are now
  cached on disk per device (`.ibackup-device-cache\offloaded-preview-cache.json`
  in the folder the app was started from, not in the archive), so only the
  first import after this update pays that cost again. The file is safe to
  delete; it is rebuilt on the next import.

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
  selected device before relying on incremental matching. Later migrations
  (v3-v6: offloaded-preview flags, location, camera details) only add empty
  columns, run automatically when the archive is opened, and cannot be undone;
  an older build refuses to open an upgraded archive.
- A fresh integrity error or missing copy blocks destructive work. Restore
  from an independent backup rather than overwriting a known-good original.
- An OS-exclusive lock allows only one open service session per archive,
  including read operations. A competing session is rejected as busy, not
  queued; close the existing session before retrying. Do not bypass the lock.
- `.ibackup/logs/` contains a rotating CLI diagnostic operation log governed by
  `log_level`, recording command start/completion/error. Its handler closes at
  command end. This is not structured per-asset or immutable audit logging;
  that remains future work. Review paths/device data before sharing logs.
