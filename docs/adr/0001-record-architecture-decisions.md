# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The project made several significant, hard-to-reverse decisions during the
documentation phase (platform, stack, storage model, hashing, device access).
They were recorded only as running "Update —" notes inside `plan.md`, which is
hard to search and mixes decisions with plan narrative.

## Decision

Capture each significant decision as a numbered **Architecture Decision Record**
under `docs/adr/`, using a lightweight MADR-style template. Existing decisions
are migrated into ADRs 0002–0009. New significant decisions get a new ADR; to
change one, add a superseding ADR rather than editing the accepted record.

## Alternatives considered

- **Keep decisions in `plan.md`** — rejected: not greppable, no clear status,
  decisions get buried and edited in place, losing history.
- **A single `DECISIONS.md`** — rejected: grows unwieldy and loses the
  one-decision-per-file, supersede-don't-edit discipline.

## Consequences

- **Positive:** Decisions are discoverable, individually versioned, and carry
  explicit status and rationale; onboarding is faster.
- **Negative / trade-offs:** A small process cost — remember to add an ADR when a
  significant decision is made, and keep the index in `README.md` current.
