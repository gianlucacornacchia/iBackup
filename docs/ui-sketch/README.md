# UI Sketch — iPhone Archive (`ibackup`) GUI

**Status: awaiting user approval.** Per `specifications.md` §16.3 this is a hard
gate: no PySide6 code is written until this sketch is explicitly approved.

Framework: **PySide6 (Qt for Python)**, Windows 10/11. The GUI is a *thin
adapter* — every button calls one `AppService` method, the same one the CLI
calls, which is what guarantees feature parity. No business logic lives in the
GUI.

---

## 1. Main window

```
+---------------------------------------------------------------------------------------+
| iPhone Archive  -  D:\iphone-archive                                    [_] [O] [X]    |
+---------------------------------------------------------------------------------------+
| File   Archive   Phone   View   Help                                                   |
+---------------------------------------------------------------------------------------+
| [ Import ] [ Verify ] [ Scan phone ] [ Reclaim... ]        Phone: iPhone (connected) o |
+------------------------+--------------------------------------------------------------+
| LIBRARY                | Trip 2024                        [ Sort: date v ] [ Size: M v]|
|  o All photos    1 284 |  +--------+ +--------+ +--------+ +--------+ +--------+       |
|  o Unsorted        312 |  |  IMG   | |  IMG   | | [x]IMG | | [x]IMG | |  MOV   |       |
|  o Deleted on phone 47 |  | 0001   | | 0002   | | 0003   | | 0004   | | 0005   |       |
|  o Recycle bin (Deleted)|  +--------+ +--------+ +--------+ +--------+ +--------+       |
|                     18 |  +--------+ +--------+ +--------+ +--------+ +--------+       |
|                        |  |  IMG   | |  IMG   | |  IMG   | |  IMG   | |  IMG   |       |
| ALBUMS                 |  | 0006   | | 0007   | | 0008   | | 0009   | | 0010   |       |
|  o Trip 2024       420 |  +--------+ +--------+ +--------+ +--------+ +--------+       |
|  o Favourites      118 |                                                               |
|  o Family          260 |  (virtualized grid - thumbnails load lazily from              |
|  o Screenshots     174 |   .ibackup\thumbnails\, video shows a film placeholder)        |
|                        |                                                               |
| MARKS                  |                                                               |
|  o Marked for delete 5 |                                                               |
+------------------------+--------------------------------------------------------------+
| 2 selected - 14.6 MB   [ Move to album... ] [ Mark for delete ] [ Delete... ]           |
+---------------------------------------------------------------------------------------+
| 1 284 assets - 1 302 files - 4 albums - 18 recycled - 47 gone from phone      12.4 GB   |
+---------------------------------------------------------------------------------------+
```

Behaviour:

- **Left navigation** — library scopes, albums (with counts), and the marks
  queue. Selecting an entry repopulates the grid.
  Backed by `app_service_list_albums` / `app_service_stats`.
- **Centre grid** — virtualized thumbnail grid; only visible tiles request a
  thumbnail (`app_service_thumbnail`), so tens of thousands of assets stay
  responsive. Rubber-band drag, `Ctrl+click`, `Shift+click` and `Ctrl+A`
  multi-select. `Enter` / double-click opens the viewer.
- **Selection bar** — appears only when something is selected, showing the count
  and total size; hosts the batch actions.
- **Status bar** — the counters from `app_service_stats`.
- **Toolbar** — the phone-side operations; greyed out with a tooltip when no
  iPhone is connected.

---

## 2. Import progress dialog

```
+-------------------------------------------------+
| Importing from iPhone                      [X]  |
+-------------------------------------------------+
|  Copying IMG_0421.HEIC                          |
|  [##################............]  1 842/4 006  |
|                                                 |
|  Added 1 802   Skipped 38   Duplicates 2        |
|  Errors 0                                       |
|                                                 |
|  Elapsed 06:12      Remaining ~08:40            |
+-------------------------------------------------+
|                        [ Cancel ]  [ Hide ]     |
+-------------------------------------------------+
```

- Runs on a `QThread`; the UI never blocks.
- Wired to `ProgressHandle`: `progress_report` drives the bar, **Cancel** calls
  `progress_cancel` and the import stops at the next safe checkpoint, leaving a
  consistent, resumable archive.
- **Hide** keeps it running with a small progress widget in the status bar.
- The same dialog serves verify, reclaim and thumbnail pre-generation.

---

## 3. "Deleted on phone" review

This is the workflow the user asked for explicitly: see what is gone from the
phone, then choose per item.

