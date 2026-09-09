# Progress Log — iPhone Archive (`ibackup`)

Living status document so work can be **resumed after any interruption**. Update
this whenever a todo changes state or a decision is made. The source-of-truth
task list is the session todo DB / `todos.md`; this file is the human-readable
resume point.

_Last updated: 2026-09-09 (core-hardening review checkpoint)._

## Current status

- **Phase:** core-hardening checkpoint complete offline.
- **State:** documentation approved; source safety corrections and offline
  regression/quality gates completed. Historical counts describe past runs only.
- **Next action on resume:** perform the Windows/iPhone read/album/large-video
  matrix before considering destructive real-phone reclaim, or obtain explicit
  UI-sketch approval before beginning GUI work.
- **GUI:** sketch written, **HARD BLOCKED on explicit approval**. Review/fix
  requests do not grant GUI approval. The Windows Mica probe, GUI code, entry
  point and GUI tests are all unimplemented/blocked.
- **Not yet validated:** real-iPhone behaviour (`AfcDevice` has never run
  against hardware), the Windows `.exe` packaging, and the Windows CI workflow —
  development happened on Linux against the offline fake device.
- **Release:** packaging is scheduled, not released. No PyInstaller spec is
  added in this remediation. The broken `ibackup-gui` entry point is removed
  until the actual GUI exists.

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
