# UI Sketch — iPhone Archive (`ibackup`) GUI

**Status: awaiting user approval.** Per `specifications.md` §16.3 this is a hard
gate: no PySide6 code is written until this sketch is explicitly approved.
Review corrections are **not** that approval. The Mica probe is GUI work and is
also blocked. All views and interactions below are requirements, not screenshots
of implemented software. Core-hardening validation is a separate prerequisite.

> **A clickable mock of everything below now exists** in `mockup/`. Run
> `python docs/ui-sketch/mockup/run_mock.py` to click through the real
> interface, or look at the rendered screens in `mockup/screens/`. It is a
> throwaway review artifact built with the selected framework: it uses fake
> data, imports nothing from `iphone_archive`, and performs no operations.
> **It is not application code and does not open this gate.**

Framework: **PySide6 (Qt for Python) 6.7+**, Windows 10/11. The GUI is a *thin
adapter* — every button calls one `AppService` method, the same one the CLI
calls; the parity map and adapter tests must establish parity. No business logic lives in the
GUI.

**Look and feel: a modern Windows 11 app**, not a default cross-platform Qt
window. The visual language is specified in §0 and the rationale is ADR-0010.

---

## 0. Visual design — Windows 11 Fluent

The goal is that the app is indistinguishable in feel from Photos, Settings or
File Explorer on Windows 11. Four things get us there; the first is free.

### 0.1 Native control rendering

Qt 6.7 ships a real **`windows11` QStyle** and makes it the **default style on
Windows 11**, so buttons, checkboxes, scrollbars, sliders and text fields render
with genuine Windows 11 geometry, hover/press states and accent color. We keep
it as the base style and only add QSS where the native style has nothing to say
(surfaces, cards, typography, spacing).

- We do **not** blanket-restyle with `QWidget { ... }` — QSS *wraps* the native
  style rather than replacing it, so a broad reset would strip the very
  nativeness we want.
- On **Windows 10** the style key falls back to the Vista style. The app then
  renders flat-and-modern using the same tokens on solid backgrounds. Accepted
  degradation; Windows 11 is the design target.

### 0.2 Window chrome (Mica, rounded corners, dark caption)

Applied to the top-level `HWND` (from `winId()`) via `DwmSetWindowAttribute`,
each call guarded by a build check and checked for failure. Log the attribute,
result/error and selected solid fallback (ADR-0011); never silently swallow it:

| Effect | Attribute | Value | Requires |
|---|---|---|---|
| Mica backdrop | `DWMWA_SYSTEMBACKDROP_TYPE` (38) | `DWMSBT_MAINWINDOW` (2) | Win11 build 22621 |
| Rounded corners | `DWMWA_WINDOW_CORNER_PREFERENCE` (33) | `DWMWCP_ROUND` (2) | Win11 build 22000 |
| Dark title bar | `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) | `TRUE` when dark | Win11 build 22000 |

- **Mica** is the signature Windows 11 backdrop: the desktop wallpaper, heavily
  blurred and tinted, showing through the window base layer. Content sits on a
  `LayerFillColorDefault` layer above it.
- Select a solid background when unsupported or unavailable, including Windows
  10, transparency-disabled and power-saving configurations. Verify actual Qt
  rendering on the target instead of assuming DWM alone handles every fallback.
- We keep the **system title bar**. A hand-drawn caption would look custom but
  loses Snap Layouts, accessibility and correct maximize behaviour.
- **Unproven:** Mica behind Qt-painted content may need a translucent Qt
  background. Only **after explicit approval**, run a probe on Win11 22H2+
  before implementing the full views. No probe has run. If not clean, retain
  solid `SolidBackgroundFillColorBase` and log the fallback.

### 0.3 Design tokens

Reimplemented from the public WinUI token set — data in `gui/theme.py`, no
third-party code.

**Typography** — Segoe UI Variable (Windows 11), falling back to Segoe UI:

| Role | Size/line height | Weight | Used for |
|---|---|---|---|
| Caption | 12/16 | Regular | Photo metadata, counts under tiles |
| Body | 14/20 | Regular | Default UI text |
| Body Strong | 14/20 | Semibold | Emphasis, selected nav item |
| Body Large | 18/24 | Regular | Empty-state text |
| Subtitle | 20/28 | Semibold | Section headers |
| Title | 28/36 | Semibold | Page titles ("Trip 2024") |

Rules: **Semibold for emphasis, never Bold.** Sentence case everywhere,
including titles and buttons. Never below 14 Semibold / 12 Regular.

**Shape** — `4px` radius on in-page controls (buttons, text fields, list rows,
thumbnail tiles); `8px` on overlays (dialogs, flyouts, menus); `0px` on snapped
or maximized edges.

**Color** — exact WinUI tokens, both themes, following the system setting:

| Token | Light | Dark | Used for |
|---|---|---|---|
| `SolidBackgroundFillColorBase` | `#F3F3F3` | `#202020` | Window base / Mica fallback |
| `LayerFillColorDefault` | `#80FFFFFF` | `#4C3A3A3A` | Content layer over Mica |
| `CardBackgroundFillColorDefault` | `#B3FFFFFF` | `#0DFFFFFF` | Cards, grid backplates |
| `TextFillColorPrimary` | `#E4000000` | `#FFFFFFFF` | Body text |
| `TextFillColorSecondary` | `#9E000000` | `#C5FFFFFF` | Counts, metadata |
| `TextFillColorDisabled` | `#5C000000` | `#5DFFFFFF` | Disabled labels |
| `ControlStrokeColorDefault` | `#0F000000` | `#12FFFFFF` | Control borders |
| `DividerStrokeColorDefault` | `#0F000000` | `#15FFFFFF` | Separators |

