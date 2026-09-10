# Clickable UI mock

**This is a review artifact, not application code.** It exists so the interface
can be judged before any GUI is built, while `ui-sketch-approval-gate` is still
closed.

What that means concretely:

- it imports **nothing** from `iphone_archive`, and never opens an archive,
  catalog, settings file or iPhone;
- every photo, album, count, size and progress bar is **fake**;
- buttons **navigate and demonstrate behaviour**; they perform no real work;
- it is excluded from `ruff`, `mypy` and `pytest`, and is not packaged.

## Run it

```bash
.venv/bin/python docs/ui-sketch/mockup/run_mock.py
```

Regenerate the reference images in `screens/`:

```bash
# --both writes light and dark; omit for light only, --dark for dark only
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/ui-sketch/mockup/capture_screens.py --both
```

## What you can click

| Try this | What it shows |
|---|---|
| Any row in the left pane | Switches the page; the accent **selection pill** moves |
| Hamburger, top left | Collapses the pane to an icon rail and back |
| Drag across tiles, `Ctrl+click`, `Shift+click`, `Ctrl+A` | Multi-select; the selection bar slides in |
| Double-click a tile | Single-photo viewer with metadata, prev/next |
| **Import** or **Verify** | Progress dialog with working Cancel and Hide |
| **Scan phone** | Reports what is gone from the phone, in the status bar |
| **Free up space** | Reclaim window, opening in dry run |
| **Deleted from phone** | The three-way review: keep / move to Deleted / delete |
| **Marked** | The marks queue, including a whole marked album |
| Any **Delete...** button | Confirmation dialog; the action stays disabled until you type `DELETE` |
| **Settings**, bottom left | All six preference panels |
| **...** overflow ▸ *Simulate: no iPhone connected* | Phone-dependent commands grey out with a tooltip |

## Reviewing it on Windows versus here

The mock is written for Windows 11 but runs anywhere, so what you see depends on
where you run it:

| | On Windows 11 | On this Linux dev box |
|---|---|---|
| Control rendering | Native `windows11` Qt style | Fusion style approximation |
| Mica, rounded corners, dark caption | Applied via `DwmSetWindowAttribute` | Not applied; solid `SolidBackgroundFillColorBase` |
| Font | Segoe UI Variable | First available fallback |
| Text antialiasing | ClearType (subpixel) | Grayscale, to avoid color fringing |
| Scrollbars | Native Fluent | Lightly styled to approximate them |

The status bar always states which of these applied, so a screenshot can never
misrepresent itself. **Layout, hierarchy, wording, colors, spacing and every
interaction are real and reviewable here**; only the native chrome is not.

## Files

| File | Contents |
|---|---|
| `run_mock.py` | Entry point, main window, navigation, command bar, status bar |
| `mock_tokens.py` | WinUI design tokens, type ramp, metrics, scoped QSS |
| `mock_widgets.py` | Drawn icons, navigation delegate, thumbnail grid, command/selection bars |
| `mock_dialogs.py` | Progress, destructive confirmation, viewer, settings |
| `mock_views.py` | Deleted-on-phone review, marks queue, reclaim window |
| `mock_data.py` | The fake library and generated placeholder thumbnails |
| `capture_screens.py` | Renders `screens/` for review without running the app |

## Known deliberate simplifications

These are shortcuts in the **mock**, not proposals for the real GUI:

- Progress runs on a `QTimer`, not a `QThread` with a real `AppService`.
- Thumbnails are drawn gradients, so no image decoding is exercised.
- Icons are drawn with `QPainter`; the real GUI uses the MIT
  `fluentui-system-icons` SVG set (sketch section 0.5).
- The grid holds ~130 fake items, so virtualization is configured but not
  stress-tested. Real libraries are far larger — the test iPhone held 1 297.
- **Video tiles show a generated gradient, but the real poster frame now works.**
  `thumbnail` extracts a rotated frame from `.mov`/`.mp4` via PyAV, so on real
  data these tiles carry an actual still. The duration badge is fake data.
- Reclaim's confirm path deliberately ends in the message the **real** device
  layer produces today: deletion from a real iPhone is still blocked pending
  validation (`device-delete-validation`).
