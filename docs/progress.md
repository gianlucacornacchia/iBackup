# Progress Log — iPhone Archive (`ibackup`)

Living status document so work can be **resumed after any interruption**. Update
this whenever a todo changes state or a decision is made. The source-of-truth
task list is the session todo DB / `todos.md`; this file is the human-readable
resume point.

_Last updated: 2026-09-11 (Phase 2 GUI started)._

## Current status

- **Phase:** Phase 2 — building the GUI. Phase 1 (core engine + full CLI) and
  the core-hardening checkpoint are complete offline.
- **State:** the UI-sketch gate **passed on 2026-09-11**; the sketch and its
  clickable mock were approved and `gui-theme` / `gui-frontend` were unblocked.
  `gui-frontend` has been broken into the twelve steps listed in §"Phase 2 GUI
  steps" below and in `plan.md` §2b.
- **Next action on resume:** continue the Phase 2 step list in order. Step 1
  (`gui-scaffold`) is done; step 2 is `gui-theme`, then `gui-worker`.
- **Not yet validated:** real-iPhone *destructive* behaviour, Mica and native
  window chrome, the Windows `.exe` packaging and the Windows CI workflow. The
  read path **has** now been exercised against a real iPhone 12 (see the
  hardware-validation entries below); everything else is Linux + fake device.
- **Release:** packaging is step 12 and has not started. `ibackup-gui` now
  exists as a real entry point that opens the window shell.

## Phase 2 GUI steps

Ordered, one commit each, bottom-up with tests. Full descriptions in `plan.md`
§2b; live state is in the todo DB and `todos.md`.

| # | Step | State |
|---|---|---|
| 1 | `gui-scaffold` — package, entry point, window shell, offscreen tests | **done** |
| 2 | `gui-theme` — WinUI tokens, light/dark, Mica on Windows | next |
| 3 | `gui-worker` — thread owning `AppService`, progress/cancel | pending |
| 4 | `gui-models` — lazy-paging asset/album models, selection scope | pending |
| 5 | `gui-thumbnail-loader` — background previews, bounded cache | pending |
| 6 | `gui-shell` — navigation, pages, command bar, status bar | pending |
| 7 | `gui-gallery` — grid, multi-select, viewer | pending |
| 8 | `gui-ops-safe` — import, verify, scan, dedup, move | pending |
| 9 | `gui-ops-destructive` — typed-DELETE gating, deleted/marks/reclaim | pending |
| 10 | `gui-settings` — six panels; also closes `settings-store` | pending |
| 11 | `gui-parity-tests` — fails if any CLI action lacks a GUI surface | pending |
| 12 | `gui-packaging` — PyInstaller `.exe` | pending |

Step 3 is the risk concentration: `AppService` is single-thread affine and holds
an exclusive archive lock, so the threading backbone is isolated in one step
rather than spread across the views.

### Final core-hardening validation report