The **user's accent color** drives selection, focus rings and the primary
button. It is read from the system rather than hard-coded, and contrast/high
-contrast themes are respected rather than overridden.

**Metrics** — 32px standard control height, 40px navigation/list row height,
16px page margins, 8px gaps inside a group, 4px inside a control.

### 0.4 Layout idiom

Modern Windows apps do **not** use a classic menu bar. The old sketch had
`File Archive Phone View Help`; that is exactly the Win32/Linux tell we are
removing. Instead:

- a **NavigationView-style left pane** (icon + label rows, selection pill,
  collapsible to a 40px icon rail) — as in Settings and Photos;
- a **command bar** across the top of the content area holding the primary
  verbs, with overflow behind a `...` button;
- a **`...` overflow menu** for everything that used to live in menus;
- **content-first layout:** the grid is the page, chrome stays minimal;
- **subtle motion** — 150–200ms ease-out for hover, selection and page changes;
  no bouncing, no long animations.

### 0.5 Iconography

**MIT-licensed `fluentui-system-icons` (SVG)** recolored to the current theme.
Retain its MIT copyright and permission notices. We do **not** bundle Segoe
Fluent Icons/font files; use system-installed fonts where available. Check
actual redistribution rights rather than infer them from a design download.

### 0.6 What we are not doing

- **No `qfluentwidgets`.** It is the most complete Fluent widget set for Qt, but
  its GPL distribution obligations are not chosen for this bundle. MIT is
  GPL-compatible; original MIT code does not lose its license. See ADR-0011.
- **No Material / QDarkStyle skin** — permissively licensed, but Material is a
  different design language and would look no more Windows-native than stock Qt.
- **No frameless custom title bar** — looks bespoke, breaks Snap Layouts.

---

## 1. Main window

Mica backdrop, rounded corners, system title bar, **no menu bar**, and a
NavigationView-style left pane with a selection pill on the active row.

