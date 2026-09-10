# iPhone Archive — Tests and Validation Plan

Status: offline core/CLI hardening and its regression checkpoint are complete.
The GUI, real-iPhone behavior and Windows release are **not validated**.
Use the final validation report in [progress](progress.md), not stale copied
test counts, for executed commands/results.

## 1. Running existing tests

With the project virtual environment active and dev dependencies installed:

```powershell
pytest tests\test_importer.py tests\test_service.py tests\test_cli.py
pytest
pytest --cov=iphone_archive
```

Choose targeted existing tests after code changes; run the full configured
quality gates for a checkpoint. Docs-only edits need no Python test run.
The suite uses fake devices and pytest `tmp_path`; configure a project-local
test base when the execution environment prohibits system temporary folders.
GUI tests will use `QT_QPA_PLATFORM=offscreen` after approval and implementation;
there is no `tests/test_gui.py` to run now.

## 2. Existing test inventory

This table names actual files and their area, not a claim that every possible
scenario is covered or that the latest edited suite has passed.

| File (`tests/`) | Area |
|---|---|
| `test_config.py` | Archive path initialization/resolution. |
| `test_settings.py` | Settings persistence, defaults, validation, CLI config behavior. |
| `test_logging_setup.py` | Logging configuration and operation output. |
| `test_hashing.py` | Streaming hashes, known inputs and property checks. |
| `test_name_safety.py` | Sanitization, reserved names, collisions and property checks. |
| `test_archive_layout.py` | Placement, hardlink/copy behavior and safe paths. |
| `test_catalog.py` | Schema and repository behavior; upgrade coverage must track migrations. |
| `test_sidecar.py` | Metadata serialization/round trip. |
| `test_device.py` | Fake-device protocol plus mocked AFC behavior, not hardware evidence. |
| `test_importer.py` | Import/skip/dedup, album placement, process-exit recovery after placement/extra copy/sidecar, and refusal of ambiguous recovery files. |
| `test_dedup.py` | Read-only duplicate/storage reports. |
| `test_verifier.py` | Intact, missing and corrupted cataloged copies; no `--full` mode. |
| `test_albums.py` | Archive album summaries, not real `Photos.sqlite` compatibility. |
| `test_phone_diff.py` | Inventory/absence reconciliation. |
| `test_reclaim.py` | Device/content eligibility, selected reclaim, fresh checks and fail-closed deletion regressions. |
| `test_gallery.py` | Asset/album read models, partial recycling and location-filtered paths/counts, not HTML output. |
| `test_thumbnails.py` | Still-image generation/cache, video poster frames (orientation checked against ffmpeg, dark lead-in skipped, missing PyAV degrades), and unsupported-media behavior. |
| `test_progress.py` | Progress and cancellation handle. |
| `test_service.py` | Facade, recycle/restore/purge/reclaim, selection, locks/thread ownership. |
| `test_marks.py` | Stage/unmark/commit behavior. |
| `test_selection.py` | Partial/batch moves, conflicts, preflight and interrupted-operation recovery, including subprocess exit/restart rollback. |
| `test_recycle.py` | Partial recycle/restore/purge, invalid paths, missing copies, sidecar-failure recovery and committed-operation restart finalization. |
| `test_cli.py` | Command parsing, errors, confirmation and service wiring. |
| `test_e2e.py` | Offline pipeline and selected crash/resume scenarios. |

`test_reclaim.py`, `test_recycle.py` and `test_selection.py` were added in core
hardening; related integration cases remain in service/E2E files. Their presence
is not a claim of a completed final validation run. Result DTOs
live with their owning modules, not `service/results.py`.

Shared `conftest.py` fixtures are `isolated_settings`, `catalog_connection`,
and `sample_media`; other service/device fixtures are local to individual tests.

## 3. Core-hardening acceptance coverage

The checkpoint must record pass/fail evidence for these requirements, including
new regression tests where existing tests do not cover them:

- Device-scoped, many-to-one identities; same path on different phones; renamed
  and duplicate content; legacy migration; unknown newer schema rejection.
- Incomplete/failed/cancelled scans do not publish absence; `_Unsorted` fallback
  is observable for unavailable/unsupported album metadata.
