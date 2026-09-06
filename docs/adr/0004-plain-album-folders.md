# 0004. Plain album folders of real files, no symlinks

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

A core requirement is that the archive be browsable and viewable **without this
app**, in Windows File Explorer, and organized by album. The archive must remain
valid when copied to external/portable drives (NTFS/exFAT).

## Decision

Store every asset as a **real, plain file** inside a per-album folder under
`Photos/<Album>/` (album-less assets under `_Unsorted/YYYY/MM/`). An asset in N
albums is placed as a real file in each album folder. **Never use symlinks.** An
optional `--album-link-mode hardlink` may save space on NTFS, auto-falling back
to `copy` on exFAT/FAT.

## Alternatives considered

- **Symlinks for multi-album membership** — rejected: break when copied to
  exFAT/other machines and are poorly supported in Explorer.
- **Single flat store + gallery-only browsing** — rejected: violates the
  app-free, browse-by-album requirement.

## Consequences

- **Positive:** Album folders are self-contained and browsable anywhere; archive
  survives copying across filesystems; no dependency on the app to view photos.
- **Negative / trade-offs:** A photo in N albums costs N copies (unless hardlinked
  on NTFS). Accepted deliberately; `dedup --report` makes the cost visible and
  on-phone re-import is still deduplicated so bytes transfer only once.
