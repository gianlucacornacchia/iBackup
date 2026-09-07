# 0010. Windows 11 Fluent look without a GPL widget library

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** project owner, assistant

## Context

The GUI must look like a **modern Windows 11 application** (Photos, Settings,
File Explorer), not like a default cross-platform Qt application. A stock Qt
Widgets app on Windows reads as foreign: square corners, a classic menu bar,
grey 3D-ish chrome, the wrong font, and no system backdrop.

Three constraints shape the decision:

1. The project is **MIT-licensed** and intends to ship a redistributable `.exe`.
2. The target is **Windows-only**, so platform-specific APIs are acceptable and
   cross-platform fallbacks are not required.
3. The GUI must stay a **thin adapter** over `AppService` (ADR-0009); theming
   must not leak business logic or force a widget-framework rewrite.

Research findings that drove the decision (verified 2026-09-07):

- **Qt 6.7.0 introduced a real `windows11` QStyle**
  (`qtbase/src/plugins/styles/modernwindows/`), and Qt makes it the **default
  style on Windows 11** (`qwindowstheme.cpp` prepends `Windows11` to the style
  list). On Windows 10 the key falls back to `windowsvista` with a warning.
  Qt also already sets the dark title bar itself via `DwmSetWindowAttribute`.
- **`PySide6-Fluent-Widgets` (qfluentwidgets) is GPLv3** for free use, with a
  paid commercial license. PyPI metadata, the repository `LICENSE`, and the
  README all agree. Bundling it would force our distributed application under
  GPLv3 — incompatible with shipping an MIT app.
- **Segoe Fluent Icons may not be redistributed**: Microsoft's own page states
  the font may be downloaded for design and development *"but you may not ship
  it to another platform."* It also is not present on Windows 10 by default.
- The **WinUI design tokens are public and precisely specified** (type ramp,
  4px/8px corner radii, exact light/dark color hexes in
  `microsoft-ui-xaml/controls/dev/CommonStyles/Common_themeresources_any.xaml`),
  so they can be reimplemented directly without copying any code.
- Windows 11 chrome is reachable from any top-level `HWND` — and a Qt widget's
  `winId()` is one — through `DwmSetWindowAttribute` with documented attributes:
  `DWMWA_USE_IMMERSIVE_DARK_MODE` (20), `DWMWA_WINDOW_CORNER_PREFERENCE` (33),
  `DWMWA_SYSTEMBACKDROP_TYPE` (38, Mica, requires build 22621+).

## Decision

Build the Windows 11 look from **first-party platform behaviour plus our own
Fluent design tokens**, and do **not** take a GPL widget-library dependency:

1. Require **PySide6 >= 6.7** and run on the native **`windows11` QStyle**.
2. Add a `gui/theme.py` holding the **WinUI design tokens** (type ramp, radii,
   spacing, light/dark color tokens) and emitting **narrowly scoped QSS** —
   applied on top of the native style, never a blanket `QWidget { ... }` reset.
3. Add a `gui/win32_effects.py` that calls `DwmSetWindowAttribute` through
   `ctypes` for Mica backdrop, rounded corners and dark mode, each guarded by a
   Windows build check and failing silently into a solid-color fallback.
4. Follow the **Windows 11 app layout idiom**: a NavigationView-style left pane,
   a command bar, and **no classic menu bar**.
5. Use **MIT-licensed `fluentui-system-icons`** (SVG) for iconography instead of
   the non-redistributable Segoe Fluent Icons font.
6. Follow the system light/dark setting and the user's accent color.

## Alternatives considered

- **`PySide6-Fluent-Widgets` (qfluentwidgets)** — by far the most complete
  Fluent widget set for Qt and actively maintained (8k+ stars). **Rejected on
  licensing:** GPLv3 would relicense our distributed application. Revisit only
  if the project relicenses or a commercial license is purchased.
- **Rely on the `windows11` QStyle alone** — free and native, but it styles
  *controls* only. It gives us no Mica, no layered card surfaces, no Fluent
  typography ramp, and no navigation idiom, so the app would still read as a
  generic Qt window. Kept as the base, insufficient on its own.
- **A full custom QSS skin / blanket restyle** (QDarkStyle, qt-material) —
  permissive licenses, but Material or generic-dark is explicitly *not* the
  Windows look, and overriding everything fights the native style. Rejected.
- **A frameless window with a hand-drawn title bar**
  (`PySideSix-Frameless-Window`) — needed for a fully custom caption, but it is
  **LGPLv3**, adds relinking obligations, and hand-drawn captions routinely lose
  Snap Layouts and accessibility behaviour. Rejected; keep the system caption.
- **Rewrite the frontend in WinUI 3 / C#** — the most authentically native
  result, but it splits the project across two languages and runtimes and
  discards the tested Python service layer. Rejected as disproportionate.
- **Web stack (WebView2 + HTML/CSS)** — already rejected in ADR-0003; imitating
  Fluent in CSS is no more native than Qt and adds a second toolchain.

## Consequences

- **Positive:** the app inherits genuine Windows 11 control rendering, dark
  mode, accent color and Mica for very little code; the licensing stays clean
  MIT; no widget-framework rewrite; tokens are data, so themes are testable.
- **Negative / trade-offs:**
  - Requires **PySide6 >= 6.7**, raising the floor from the previous `>= 6.6`.
  - On **Windows 10** there is no `windows11` style and no Mica; the app must
    degrade to the Vista style with solid `SolidBackgroundFillColorBase`
    surfaces. It will look modern-flat, not Fluent. Accepted.
  - Qt Widgets has **no NavigationView, CommandBar or ContentDialog**; those
    patterns must be approximated with composed widgets, which is real work.
  - **Mica on a Qt HWND is not verified end-to-end** — it may additionally
    require a translucent Qt background or extending the frame. This must be
    proven with a throwaway probe on Windows 11 22H2 **before** the GUI build,
    and abandoned to solid colors if it does not work cleanly.
  - Mixing QSS with a native style is documented to wrap, not replace, it; any
    widget we style must be styled completely enough to avoid half-native,
    half-custom rendering. Keep the QSS surface deliberately small.
  - We cannot ship Segoe Fluent Icons, so iconography will be *Fluent-styled*
    rather than the exact system glyphs.
