# Agent instructions — iPhone Archive (`ibackup`)

Full workflow rules live in `docs/todos.md` (top of file). The essentials:

- Use the `.venv` interpreter (`.venv\Scripts\python`), never the global one.
- After coding, run `ruff check .`, `ruff format --check .`,
  `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` and
  `pytest` (with `QT_QPA_PLATFORM=offscreen`).
- Commit incrementally, one logical step per commit. **Never push.**

## Docs before every commit (mandatory)

No commit may change behaviour without updating the docs it affects **in the
same commit**. Before running `git commit`:

1. List what changed: `git diff --cached --stat` (and `git status`).
2. Check doc freshness: `git log -1 --date=short --format="%ad %h" -- <doc>`
   for each doc below, and compare against code commits since that date.
3. Update every affected doc:

   | Change | Docs to update |
   |---|---|
   | Any change | `docs/progress.md` (new dated entry at top of the log) |
   | User-visible behaviour, CLI command/option, GUI surface | `docs/readme-user.md`, `README.md`, `docs/specifications.md`, `docs/ui-sketch/README.md` §8 parity map |
   | New/renamed module, layering, data flow | `docs/structure.md`, `docs/plan.md` |
   | Catalog schema, archive layout, import/reclaim rules | `docs/specifications.md`, `docs/plan.md` |
   | Tests added/changed | `docs/unit-tests.md` |
   | Dependencies, tooling, packaging | `docs/development.md`, `packaging/README.md`, `README.md` |
   | Todo delivered or new follow-up | `docs/todos.md` |
   | New or changed acceptance criteria | `docs/user-stories.md` |
   | Architectural decision or correction | `docs/adr/` (new ADR or dated addendum; never rewrite accepted ADR bodies) and `docs/adr/README.md` |

4. Stage the docs together with the code, then commit.