```
 ______________________________________________________________________________________
/                                                                                      \
| (=)  iPhone Archive                                                    [_] [#] [X]   |   <- system caption, Mica
|--------------------------------------------------------------------------------------|
|                    |                                                                  |
|  [o] Search      ^ |   Trip 2024                                        (Title 28)    |
|                    |   420 photos - 3.1 GB                          (Caption, dimmed) |
|  LIBRARY           |  +-------------------------------------------------------------+ |
| |=| All photos1 284|  | (v) Import  (^) Verify  (O) Scan phone  (=) Free up space  ..| |  <- command bar
|  __________________|  +-------------------------------------------------------------+ |
| ( |#| Trip 2024 420|                                                                  |
|  ------------------|   +--------+ +--------+ +========+ +========+ +--------+         |
|    selection pill  |   |        | |        | |        | |        | |  |>    |         |
| |?| Unsorted    312|   |  IMG   | |  IMG   | |  IMG  o| |  IMG  o| |  MOV   |         |
| |x| Deleted-phone47|   | 0001   | | 0002   | | 0003   | | 0004   | | 0005   |         |
| |b| Recycle bin  18|   +--------+ +--------+ +========+ +========+ +--------+         |
| |!| Marked        5|      accent-outlined tiles = selected, with a check circle       |
|                    |                                                                  |
|  ALBUMS            |   +--------+ +--------+ +--------+ +--------+ +--------+         |
| |#| Favourites  118|   |  IMG   | |  IMG   | |  IMG   | |  IMG   | |  IMG   |         |
| |#| Family      260|   | 0006   | | 0007   | | 0008   | | 0009   | | 0010   |         |
| |#| Screenshots 174|   +--------+ +--------+ +--------+ +--------+ +--------+         |
|                    |                                                                  |
|                    |   cards on LayerFillColorDefault, 4px radius, 150ms hover lift   |
|                    |                                                                  |
|                    |  +-------------------------------------------------------------+ |
| |@| Settings       |  | 2 selected - 14.6 MB   [Move to album] [Mark] [Delete...]    | |  <- selection bar
|--------------------+  +-------------------------------------------------------------+ |
| iPhone connected - 1 284 assets - 4 albums - 47 gone from phone            12.4 GB    |
\______________________________________________________________________________________/
       ^ rounded corners (DWMWCP_ROUND)
```

Behaviour:

- **Left navigation** — a NavigationView pattern: icon + label rows at 40px, an
  **accent selection pill** on the active row, section headers in Body Strong,
  counts right-aligned in `TextFillColorSecondary`. Collapses to a 40px icon
  rail via the hamburger, and auto-collapses below ~900px width.
  Backed by `app_service_list_albums` / `app_service_stats`.
- **Command bar** — the primary verbs as icon+label buttons on a card surface,
  with a `...` overflow for the rest. This replaces the old menu bar entirely.
  Buttons that need a phone are disabled with an explanatory tooltip when none
  is connected.
- **Page header** — album name in Title (28/36 Semibold) with a Caption subtitle
  giving count and size, exactly like a Settings page header.
- **Centre grid** — virtualized thumbnail grid; only visible tiles request a
  thumbnail (`app_service_thumbnail`), so tens of thousands of assets stay
  responsive. Tiles are 4px-radius cards that lift subtly on hover. Selected
  tiles get an **accent outline plus a check circle**, the Photos convention.
  Rubber-band drag, `Ctrl+click`, `Shift+click` and `Ctrl+A` multi-select;
  `Enter` / double-click opens the viewer.
- **Selection bar** — slides in only when something is selected (150ms), showing
  the count and total size, and hosting the batch actions.
- **Status bar** — phone state and the counters from `app_service_stats`.
- **Settings** — pinned at the bottom of the nav pane, as in Windows Settings.

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

- Runs on a `QThread` that constructs, opens, uses and closes its own
  `AppService`/SQLite connection. Never share a service across QThreads.
- Wired to `ProgressHandle`: `progress_report` drives the bar, **Cancel** calls
  `progress_cancel` and the import stops at the next safe checkpoint, leaving a
  consistent, resumable archive. Cancellation uses `threading.Event`; queued
  Qt signals deliver progress/results to the UI, never direct worker widget calls.
- **Hide** keeps it running with a small progress widget in the status bar.
- The same dialog serves verify, reclaim and thumbnail pre-generation.
- The archive OS lock permits one open service session, including reads;
  competing sessions fail busy rather than queue. Dispatch operations through
  the owning worker. Progress snapshots retain only the last 256 events.
  Bound thumbnail
  workers, pending requests and decoded cache; discard obsolete scroll requests.
  Shutdown cancels and waits before closing the worker-owned connection.

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
- Pass only selected asset IDs to `app_service_reclaim`; revalidate current
  source bytes and active archive copies at execution. A preview is not a
  deletion authorization. Real AFC deletion remains blocked pending the
  Windows/iPhone validation matrix, even after UI approval.

