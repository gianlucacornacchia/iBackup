# iPhone Archive — User Guide

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
- Optionally helps you **safely free up space** on the phone after backup.
- Runs **entirely on your machine** — no cloud, no iCloud required.

## What it does NOT do

- It is **not** a sync tool and does **not** mirror deletions from the phone.
- It does **not** edit or re-encode your media.
- It does **not** replace Apple Photos.
- It does **not** require any cloud service.

---

## Requirements

- A Windows 10 or 11 (64-bit) PC.
- Python 3.11 or newer (only if installing via `pip`; the packaged `.exe`
  bundles its own runtime).
- An iPhone with a USB cable.
- Apple's **iTunes** or **"Apple Devices"** app installed — it provides the
  Apple Mobile Device USB driver used to talk to the iPhone.

### Install

Option A — packaged app (recommended):

- Download and run the `ibackup` Windows installer, or unzip the portable
  build. This provides both `ibackup` (CLI) and `ibackup-gui` (GUI).

Option B — from source (Python):

```powershell
pip install .
```

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
| `ibackup device-info` | Detect the iPhone and show how many items it holds. |
| `ibackup import` | Import new photos/videos and organize them by album. |
| `ibackup verify` | Re-check that archived files are intact. |
| `ibackup dedup` | Show duplicate and storage statistics. |
| `ibackup albums` | List albums and their photo counts. |
| `ibackup list` | List archived photos (`--album`, `--unsorted`, `--recycled`, `--limit`). |
| `ibackup stats` | Show headline archive counts. |
| `ibackup scan-phone` | Refresh which archived photos are still on the phone. |
| `ibackup thumbnail <asset-id>` | Generate a cached preview image for a photo. |
| `ibackup move <album> <asset-ids...>` | Move a selection of photos into another album. |
| `ibackup reclaim` | List phone photos that are safe to delete (dry run). |
| `ibackup reclaim --confirm` | Delete those photos from the phone. |
| `ibackup deleted-on-phone list` | Show archived photos that no longer exist on the phone. |
| `ibackup deleted-on-phone to-deleted <asset-ids...>` | Move selected photos into the `Deleted\` recycle-bin folder. |
| `ibackup deleted-on-phone restore <asset-ids...>` | Restore photos from `Deleted\` back into the album tree. |
| `ibackup deleted-on-phone purge <asset-ids...> --confirm` | Permanently delete selected photos from the archive. |
| `ibackup marks add <id> [--album]` | Stage a photo or album for deletion (nothing is deleted yet). |
| `ibackup marks list` | Show staged marks. |
| `ibackup marks remove <mark-id>` | Cancel a staged mark. |
| `ibackup marks commit --confirm [--purge]` | Apply staged marks: recycle them, or delete permanently with `--purge`. |

Every command accepts `--archive <path>`. To avoid repeating it, set the
`IBACKUP_ARCHIVE` environment variable once per session:

```powershell
$env:IBACKUP_ARCHIVE = "D:\iphone-archive"
ibackup import
```

Commands that delete anything are **safe by default**: `reclaim`,
`deleted-on-phone purge`, and `marks commit` only report what *would* happen
until you add `--confirm`.

### Import options

- `--album-link-mode copy` (default): store a real copy of a photo in each of
  its album folders. Most portable; works on any drive including exFAT.
- `--album-link-mode hardlink`: save space by linking instead of copying, on
  filesystems that support it (NTFS). Automatically falls back to `copy` on
  exFAT/FAT.

---

## Freeing space on your phone (safely)

After a successful backup you can reclaim space:

```powershell
# See what could be deleted (nothing is deleted yet)
ibackup reclaim --archive D:\iphone-archive

# Actually delete from the phone (you will be asked to confirm)
ibackup reclaim --archive D:\iphone-archive --confirm
```

A photo is only offered for deletion if it is already in the archive **and**
passes a fresh integrity check. The app never deletes phone content
automatically, and it never deletes anything from the archive.

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

In the GUI you get the same review as a thumbnail list, with multi-select and the
same two choices. Nothing happens automatically — you always decide.

---

## Frequently asked questions

**Do I need iCloud?**
No. Everything works over USB, entirely on your computer.

**Will it change or compress my photos?**
No. Files are copied exactly as they are on the phone.

**If I delete a photo on my phone, does it disappear from the archive?**
No. The archive is append-only and keeps it.

**Why do some photos appear in more than one folder?**
If a photo is in several albums, a copy is placed in each album folder so every
folder is complete on its own. Use `dedup --report` to see the storage impact,
or use `--album-link-mode hardlink` to save space where supported.

**Can I open the archive in File Explorer?**
Yes. The photos are plain files in plain folders with Windows-safe names, so you
can browse and view them without this app.

**Is there a graphical interface?**
Yes. Alongside the `ibackup` command line, a graphical app (`ibackup-gui`, built
with Qt/PySide6) lets you browse pictures and albums, select multiple items,
move, delete or mark-for-delete pictures and albums, and review what's safe to
delete from the phone. The GUI can do everything the CLI can. Launch it with:

```powershell
ibackup-gui
```

---

## Troubleshooting

- **`device-info` shows no device:** unlock the phone, replug the cable, and tap
  **Trust** on the phone. Make sure iTunes / "Apple Devices" is installed so the
  Apple Mobile Device USB driver is present.
- **Albums are missing (photos went to `_Unsorted`):** album information could
  not be read from this phone/iOS version. Your photos are still fully backed up.
- **Permission errors on an external drive:** make sure you can write to the
  drive, and prefer NTFS or exFAT for large drives.
