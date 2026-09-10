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

## Validation against real hardware (2026-09-10)

First test against a physical device: **iPhone 12 (iPhone13,2), iOS 26.4**,
1297 media items, 5.55 GB.

Confirmed working: pairing and lockdown, `/DCIM` enumeration, streamed reads,
SHA-256 hashing, dedup, atomic import, incremental fast-skip, integrity
verification, and HEIC thumbnailing.

Corrected: album membership was **entirely broken** on real hardware. The join
table between albums and assets is named after a Core Data entity ordinal that
changes between iOS releases — `Z_28ASSETS` on the schema we had guessed,
`Z_33ASSETS` on iOS 26 — so the hardcoded query silently matched nothing and
every asset fell back to `_Unsorted/`. The table and its columns are now
discovered at runtime, and only user-created albums (`ZKIND = 2`) are imported,
which excludes untitled smart albums and internal entries such as
`progress-sync`. Result on this device: 67 albums, 750 of 1297 on-device items
mapped.

Measured: sustained AFC read of **~34 MB/s** on large files, plus a **fixed
~36 s enumeration cost** per run that is dominated by copying the 1 GB
`Photos.sqlite`. That fixed cost dominates small incremental imports.

Still unvalidated: deletion from the phone. `AfcDevice.device_delete` refuses
unconditionally, so `reclaim` currently reports candidates and then fails
without freeing anything. Raw AFC unlink under `/DCIM` does not update the
Photos library, which would leave the phone's database inconsistent.
