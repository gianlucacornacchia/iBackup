# 0008. Device access via `pymobiledevice3` (AFC)

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The app must read photos/videos (and best-effort album metadata from
`Photos.sqlite`) from a USB-connected iPhone on Windows, and delete phone-side
files during guarded space reclamation. iOS exposes media over the AFC (Apple
File Conduit) service; access requires the device to be paired/trusted.

## Decision

Use **`pymobiledevice3`** (pure-Python) over the **AFC media domain** for
enumerate/pull/delete and to read `Photos.sqlite` when reachable. On Windows the
underlying **Apple Mobile Device USB driver** (from iTunes / "Apple Devices") is
required. All device I/O is wrapped behind a `device/` interface so logic can be
tested with a fake device.

## Alternatives considered

- **`ifuse`/`libimobiledevice` mount** — rejected: Linux-oriented and requires a
  FUSE mount; not the Windows path.
- **iTunes/Apple APIs or iCloud** — rejected: not a local, scriptable media
  pipeline; iCloud dependency violates the local-only principle.

## Consequences

- **Positive:** Pure-Python, no FUSE mount, scriptable enumerate/pull/delete;
  album metadata when AFC exposes `Photos.sqlite`; testable behind an interface.
- **Negative / trade-offs:** Depends on the Apple USB driver being installed and
  the device trusted; `Photos.sqlite` may be unreadable on some iOS versions
  (album parsing is best-effort, falling back to `_Unsorted/`); transfer is
  bounded by USB 2.0 on Lightning devices.
