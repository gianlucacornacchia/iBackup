# 0009. Headless `service/` layer shared by CLI and GUI

- **Status:** Accepted; execution contract clarified by ADR-0011
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The product ships both a CLI (`ibackup`) and a PySide6 GUI (`ibackup-gui`) and
requires **full parity** — the GUI must do everything the CLI can and vice versa.
Long operations need progress and cancellation, and both frontends must present
the same results.

## Decision

Put **all application logic behind a headless `service/` layer**
(`app_service.py` facade + `progress.py` for progress/cancel + `results.py` DTOs +
`selection.py` + `marks.py`). The CLI and GUI are **thin adapters** that only
parse input, call the service, and render UI-agnostic result DTOs. No business
logic lives in `cli.py` or `gui/`.

## Alternatives considered

- **Logic in the CLI, GUI shells out to the CLI** — rejected: brittle parsing,
  poor progress/cancel, awkward structured results.
- **Duplicate logic in each frontend** — rejected: guarantees drift and breaks
  the parity requirement.

## Consequences

- **Positive:** Guaranteed CLI/GUI parity; logic is unit-testable without any UI;
  a future frontend (web, API) reuses the same service; clean separation of
  concerns.
- **Negative / trade-offs:** An extra abstraction layer and the discipline of
  designing UI-agnostic DTOs and a progress/cancel protocol up front.