```
+---------------------------------------------------------------------------------------+
| Deleted on phone - 47 photos still safe in your archive                                |
+---------------------------------------------------------------------------------------+
| These are in your archive but no longer on the iPhone. Nothing happens automatically.  |
|                                              [ Select all ]  [ Rescan phone ]          |
+---------------------------------------------------------------------------------------+
|  +--------+ +--------+ +--------+ +--------+ +--------+                                |
|  | [x]IMG | | [x]IMG | |  IMG   | |  IMG   | |  MOV   |    Last seen on phone:         |
|  | 0102   | | 0103   | | 0181   | | 0182   | | 0190   |    2026-08-14                  |
|  +--------+ +--------+ +--------+ +--------+ +--------+                                |
+---------------------------------------------------------------------------------------+
| 2 selected                                                                             |
|      [ Keep in archive ]   [ Move to Deleted folder ]   [ Delete from archive... ]      |
+---------------------------------------------------------------------------------------+
```

- **Keep in archive** — dismiss; nothing changes (the default, non-action).
- **Move to Deleted folder** — `app_service_move_to_deleted`; reversible, files
  move to `Deleted\` mirroring their album subpath.
- **Delete from archive** — `app_service_purge`, permanent, and opens the
  confirmation dialog in §5.

---

## 4. Reclaim phone space

```
+---------------------------------------------------------------------------------------+
| Free space on iPhone                                                                   |
+---------------------------------------------------------------------------------------+
| Only photos that are archived AND pass a fresh integrity check are offered here.       |
| Your archive is never modified by this operation.                                      |
+---------------------------------------------------------------------------------------+
|  Safe to delete from phone      3 918 items      11.8 GB                               |
|  Not safe (failed re-check)         4 items       moved to the report below            |
|                                                                                        |
|  [x] IMG_0001.HEIC   4.2 MB   verified 2026-09-07                                      |
|  [x] IMG_0002.HEIC   3.9 MB   verified 2026-09-07                                      |
|  [ ] IMG_0003.MOV   88.1 MB   NOT VERIFIED - will be skipped                           |
+---------------------------------------------------------------------------------------+
|                         [ Cancel ]   [ Delete 3 918 items from iPhone... ]             |
+---------------------------------------------------------------------------------------+
```

- Opens in **dry-run** state; the button is the only path to a real deletion and
  it routes through the confirmation dialog.

---

## 5. Destructive-action confirmation

Used by purge, mark-commit and reclaim — the GUI mirror of `--confirm`.

```
+-------------------------------------------------+
|  Delete 12 photos from the archive?             |
+-------------------------------------------------+
|  This is permanent and cannot be undone.        |
|  Total size: 46.2 MB                            |
|                                                 |
|  Tip: "Move to Deleted folder" is reversible.   |
|                                                 |
|  Type DELETE to confirm:  [__________]          |
+-------------------------------------------------+
|            [ Cancel ]   [ Delete ]  (disabled)  |
+-------------------------------------------------+
```

- The action button stays disabled until the confirmation word is typed.
- **Cancel** is the default focus.

---

## 6. Marks queue

```
+---------------------------------------------------------------------------------------+
| Marked for delete - 5 items (nothing has been deleted yet)                             |
+---------------------------------------------------------------------------------------+
|  IMG_0301.HEIC   Trip 2024     blurry           [ Unmark ]                             |
|  IMG_0302.HEIC   Trip 2024     blurry           [ Unmark ]                             |
|  Album "Screenshots" (174 items)                [ Unmark ]                             |
+---------------------------------------------------------------------------------------+
|          [ Clear all marks ]   [ Move to Deleted folder ]   [ Delete permanently... ]  |
+---------------------------------------------------------------------------------------+
```

---

## 7. Single-photo viewer

```
+---------------------------------------------------------------------------------------+
|  < IMG_0003.HEIC                                                          [X]          |
+---------------------------------------------------------------------------------------+
|                                                                                        |
|                            [ full-size image preview ]                                 |
|                                                                                        |
+---------------------------------------------------------------------------------------+
|  Captured 2026-07-02  -  4.2 MB  -  Albums: Trip 2024, Favourites                      |
|  SHA-256 a3f1...9c   -  Verified 2026-09-07   -  On phone: no                          |
|  D:\iphone-archive\Photos\Trip 2024\IMG_0003.heic        [ Show in Explorer ]           |
+---------------------------------------------------------------------------------------+
|                        [ Move to album... ] [ Mark ] [ Delete... ]      < Prev  Next > |
+---------------------------------------------------------------------------------------+
```

---

## 7b. Settings / Preferences  *(backend built; dialog pending approval)*

The settings **store and CLI now exist** (`settings.py` + `ibackup config
get|set|list|reset|path|forget`), so this dialog is a thin editor over
`app_service_get_settings` / `app_service_update_settings`. It is the only part
of the settings feature still to be built, and it waits on this approval.

```
+-------------------------------------------------------------+
|  Settings                                            [X]     |
+--------------+----------------------------------------------+
| Archive      |  Default archive                             |
| Import       |  [ D:\iphone-archive              ] [Browse] |
| Thumbnails   |  [x] Reopen this archive on startup          |
| Safety       |                                              |
| Advanced     |  Recent archives:                            |
|              |    D:\iphone-archive                         |
|              |    E:\backup-2025                 [ Forget ] |
+--------------+----------------------------------------------+
|                                  [ Cancel ]  [ Save ]        |
+-------------------------------------------------------------+
```

Panels:

- **Archive** — default archive root, reopen-on-startup, recent archives list.
- **Import** — album link mode (`copy` / `hardlink` with automatic exFAT
  fallback), and whether to scan the phone automatically after each import.
- **Thumbnails** — preview size (128 / 256 / 512 px), on-disk cache size with a
  **Clear cache** button (`app_service_clear_thumbnails`).
- **Safety** — require typing `DELETE` for permanent deletion (default on),
  default the deleted-on-phone action to *Move to Deleted folder*, keep reclaim
  in dry-run until explicitly confirmed. These only ever *add* friction; they
  cannot disable a confirmation entirely.
- **Advanced** — log level and a **Open logs folder** shortcut.

Design notes:

- Settings are **user preferences (defaults), never archive semantics**. Nothing
  here can weaken the append-only guarantee or auto-delete anything.
- Stored per-user outside the archive (`%APPDATA%\ibackup\settings.json`) so the
  archive folder stays a pure, portable data directory.
- Backed by `settings.py` and exposed through `app_service_get_settings` /
  `app_service_update_settings`; the CLI equivalent is `ibackup config`.
- Invalid values are refused by the service, so the dialog only has to surface
  the `SettingsError` message. `confirm_word_required` is intentionally shown
  but not switchable off.

## 8. CLI ↔ GUI parity map

Every CLI command has a GUI surface, and both call the same service method.

| Operation | CLI | GUI | Service method |
|---|---|---|---|
| Initialize archive | `init` | File ▸ New archive | `app_service_initialize` |
| Open archive | `--archive` | File ▸ Open archive | `app_service_open` |
| Device info | `device-info` | Toolbar phone indicator | (`device_enumerate`) |
| Import | `import` | **Import** button + §2 | `app_service_import` |
| Verify | `verify` | **Verify** button + §2 | `app_service_verify` |
| Dedup report | `dedup` | Archive ▸ Storage report | `app_service_dedup_report` |
| Albums | `albums` | Left nav ALBUMS | `app_service_list_albums` |
| List assets | `list` | Centre grid | `app_service_list_assets` |
| Unsorted | `list --unsorted` | Left nav ▸ Unsorted | `app_service_list_unsorted` |
| Recycle bin | `list --recycled` | Left nav ▸ Recycle bin | `app_service_list_recycled` |
| Stats | `stats` | Status bar | `app_service_stats` |
| Scan phone | `scan-phone` | **Scan phone** button | `app_service_scan_phone` |
| Deleted on phone | `deleted-on-phone list` | §3 view | `app_service_deleted_on_phone` |
| Move to Deleted | `deleted-on-phone to-deleted` | §3 button | `app_service_move_to_deleted` |
| Restore | `deleted-on-phone restore` | Recycle bin ▸ Restore | `app_service_restore` |
| Purge | `deleted-on-phone purge --confirm` | §3 button + §5 dialog | `app_service_purge` |
| Reclaim | `reclaim [--confirm]` | §4 view + §5 dialog | `app_service_reclaim` |
| Mark | `marks add` | **Mark for delete** button | `app_service_mark(_many)` |
| List marks | `marks list` | §6 view | `app_service_list_marks` |
| Unmark | `marks remove` | §6 **Unmark** | `app_service_unmark` |
| Commit marks | `marks commit --confirm` | §6 buttons + §5 dialog | `app_service_commit_marks` |
| Move selection | `move` | **Move to album...** | `app_service_move_selection` |
| Thumbnail | `thumbnail` | Grid tiles (implicit) | `app_service_thumbnail` |
| Settings | `config list` / `get` / `set` | §7b dialog *(pending)* | `app_service_get_settings` / `app_service_update_settings` |

---

## 9. Interaction rules

- **Nothing destructive happens without an explicit confirmation** (§5), and the
  reversible option is always offered first.
- **Long operations never block the UI** — they run in a `QThread` with progress
  and working cancellation.
- **Read-only by default:** import, verify, scan and browsing never modify or
  delete archived files.
- **Keyboard:** `Ctrl+A` select all, `Ctrl+click` / `Shift+click` extend,
  `Delete` marks (never deletes directly), `F5` refresh, `Esc` clears selection.
- **Empty and error states** are explicit: "No archive open", "No iPhone
  connected — connect via USB, unlock, and tap Trust", "This album is empty".

---

## 10. What approval unblocks

Approving this sketch unblocks `ui-sketch-approval-gate` and therefore the
`gui-frontend` todo: the PySide6 package (`main_window`, `album_list_view`,
`picture_grid_view`, `thumbnail_loader`, `operations_controller`,
`deleted_on_phone_view`, `reclaim_view`, `marks_view`, Qt models), the
`ibackup-gui` entry point, and `tests/test_gui.py` under `pytest-qt`.

**Please review and confirm, or tell me what to change.**
