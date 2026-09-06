# Architecture Decision Records (ADRs)

This folder captures the **significant, hard-to-reverse decisions** for iPhone
Archive (`ibackup`) as first-class, greppable records. Each ADR is immutable once
`Accepted`; to change a decision, add a new ADR that **supersedes** the old one
(update the `Status` line of both).

Format: a lightweight [MADR](https://adr.github.io/madr/)-style template
(`0000-template.md`). Keep ADRs short — context, the decision, and its
consequences.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-windows-only-target.md) | Target Windows only (drop Linux) | Accepted |
| [0003](0003-python-pyside6-stack.md) | Python core + PySide6 GUI | Accepted |
| [0004](0004-plain-album-folders.md) | Plain album folders of real files, no symlinks | Accepted |
| [0005](0005-sqlite-catalog-plus-sidecars.md) | SQLite catalog + per-asset JSON sidecars | Accepted |
| [0006](0006-sha256-integrity-and-dedup.md) | SHA-256 for integrity and dedup | Accepted |
| [0007](0007-append-only-with-recycle-bin.md) | Append-only archive with a `Deleted/` recycle bin | Accepted |
| [0008](0008-pymobiledevice3-device-access.md) | Device access via `pymobiledevice3` (AFC) | Accepted |
| [0009](0009-headless-service-layer.md) | Headless `service/` layer shared by CLI and GUI | Accepted |

## Conventions

- Filename: `NNNN-kebab-title.md` (4-digit, monotonically increasing).
- One decision per ADR. Number is permanent even if the ADR is later superseded.
- Statuses: `Proposed` → `Accepted` → (`Deprecated` | `Superseded by ADR-NNNN`).