- Bounded AFC file reads and deterministic resource closure after errors,
  cancellation and early exit; large-video byte-count/hash preservation.
  Cover supported async-library adaptation with a persistent session event
  loop, not a new loop for each chunk, and `device_close`/context-manager paths.
- Reclaim rejects stale/changed source bytes, recycled-only/missing/corrupt
  archive copies and unselected assets; failed candidates report reasons.
  Preview and cancellation delete nothing; real AFC deletion fails closed.
- Archive copy/sidecar/catalog failures, conflicts and retries; recovery after
  partial recycle/restore/purge; preserving valid copies and album memberships.
  Recovery must refuse external replacements even with identical bytes, while
  private staging makes ordinary creation/ownership-record-write interruptions
  recoverable. Fault-inject ENOSPC/fsync errors and actual process exits at
  those boundaries. Measure journal bytes to ensure linear batch scaling.
- Aligned `AssetView.file_ids`/paths and `list --files`; mutually exclusive
  `marks add --file`/`--album`; file-scoped commit preserves unselected copies.
  Source-album moves differ explicitly from default all-active-copy moves.
  Recycled-only purge preserves Photos copies of partially recycled assets;
  mismatched explicit file IDs fail rather than broadening selection.
  CLI repeated `--file ID` forwards copy selection with required asset IDs.
  `--device UDID` selects device-info/import/scan/reclaim and scopes deleted
  reports with or without rescan.
- Typed `DELETE` required for permanent archive deletion and confirmed
  reclaim; absent/wrong/EOF input aborts. Reversible mark commit retains its
  explicit `--confirm`. Settings cannot weaken this policy.
- Process/session exclusivity, worker-owned SQLite, Event cancellation and
  cleanup; selected reclaim, marks clear, thumbnail cache clear and operation
  logs with actual settings applied.

Unit success does not prove power-loss durability or Windows filesystem
behavior. Identify tested failure boundaries rather than promising universal
atomicity. An immutable audit trail and catalog rebuild are separate work.

## 4. Windows/iPhone validation gate

**Required before enabling destructive reclaim on real phones.** All rows are
pending until a dated report identifies Windows build, iPhone model, iOS
version, Apple driver, dependency versions and filesystem. Use a disposable
library with an independent verified backup, not personal irreplaceable media.

| Matrix area | Required checks / evidence |
|---|---|
| Windows 10 and 11 connectivity | Trust/untrusted/locked phone, reconnect/disconnect, multiple devices, correct UDID, driver errors. |
| Read/import | JPEG/HEIC/video/Live Photo components available via AFC; byte counts and independent hashes; no assumption that cloud-only originals are local. |
| Album metadata | Supported and unsupported `Photos.sqlite` schemas, WAL/snapshot consistency, inaccessible DB, explicit warnings and `_Unsorted` fallback. |
| Large videos | Multi-GB files, measured bounded read sizes/peak memory, interruption/retry, no truncation, handles closed. |
| Archive filesystems | NTFS copy/hardlink and exFAT copy/fallback, long/colliding paths, disk-full and access-denied behavior. |
| Inventory/identity | Two phones with reused paths, same content under multiple identities, cancelled scans, source changed after preview, migration from prior schema. |
| Destructive safety (separate approved test) | Fresh validation immediately before selected delete, residual hash-to-unlink race, typed confirmation, cancellation, disconnect, recovery and phone Photos consistency after deletion. |

Read/album/large-video rows must pass **before** even considering real-phone
destructive tests. AFC file removal is not assumed equivalent to a supported
Apple Photos deletion workflow; validate photo-library consistency and
recoverability before lifting the gate. An offline fake delete is not enough.

## 5. GUI and release gates (future)

After explicit sketch approval, test worker-owned service lifetime, queued
signals, cancellation/shutdown, serialized mutations, bounded thumbnail
queues, the full parity map, accessibility and theme fallback. Perform the
Mica probe on Windows 11 only after approval and retain its result/logs.

Release requires passing Windows CI, a Windows-built CLI executable smoke test
on a clean machine without Python, dependency/license notices, versioned
artifacts, and separately validated GUI packaging when it exists. Until then,
do not advertise a downloadable installer or portable release.
