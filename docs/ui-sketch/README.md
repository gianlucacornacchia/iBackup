# UI Sketch — iPhone Archive (`ibackup`) GUI

**Status: awaiting user approval.** Per `specifications.md` §16.3 this is a hard
gate: no PySide6 code is written until this sketch is explicitly approved.

Framework: **PySide6 (Qt for Python) 6.7+**, Windows 10/11. The GUI is a *thin
adapter* — every button calls one `AppService` method, the same one the CLI
calls, which is what guarantees feature parity. No business logic lives in the
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
each call guarded by a build check and failing silently:

| Effect | Attribute | Value | Requires |
|---|---|---|---|
| Mica backdrop | `DWMWA_SYSTEMBACKDROP_TYPE` (38) | `DWMSBT_MAINWINDOW` (2) | Win11 build 22621 |
| Rounded corners | `DWMWA_WINDOW_CORNER_PREFERENCE` (33) | `DWMWCP_ROUND` (2) | Win11 build 22000 |
| Dark title bar | `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) | `TRUE` when dark | Win11 build 22000 |

- **Mica** is the signature Windows 11 backdrop: the desktop wallpaper, heavily
  blurred and tinted, showing through the window base layer. Content sits on a
  `LayerFillColorDefault` layer above it.
- Mica degrades on its own to a solid color when the user disables transparency,
  is in Battery Saver, or is on Windows 10 — no extra code needed.
- We keep the **system title bar**. A hand-drawn caption would look custom but
  loses Snap Layouts, accessibility and correct maximize behaviour.
- **Unproven:** Mica behind Qt-painted content may need a translucent Qt
  background. This gets a throwaway probe on Win11 22H2 **before** GUI work; if
  it is not clean, we ship solid `SolidBackgroundFillColorBase` and move on.

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
We deliberately do **not** ship Segoe Fluent Icons: Microsoft's license permits
downloading it for design and development but **not** shipping it, and it is
absent from Windows 10 anyway.

### 0.6 What we are not doing

- **No `qfluentwidgets`.** It is the most complete Fluent widget set for Qt, but
  it is **GPLv3**, which would relicense this MIT application. See ADR-0010.
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

Used by purge, mark-commit and reclaim — the GUI mirror of `--confirm`. Styled
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
- **Follows the system**: light/dark theme and accent color are read from
  Windows and applied live when the user changes them; contrast themes are
  respected rather than overridden.
- **Motion is subtle and short** — 150–200ms ease-out on hover, selection and
  page transitions; nothing bounces, nothing animates for longer than a beat.
- **Sentence case** for every label, title and button ("Free up space", not
  "Free Up Space"), matching Windows 11.

---

## 10. What approval unblocks

Approving this sketch unblocks `ui-sketch-approval-gate` and therefore the
`gui-frontend` todo:

- **Theming first** — `gui/theme.py` (the §0.3 tokens + scoped QSS) and
  `gui/win32_effects.py` (the §0.2 DWM calls), preceded by a throwaway Mica
  probe on Windows 11 22H2 to confirm the backdrop renders behind Qt content.
- **Then the views** — `main_window`, `navigation_pane`, `command_bar`,
  `picture_grid_view`, `thumbnail_loader`, `operations_controller`,
  `deleted_on_phone_view`, `reclaim_view`, `marks_view`, `settings_dialog`,
  and the Qt models.
- **Then** the `ibackup-gui` entry point and `tests/test_gui.py` under
  `pytest-qt` (headless via `QT_QPA_PLATFORM=offscreen`).

Requires **PySide6 >= 6.7** for the native `windows11` style (ADR-0010); the
dependency floor is being raised from 6.6.

**Please review and confirm, or tell me what to change.**