---

## 5. Destructive-action confirmation

Used by purge, permanent mark-commit and reclaim — the GUI mirror of `--confirm`
plus typed `DELETE`. Reversible mark-commit retains an explicit confirmation,
without pretending its CLI requires the permanent-deletion word. Styled
as a WinUI **ContentDialog**: 8px corners, a smoke-layer scrim dimming the
window behind it, Subtitle-weight heading, and a footer where the destructive
action is the **accent-filled primary button** and Cancel is the standard
button holding default focus.

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
of the planned settings UI and waits on this approval. Stored
`reopen_last_archive` and `default_deleted_action` preferences have no current
GUI consumer. Import/thumbnail defaults are now applied service-side;
the CLI's rotating archive log uses the configured log level.

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
- **Maintenance** — reset settings, show settings path and forget a recent
  archive without deleting its files; each has a CLI counterpart below.

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

Target parity map: GUI surfaces below are **planned** and remain blocked.
Current source CLI actions call the listed service APIs; tests must confirm
selection, defaults and confirmation behavior match.

| Operation | CLI | GUI | Service method |
|---|---|---|---|
| Initialize archive | `init` | **...** overflow ▸ New archive | `app_service_initialize` |
| Open archive | `--archive` | **...** overflow ▸ Open archive | `app_service_open` |
| Device info | `device-info [--device UDID]` | Command-bar device selection, identifier and inventory count | `app_service_device_info(source)` → `DeviceInfo(udid, media_count)` |
| Import | `import [--device UDID]` | **Import** button + §2 for selected device | `app_service_import` |
| Verify | `verify` | **Verify** button + §2 | `app_service_verify` |
| Dedup report | `dedup` | **...** overflow ▸ Storage report | `app_service_dedup_report` |
| Albums | `albums` | Left nav ALBUMS | `app_service_list_albums` |
| List assets/copies | `list [--files]` | Centre grid; selection retains aligned file IDs/paths from the current album/location | `app_service_list_assets` |
| Unsorted | `list --unsorted` | Left nav ▸ Unsorted | `app_service_list_unsorted` |
| Recycle bin | `list --recycled` | Left nav ▸ Recycle bin | `app_service_list_recycled` |
| Stats | `stats` | Status bar | `app_service_stats` |
| Scan phone | `scan-phone [--device UDID]` | **Scan phone** button for selected device | `app_service_scan_phone` |
| Deleted on phone | `deleted-on-phone list [--device UDID] [--rescan]` | §3 device-scoped report/rescan | `app_service_deleted_on_phone(device_udid=...)` |
| Move to Deleted | `deleted-on-phone to-deleted <asset-ids...> [--file ID ...]` | §3 button with explicit asset/copy scope | `app_service_move_to_deleted(file_ids=...)` |
| Restore | `deleted-on-phone restore <asset-ids...> [--file ID ...]` | Recycle bin ▸ Restore selected copies | `app_service_restore(file_ids=...)` |
| Purge | `deleted-on-phone purge <asset-ids...> [--file ID ...] [--recycled-only] --confirm` | §3 asset/copy purge; Recycle bin restricts to deleted copies; §5 dialog | `app_service_purge(file_ids=..., recycled_only=...)` |
| Reclaim selection | `reclaim [--device UDID] [--asset ID ...] [--confirm]` | §4 device/selected rows + §5 dialog | `app_service_reclaim(asset_ids=...)` |
| Mark asset/album/copy | `marks add <id> [--album \| --file]` | **Mark for delete**, with explicit current-copy versus whole-asset scope | `app_service_mark` (`asset`/`album`/`file`), `app_service_mark_many` (assets) |
| List marks | `marks list` | §6 view | `app_service_list_marks` |
| Unmark | `marks remove` | §6 **Unmark** | `app_service_unmark` |
| Clear marks | `marks clear` | §6 **Clear all marks** | `app_service_clear_marks` |
| Commit marks | `marks commit --confirm` | §6 buttons + §5 dialog | `app_service_commit_marks` |
| Move selection | `move <album> <asset-ids...> [--from-album ALBUM_ID] [--file ID ...]` | **Move to album...**, preserving album/copy scope | `app_service_move_selection(file_ids=...)` |
| Thumbnail | `thumbnail` | Grid tiles (implicit) | `app_service_thumbnail` |
| Clear preview cache | `clear-thumbnails` | §7b **Clear cache** | `app_service_clear_thumbnails` |
| Settings | `config list` / `get` / `set` | §7b dialog *(pending)* | `app_service_get_settings` / `app_service_set_setting` (bulk save: `app_service_update_settings`) |
| Reset settings | `config reset` | §7b **Reset settings** | `app_service_reset_settings` |
| Settings location | `config path` | §7b **Show settings file** | `app_service_settings_path` |
| Forget recent archive | `config forget <path>` | §7b **Forget** | `app_service_forget_archive` |

