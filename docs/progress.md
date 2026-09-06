# Progress Log — iPhone Archive (`ibackup`)

Living status document so work can be **resumed after any interruption**. Update
this whenever a todo changes state or a decision is made. The source-of-truth
task list is the session todo DB / `todos.md`; this file is the human-readable
resume point.

_Last updated: 2026-09-07 (Phase 1 — core + CLI complete)._

## Current status

- **Phase:** Phase 1 — core + CLI. **Complete.**
- **State:** docs approved. All core, catalog, device, service, browse and CLI
  modules are implemented, tested and committed. **179 tests green, 91%
  coverage.** `ibackup` runs end to end against a fake device offline.
- **Next action on resume:** the **UI sketch is written**
  (`docs/ui-sketch/README.md`) and the project is **holding at the UI-sketch
  approval gate**. On approval, implement `gui-frontend` (PySide6) exactly as
  sketched, then `tests/test_gui.py`. No GUI code may be written before that
  approval.
- **Not yet validated:** real-iPhone behaviour (`AfcDevice` has never run
  against hardware), the Windows `.exe` packaging, and the Windows CI workflow —
  development happened on Linux against the offline fake device.

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
- [x] Phase 1 — core + CLI.
- [~] UI sketch produced (`docs/ui-sketch/`); **approval pending**.
- [ ] Phase 2 — GUI.
- [ ] Full test suite green.
- [ ] Windows packaging (`.exe`).

## Change log

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

- License: TBD.
- Confirm `pymobiledevice3` AFC behavior on target iOS versions for
  `Photos.sqlite` album extraction (best-effort fallback to `_Unsorted`).
