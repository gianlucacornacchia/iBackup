# 0002. Target Windows only (drop Linux)

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The product was initially framed as "Linux-first". The author later decided they
do not need Linux support and want to focus effort on a single platform.

## Decision

Target **Windows 10/11 (64-bit) only**. Remove Linux-specific framing, tooling,
and instructions (apt, `ifuse`/mount, ext4) from the docs. Device access uses the
Apple Mobile Device USB driver shipped with iTunes / "Apple Devices".

## Alternatives considered

- **Cross-platform (Linux + Windows)** — rejected: doubles the device-access,
  packaging, and filesystem test matrix for no current benefit to the author.
- **macOS** — out of scope; Apple Photos already serves that platform.

## Consequences

- **Positive:** One packaging target (PyInstaller `.exe`), one filesystem story
  (NTFS/exFAT), Windows-safe naming becomes the single primary requirement,
  simpler CI (`windows-latest`).
- **Negative / trade-offs:** No Linux users; if cross-platform is needed later it
  must be re-introduced. Mitigated by keeping the core in portable Python and
  isolating device access behind an interface.
