# 0007. Append-only archive with a `Deleted/` recycle bin

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The archive is the long-term source of truth and must never lose content because
a photo was removed from the phone. Yet users still need a way to review assets
that no longer exist on the phone and decide what to do with them, without an
accidental permanent delete.

## Decision

The archive is **append-only**: imported assets remain until the user explicitly
removes them, and phone-side deletion never removes archive files. Deletion from
the phone is surfaced read-only ("deleted from phone"), after which the user
chooses per item to either (1) **move to a `Deleted/` recycle bin** (reversible,
mirrors the album subpath, `archive_state=deleted`, still integrity-verified) or
(2) **purge** permanently — only on explicit confirmation. Phone-side space
reclamation deletes phone files only after they are archived and verified.

## Alternatives considered

- **Mirror phone deletions into the archive** — rejected: turns the tool into a
  sync app and defeats the preservation goal (an explicit non-goal).
- **Immediate hard delete from the archive** — rejected: no safety net for a
  permanent, irreplaceable archive.

## Consequences

- **Positive:** Strong preservation guarantee; a reversible recycle bin; deletes
  are always explicit and confirmed; the phone is never touched during review.
- **Negative / trade-offs:** `Deleted/` consumes space until purged; requires
  `archive_state` / `location` tracking and exclusion of `Deleted/` from album
  browsing while still verifying it.