US-D4 HTML gallery is explicitly deferred; there is no current `gallery`
command to map. **Show in Explorer**, viewer navigation, search and theme
controls are planned presentation features, not claimed CLI archive operations.
Album-grid deletion should use the aligned `AssetView.file_ids` for the shown
copies, not silently promote a selection to all copies of an asset. Asset-wide
delete/move must be clearly labeled; `--from-album` is the CLI source-album
move equivalent, while the unqualified CLI move affects all active copies.
Recycle-bin purge must set `recycled_only=True` so partially recycled assets
retain their active copies; this maps to CLI `--recycled-only`.

---

## 9. Interaction rules

- **Nothing destructive happens without an explicit confirmation** (§5), and the
  reversible option is always offered first.
- **Long operations never block the UI** — they run in a `QThread` with progress
  and working cancellation.
- **Preservation by default:** import adds files; verify/scan may update catalog
  metadata, and thumbnails create cache files. None automatically deletes or
  changes original media bytes. Browsing does not require phone access.
- **Keyboard:** `Ctrl+A` select all, `Ctrl+click` / `Shift+click` extend,
  `Delete` marks (never deletes directly), `F5` refresh, `Esc` clears selection.
- **Empty and error states** are explicit: "No archive open", "No iPhone
  connected — connect via USB, unlock, and tap Trust", "This album is empty".
- **Follows the system**: light/dark theme and accent color are read from
  Windows and applied live when the user changes them; contrast themes are
  respected rather than overridden.
- **Motion is subtle and short** — 150–200ms ease-out on hover, selection and
  page transitions; nothing bounces, nothing animates for longer than a beat.
- **Sentence case** for every label, title and button ("Free up space", not
  "Free Up Space"), matching Windows 11.

---

## 10. What approval unblocks

Only explicit approval unblocks `ui-sketch-approval-gate`; core-hardening
contracts must also pass before the GUI implementation starts:

- **Theming first** — `gui/theme.py` (the §0.3 tokens + scoped QSS) and
  `gui/win32_effects.py` (the §0.2 DWM calls), preceded by a throwaway Mica
  probe on Windows 11 22H2 to confirm the backdrop renders behind Qt content.
- **Then the views** — `main_window`, `navigation_pane`, `command_bar`,
  `picture_grid_view`, `thumbnail_loader`, `operations_controller`,
  `deleted_on_phone_view`, `reclaim_view`, `marks_view`, `settings_dialog`,
  and the Qt models.
- **Then** the `ibackup-gui` entry point and `tests/test_gui.py` under
  `pytest-qt` (headless via `QT_QPA_PLATFORM=offscreen`).

The mock in `mockup/` is the reference for layout, wording and interaction, but
it is **not** a starting point for the implementation: it has no service layer,
no threading and no error handling, and it is deliberately excluded from lint,
type checking and the test suite.

Requires **PySide6 >= 6.7** for the native `windows11` style (ADR-0010/0011).
Windows runtime behavior, Qt/icon distribution notices and the packaged GUI
must be validated separately before a release.

**Please review and confirm, or tell me what to change.**
