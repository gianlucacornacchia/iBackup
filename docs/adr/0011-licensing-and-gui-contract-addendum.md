# 0011. Correct licensing rationale and clarify the GUI execution contract

- **Status:** Accepted — addendum to ADR-0003, ADR-0009 and ADR-0010
- **Date:** 2026-09-09
- **Deciders:** Project review corrections; existing product decisions retained

## Context

Accepted ADRs are historical records and are not rewritten. Review found
overbroad licensing/interop claims and missing safety details in the planned
GUI contract. This addendum supersedes only those claims; it does not approve
the UI sketch or authorize GUI implementation.

## Decision

1. **Keep Python/PySide6 and the Fluent design.** MIT is GPL-compatible:
   MIT code may be included in a GPL-covered combined distribution. Choosing a
   GPL widget library would create GPL distribution obligations for that
   combination, not erase the original MIT license. This project chooses not
   to adopt those obligations; it continues without qfluentwidgets. A suitable
   commercial license is a separate option, not a present dependency.
2. **C#/WinUI does not inherently require rewriting Python.** IPC or embedding
   could preserve the service/device core. The rejected alternative adds a
   second runtime, interop and packaging work; the single-language choice
   remains appropriate without claiming a rewrite is unavoidable.
3. **MIT does not describe the whole bundle.** Before release, inventory the
   exact Qt/PySide6 modules and third-party binaries/licenses; include required
   license texts, attribution and notices. For LGPL components, satisfy the
   applicable source/modification and replacement/relinking rights, including
   packaging/EULA restrictions. Verify the frozen distribution actually permits
   the required replacement workflow; do not assume PyInstaller makes it
   compliant. No GPL-only Qt module may be inadvertently bundled.
4. **Icons/fonts:** retain MIT copyright/permission notices for
   `fluentui-system-icons` and any copied licensed assets. Use installed system
   fonts where available; do not bundle Microsoft's Segoe font files without
   appropriate redistribution rights. The old blanket font-license wording is
   not a substitute for checking the actual asset/version/license.
5. **Observable fallback:** DWM calls check platform/build and return values.
   Log unsupported/failed attributes and errors, then use a solid background.
   Do not silently swallow failures or promise Mica always works. Probe on a
   Windows 11 22H2+ machine only **after explicit sketch approval**; the probe
   has not been performed. Windows 10 solid-style fallback remains intended.
6. **Worker-owned service:** construct/open/use/close SQLite and `AppService`
   within the owning worker; never share a connection across QThreads.
   Serialize mutations per archive with cross-process locking. Use Event
   cancellation and queued UI signals; bound thumbnail queues/workers/caches
   and paginate metadata. Full parity needs tests, not merely a shared facade.

## Consequences

Implementation mapping clarification: historical ADR-0004's `dedup --report`
is now simply `dedup`; ADR-0009's proposed `results.py` is not a current file
(DTOs live with their owner modules, listed in `structure.md`). ADR-0006's
constant-memory statement applies to chunked hash buffers only, not process
memory for a whole library. Historical ADR bodies remain intact.

No platform, visual layout or archive-preservation requirement changes. The
GUI remains blocked, real-phone destructive reclaim has a separate hardware
gate, and Windows packaging has a scheduled validation milestone. Release
notices/compliance and Windows behavior require evidence before distribution.
