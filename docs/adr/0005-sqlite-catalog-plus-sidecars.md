# 0005. SQLite catalog + per-asset JSON sidecars

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The archive needs a fast, queryable index (lookup by hash, list by album, track
phone identity and archive state, drive verify/reclaim) that can live for years.
It must also degrade gracefully: the plain photo files must remain usable even if
the index is lost.

## Decision

Use **SQLite** as the source-of-truth catalog, stored in hidden
`.ibackup/catalog.sqlite`, **plus a per-asset JSON sidecar** (`.ibackup/sidecars/
<sha256>.json`) recording hash, size, source, and album membership. The catalog
can be rebuilt from the sidecars + files if it is ever lost.

## Alternatives considered

- **SQLite only** — rejected: a single binary index is a single point of failure
  and is not human-readable for recovery.
- **Sidecars only (no DB)** — rejected: scanning thousands of JSON files per query
  is too slow for import fast-skip, dedup, and verify.
- **Embed metadata in filenames/paths** — rejected: fragile, lossy, and collides
  with Windows-safe naming.

## Consequences

- **Positive:** O(log n) indexed queries for scale; redundant, human-readable
  recovery path; index kept out of the browsable photo folders.
- **Negative / trade-offs:** Two stores to keep consistent (written
  transactionally per asset) and versioned SQLite migrations are needed as the
  schema evolves.