2026-09-09, Linux host, Python 3.12, source revision `96a17e8`:

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest --cov=iphone_archive --cov-report=term-missing --cov-fail-under=85 -rs` | 351 passed, 1 skipped; 90.79% coverage. |
| `.venv/bin/ruff check .` | Passed. |
| `.venv/bin/ruff format --check .` | Passed, 85 files formatted. |
| `.venv/bin/python -m mypy --strict src/iphone_archive/core src/iphone_archive/catalog` | Passed, 17 modules. |
| `.venv/bin/python -m mypy src/iphone_archive` | Passed, 36 modules. |
| `.venv/bin/python -m mypy --platform win32 src/iphone_archive` | Passed, 36 modules; static analysis, not Windows execution. |
| `.venv/bin/python -m pip check` | No broken requirements. |
| `git diff --check` | Passed. |

The skipped parametrized case is purge at the final-publication checkpoint:
purge never publishes a final media filename. Other crash boundaries include
actual subprocess termination, disk-full/ownership-write faults, and restart
recovery. The batch-journal scaling regression requires doubling the selection
to write less than 2.2 times the journal bytes.

Independent review's archive-ownership and quadratic-journal findings are
resolved and re-reviewed. Its device/import findings prompted primary-album
association for repair copies, retention of restored missing copies, and an
indexed presence query, with additional regression coverage.
Do not infer Windows CI, live-device, or release qualification from this report.

## Approval gates (must not be passed without explicit approval)

1. **Docs approval** — before writing any code. _(approved)_
2. **UI-sketch approval** — before writing any GUI code. _(next gate — blocking)_

## How to resume

1. Read this file, then `docs/plan.md` (plan) and `docs/todos.md` (checklist).
2. Set up the dev env per `docs/development.md` (create/activate `.venv`,
   `pip install -e ".[dev]"`).
3. Find the next actionable todo (dependencies done, status pending).
4. Implement it **with tests**, run `pytest`, then update this file and
   `todos.md`.

## Milestones

- [x] Phase 0 — documentation complete (specs, user README, user-stories,
      structure, unit-tests, development, plan, todos, progress).
- [x] Docs approved.
- [x] Phase 1 — core + CLI offline baseline.
- [x] Core hardening and offline regression validation.
- [ ] Windows/iPhone read, album and large-video validation.
- [ ] Controlled real-phone destructive/recovery qualification.
- [~] UI sketch produced (`docs/ui-sketch/`); **approval pending**.
- [ ] Phase 2 — GUI.
- [x] Current offline core/CLI suite green (GUI tests do not exist yet).
- [ ] Windows packaging (`.exe`).

## Change log

- 2026-09-11 — **UI-sketch gate passed; Phase 2 started.** The user approved
  both `gui-theme` and `gui-frontend` and asked for the GUI work to be broken
  into smaller steps. `gui-frontend` is now twelve ordered steps (`plan.md` §2b)
  with dependencies recorded in the todo DB, so no step starts before the layer
  beneath it is proven.
- 2026-09-11 — **Step 1 `gui-scaffold` complete.** Added
  `src/iphone_archive/gui/` with `application.py` (QApplication bootstrap, style
  selection, `--help` without Qt, readable message on a broken PySide6 install)
  and `main_window.py` (window shell, page stack, status bar). Restored the
  `ibackup-gui` entry point, now backed by real code. `tests/test_gui.py` runs
  headless under `QT_QPA_PLATFORM=offscreen`; one test asserts that importing
  `iphone_archive.gui` does **not** import Qt, so a broken Qt install can never
  take the CLI down with it. 377 passed, 1 skipped; ruff and mypy clean.

- 2026-09-10 — **Video thumbnails implemented** (`future-video-thumbnails`,
  one of the two gaps raised at the UI-mock review). `thumbnails` now extracts a
  poster frame with PyAV, whose wheels bundle FFmpeg so Windows needs no system
  install. Two correctness points were settled against the ffmpeg CLI rather
  than by assumption: the display-matrix rotation is applied so portrait iPhone
  clips are not sideways (verified pixel-identical to ffmpeg's autorotate for
  0/90/180/270), and the decoder walks forward from the seek keyframe to the
  target instead of returning the keyframe itself, which was silently producing
  black frames. A nearly-black poster frame also triggers a bounded scan for a
  brighter one. `av>=12` is now a declared dependency and is imported lazily, so
  a missing install degrades videos to a placeholder without affecting image
  thumbnails. The UI mock was updated to match: video tiles carry a duration
  badge instead of the word "video".

- 2026-09-10 — **Built a clickable UI mock** in `docs/ui-sketch/mockup/` using
  the selected framework (PySide6), covering every screen in the sketch and
  navigable between them: navigation pane with counts and selection pill,
  thumbnail grid with multi-select, import/verify progress, deleted-on-phone
  review, reclaim, typed-DELETE confirmation, viewer, marks queue and the
  six-panel settings dialog. Rendered 20 reference screenshots (light + dark)
  via `capture_screens.py`. The mock is a **review artifact only** — fake data,
  no imports from `iphone_archive`, excluded from lint/type/test — so the
  UI-sketch approval gate remains closed and no application GUI code exists.

- 2026-09-10 — **First run against a real iPhone** (iPhone 12, iOS 26.4, 1297
  items, 5.55 GB). Import, dedup, incremental fast-skip, verification, HEIC
  thumbnails and the archive layout all behaved correctly on real data.
  **Fixed a real defect**: album membership was completely broken on device
  because the Photos.sqlite album/asset join table ordinal (`Z_28ASSETS`) is
  version-specific and is `Z_33ASSETS` on iOS 26; it is now discovered at
  runtime and filtered to user albums (`ZKIND = 2`). Album coverage went from
  0 to 750 items across 67 albums. Measured ~34 MB/s transfer and a fixed ~36 s
  enumeration cost caused by copying the 1 GB Photos.sqlite on every run.
  Confirmed `reclaim` still cannot delete from the phone (by design) and left
  the device untouched. See ADR-0008.

- 2026-09-09 — Completed offline hardening and final quality gates above.
  Imports and edits now establish durable private staging before creating media,
  persist bounded ownership records before no-clobber publication, and recover
  normal creation/claim-write failures without blocking archive reopen.
  Journal metadata writes scale linearly with batch size. Repair copies retain
  album scope; missing catalogued files restored by import are not discarded
  as duplicates. Added indexes for per-asset files, album/location queries and
  per-asset source presence. Real AFC deletion is hard-disabled and the inspected
  adapter dependency is pinned to `pymobiledevice3==11.10.4`. No GUI approval,
  live-device qualification or packaged release is implied.
- 2026-09-09 — Corrected implementation versus requirements throughout docs;
  added core-hardening, hardware and scheduled release gates. Current commands,
  test/module inventories and GUI parity contract reconciled. Accepted ADR
  bodies preserved; ADR-0011 corrects licensing/interop rationale and requires
  observable DWM fallback. No GUI approval, hardware pass or release claimed.
- 2026-09-09 — Implementation pass confirms typed `DELETE`, selected reclaim
  (`--asset`), source-album moves (`--from-album`), cache/marks clear, complete
  settings APIs, OS-exclusive single-session locks with thread ownership,
  Event cancellation/last-256 progress snapshots, service-applied import/
  thumbnail settings and configured rotating CLI command start/completion/error
  logs with handler cleanup. Browse queries handle partial recycling and
  active/deleted paths/counts. CI explicitly uses `.venv` and `mypy --strict`;
  this configuration is not evidence of a passed Windows run. Final execution
  evidence remains to be recorded above; hardware and GUI gates remain closed.

- 2026-09-07 — **UI direction set: modern Windows 11 Fluent, not stock Qt.**
  Researched and recorded **ADR-0010**. Key findings: Qt **6.7** ships a native
  `windows11` QStyle (and defaults to it on Win11), so the dependency floor was
  raised from PySide6 6.6 to **6.7**; **qfluentwidgets is GPLv3**, so it is
  originally described as license-incompatible (corrected by ADR-0011: MIT is
  GPL-compatible, but this distribution does not adopt GPL obligations);
  **Segoe Fluent Icons may
  not be redistributed**, so MIT `fluentui-system-icons` is used instead.
  Sketch §0 now specifies the Mica/rounded-corner/dark-caption DWM calls, the
  WinUI type ramp, 4/8px radii and exact light/dark color tokens, and the
  layout idiom (**menu bar removed**, NavigationView + command bar). Added a
  `gui-theme` todo that must land before `gui-frontend`, starting with a Mica
  probe. Still holding at the UI-sketch approval gate.

- 2026-09-07 — Closed the configuration gap: added **`settings.py`** (persisted
  preferences in `%APPDATA%\ibackup\settings.json`, outside the archive),
  `app_service_get_settings` / `app_service_update_settings`, and the
  **`ibackup config get|set|list|reset|path|forget`** command. The first archive
  created becomes the default, so `--archive` can be omitted. Validation refuses
  any value that would weaken safety (`confirm_word_required` cannot be turned
  off). An autouse fixture isolates tests from the real user profile.
  **205 tests green at that checkpoint.** Later review identified runtime
  settings/log/confirmation wiring gaps; current hardening status is above.

- 2026-09-07 — Wrote the **UI sketch** (`docs/ui-sketch/README.md`): main window,
  import progress, deleted-on-phone review, reclaim, destructive confirmation,
  marks queue, single-photo viewer, plus a full **CLI-to-GUI parity map**.
  **Holding at the UI-sketch approval gate.**

- 2026-09-07 — **Phase 1 delivered.** Implemented, in dependency order and each
  with its own tests + commit: project scaffold, name-safety, hashing, catalog
  (schema/repository/sidecars), config + logging, archive layout, device layer
  (AFC + fake), importer (two-pass with fast-skip), verifier, dedup, phone-diff,
  recycle bin, reclaim, albums, gallery, thumbnails, the `AppService` facade
  with marks + multi-select, and the Typer CLI. Added the golden end-to-end and
  crash-resume suite. **179 tests, 91% coverage, ruff + mypy clean.**
  `IBACKUP_FAKE_DEVICE` / `IBACKUP_ARCHIVE` allow the whole CLI to be exercised
  without an iPhone.

- 2026-09-07 — Adopted **architect top-5 workflow additions**: Windows CI
  (ruff + `mypy --strict` + pytest + **coverage gate**), **pre-commit** hooks,
  **ADR folder** (`docs/adr/`, migrated 8 existing decisions), **`hypothesis`**
  property tests for name-safety + hashing, and a **golden E2E + crash-resume**
  test (`tests/test_e2e.py`). Remaining recommendations saved as `future-*`
  backlog todos (schema migrations, audit log, catalog repair, release
  checklist, dependency hygiene, destructive-op guardrails).
- 2026-09-07 — Initialized **git version control**; committed docs in logical,
  story-telling steps (gitignore → README/development → progress → workflow
  rules). Adopted **incremental-commit / no-push** rule. Stray `report.*.json`
  tool dumps are git-ignored.
- 2026-09-07 — Target set to **Windows-only**; stack fixed to **Python +
  PySide6**; added deleted-from-phone review + `Deleted/` recycle bin; added
  performance/scalability analysis and import fast-skip; added dev-docs
  (development.md, README.md) and this progress log; adopted **venv** and
  **run-tests-after-coding** and **keep-docs-updated** rules.
- 2026-09-07 — Phase 0 documentation drafted and consolidated into `docs/`.

## Notes / open items

- Project license: MIT. Bundled dependencies retain separate obligations;
  Qt/icon release notices and compliance review remain required (ADR-0011).
- Confirm `pymobiledevice3` AFC behavior on target iOS versions for
  `Photos.sqlite` album extraction (best-effort fallback to `_Unsorted`).
