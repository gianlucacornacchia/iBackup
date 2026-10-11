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

## Addendum (2026-10-11): iCloud Shared Albums

The decision is unchanged; the AFC read scope grows. Besides user albums
(`ZKIND = 2`), the adapter now reads iCloud Shared Albums (`ZKIND = 1505`)
from the same `Photos.sqlite` copy through the same runtime-discovered join,
and walks `/PhotoData/PhotoCloudSharingData` (the phone's local shared-album
cache) for the members that database names. This is still local USB/AFC
access: no iCloud login or network, and only media iOS has already cached can
be imported. `reclaim` never offers files from that cache. **Not yet validated
on hardware:** `ZKIND = 1505` and the `PhotoCloudSharingData` `ZDIRECTORY`
layout follow known iOS conventions and need a real-iPhone check. See
`specifications.md` §12.1.

## Addendum (2026-10-11): hardware validation of shared albums

Checked the same day against a copy of `Photos.sqlite` from the iPhone 12
(iOS 26.4): the addendum above was **wrong for iOS 26**. No `ZGENERICALBUM`
row has `ZKIND = 1505`; shared albums are `ZSHARE` rows (entity
`CollectionShare`) whose media link via `ZASSET.ZCOLLECTIONSHARE`, not through
the `Z_nnASSETS` join, and `ZSCOPEIDENTIFIER` names the
`PhotoCloudSharingData/<personId>/<GUID>/100CLOUD` folder. The adapter now
reads `ZSHARE` first and keeps `ZKIND = 1505` as an unvalidated fallback for
older iOS; 18 albums and 6,150 items were found. Only a small fraction of
shared media is cached (13 of 1,473 in one album), so uncached members are
imported as low-resolution previews from `/PhotoData/Thumbnails/V2`, upgraded
in place once downloaded. Still local USB/AFC. An end-to-end import run and
the byte-difference between shared copies and DCIM originals remain
unverified.
