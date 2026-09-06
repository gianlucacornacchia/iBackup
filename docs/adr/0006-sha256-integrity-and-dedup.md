# 0006. SHA-256 for integrity and dedup

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The archive must guarantee byte-for-byte preservation (detect any corruption over
time) and detect duplicate content for incremental import. A content hash is
needed for both, and it should be verifiable with standard tools years from now.

## Decision

Use **SHA-256** as the single content hash for both integrity verification and
duplicate detection. Hashing is streamed in chunks (constant memory) and re-run
after each copy to verify the stored file matches the source.

## Alternatives considered

- **MD5 / SHA-1** — rejected: cryptographically broken; poor choice for a
  long-lived integrity guarantee even though collisions are unlikely in practice.
- **BLAKE3 / xxHash** — faster, but less universally available in standard OS
  tooling for independent verification years later; hashing is not the pipeline
  bottleneck (USB transfer is), so speed is not the deciding factor.

## Consequences

- **Positive:** Strong, standard, independently verifiable integrity and reliable
  dedup keyed on `sha256 UNIQUE`.
- **Negative / trade-offs:** Slightly slower than non-crypto hashes, but
  negligible next to USB 2.0 transfer time; the hash is the primary asset key so
  changing it later would require a catalog migration.
