# iPhone Archive

[![Tests](https://github.com/gianlucacornacchia/iBackup/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/gianlucacornacchia/iBackup/actions/workflows/tests.yml)
[![Build](https://github.com/gianlucacornacchia/iBackup/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/gianlucacornacchia/iBackup/actions/workflows/build.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A permanent, append-only archive for the photos and videos on your iPhone.**

`ibackup` copies media from a USB-connected iPhone into plain files and folders
on your PC or external drive, organised by album. Once a photo is in the
archive it stays there, even after you delete it from the phone. The archive,
not the phone, is the source of truth, and it stays fully browsable in File
Explorer without this app.

> [!WARNING]
> **Alpha software.** The CLI and GUI run from source and are covered by an
> offline test suite. Real-device import has been exercised on an iPhone 12
> (iOS 26.4) on Windows 11, but the full Windows/iPhone validation matrix has
> not yet passed and there is no downloadable release. Keep an independent
> backup and do not rely on this as your only copy.

## Features

- **Lossless, incremental import.** Originals are copied byte-for-byte, never
  re-encoded or modified. Each file is SHA-256-verified, and items already
  archived are skipped on the next run.
- **Albums as real folders.** Every phone album becomes a folder of ordinary
  files. Album membership is reconciled with the phone on every import, and
  iCloud Shared Albums are archived in their own `_Shared Albums` folder.
- **Append-only by design.** Deleting something on the phone never deletes it
  from the archive. Photos removed from the phone can be reviewed, recycled,
  restored or purged, and anything permanent asks you to type `DELETE`.
- **"Optimize iPhone Storage" aware.** Photos whose originals live only in
  iCloud are imported as labelled low-resolution previews from the phone's own
  cache, then upgraded in place once the original is back on the phone.
- **Integrity checks.** `verify` re-hashes archived files, and a duplicate and
  storage report shows where the space goes.
- **Rich metadata.** Capture time, GPS and camera details (camera, lens, ISO,
  aperture, focal length) are kept in a SQLite catalog with per-asset JSON
  sidecars.
- **Trip map.** An interactive OpenStreetMap view of any album's located
  photos, in capture order. You can tag each leg with how you travelled and
  hide GPS outliers.
- **Two first-class front ends.** A scriptable CLI and a Qt desktop app with
  light and dark themes. A parity test fails the build if any capability
  exists in only one of them.
- **Local and private.** No cloud account or iCloud login is used, and nothing
  is uploaded. The only network traffic is map tiles while the map is open.

## How it works

```text
iPhone (USB, AFC) ──► ibackup ──► <archive>/
                                   ├── Photos/
                                   │   ├── <Album Name>/        real files, one copy per album
                                   │   ├── _Unsorted/YYYY/MM/   photos in no album
                                   │   └── _Shared Albums/<Album Name>/
                                   ├── Deleted/                 recycle bin, mirrors Photos/
                                   └── .ibackup/                catalog.sqlite, sidecars, thumbnails, logs
```

The phone is read over Apple File Conduit with
[`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3), through the
Apple Mobile Device driver; no drive mount or jailbreak is needed. The archive
contains no symlinks, and every name is sanitised for NTFS and exFAT, so you
can copy the archive to any disk and it keeps working. Full details are in the
[specification](docs/specifications.md).

## Requirements

- Windows 10 or 11 (64-bit)
- Python 3.11 or newer
- Apple's **iTunes** or **Apple Devices** app, which installs the USB driver
- An iPhone and a USB cable, with the computer trusted on the phone

## Installation

There is no packaged release yet, so install from source:

```powershell
git clone https://github.com/gianlucacornacchia/iBackup.git
cd iBackup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
```

This installs two commands: `ibackup` (CLI) and `ibackup-gui` (desktop app).

## Quick start

```powershell
ibackup device-info                          # check the phone is connected and trusted
ibackup init D:\iphone-archive               # create an archive
ibackup import --archive D:\iphone-archive   # import new photos and videos
ibackup verify --archive D:\iphone-archive   # re-check archived files
ibackup-gui                                  # or do all of it from the desktop app
```

### Common commands

| Command | Purpose |
|---|---|
| `ibackup import` | Import new media and reconcile album folders |
| `ibackup verify` | Re-hash archived files (`--limit N` for a quick spot check) |
| `ibackup albums` / `ibackup list` / `ibackup stats` | Browse the catalog |
| `ibackup dedup` | Duplicate and storage report |
| `ibackup scan-phone` | Refresh which archived photos are still on the phone |
| `ibackup deleted-on-phone …` | Review, recycle, restore or purge photos deleted from the phone |
| `ibackup move <album> <ids…>` | Move photos to another album |
| `ibackup marks …` | Stage deletions, then commit them in one confirmed step |
| `ibackup reclaim` | Preview which phone files are safely archived (deletes nothing) |
| `ibackup config …` | View and change settings |

Run `ibackup --help` for every option. The [user guide](docs/readme-user.md)
covers each command, the desktop app and the map.

## Compatibility

| iPhone | iOS | Windows | Status |
|---|---|---|---|
| iPhone 12 | 26.4 | 11 | ⚠️ Import, albums, GPS, offloaded previews and verify work; shared albums are partly validated and deleting from the phone is disabled |
| Any other model or iOS version | | | ❔ Untested; [help us test it](docs/compatibility.md#report-your-device) |

The [compatibility matrix](docs/compatibility.md) has the per-feature
results, iOS version notes, and the known bugs, both open and fixed.

> [!TIP]
> **Anyone can contribute.** Test iPhone Archive with your own iPhone model
> and [send a device report](https://github.com/gianlucacornacchia/iBackup/issues/new?template=device_report.yml),
> even if everything works. Each report adds a row to the matrix. Code
> contributions are just as welcome: you don't need an iPhone to build
> features or fix bugs, because the test suite runs against a fake device.
> See [CONTRIBUTING.md](CONTRIBUTING.md).

## Safety model

- Imports never overwrite or modify an archived file. Files are written to a
  staging area, verified, then published atomically.
- Nothing is removed from the archive unless you ask for it. Recycling is
  reversible, and permanent deletion needs a typed `DELETE` in both the CLI
  and the GUI.
- `reclaim` only lists phone files that have a freshly verified archive copy.
  **Deleting from the phone is currently disabled** until hardware validation
  passes.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install

ruff check . ; ruff format --check .
mypy --strict src/iphone_archive/core src/iphone_archive/catalog
$env:QT_QPA_PLATFORM = "offscreen"; pytest
```

The test suite has over 850 tests and runs fully offline against a fake
device, including property-based tests (Hypothesis), a golden end-to-end and
crash-resume test, and headless GUI tests (pytest-qt). CI runs on Windows:

- **[Tests](.github/workflows/tests.yml):** lint, format, strict type-checking,
  and the test suite on Python 3.11 and 3.12 with an 85% coverage gate.
- **[Build](.github/workflows/build.yml):** the sdist and wheel, plus the
  PyInstaller desktop app, which is launched as a smoke test and uploaded as a
  build artifact.

See the [development guide](docs/development.md) for the environment, tooling
and packaging, and [CONTRIBUTING.md](CONTRIBUTING.md) for how to propose
changes.

### Architecture

The CLI ([Typer](https://typer.tiangolo.com/)) and the GUI
([PySide6](https://doc.qt.io/qtforpython-6/)) are thin adapters over one
headless service layer:

```text
cli.py ─┐
        ├─► service/ ─► core/ (import, verify, recycle, reclaim, …) ─► catalog/ (SQLite + sidecars)
gui/  ──┘                  └──► device/ (AFC over USB, or a fake device in tests)
```

## Documentation

| Document | Contents |
|---|---|
| [User guide](docs/readme-user.md) | Installation, commands, desktop app, map, FAQ, troubleshooting |
| [Compatibility](docs/compatibility.md) | Tested iPhones and iOS versions, per-feature results, known bugs |
| [Specification](docs/specifications.md) | Archive layout, catalog schema, import and safety rules |
| [Architecture](docs/structure.md) | Module map and data flow |
| [Development](docs/development.md) | Environment, dependencies, tests, packaging |
| [Test plan](docs/unit-tests.md) | Test inventory and the hardware validation gate |
| [User stories](docs/user-stories.md) | Acceptance criteria |
| [Decision records](docs/adr/README.md) | Architectural decisions (ADRs) |
| [Progress log](docs/progress.md) | Dated change log and validation evidence |
| [Roadmap](docs/todos.md) | Build checklist and open work |

## License

Released under the [MIT License](LICENSE). Bundled third-party components keep
their own licenses, including Qt/PySide6 (LGPL) and Leaflet (BSD-2-Clause).
Map data is © OpenStreetMap contributors. See
[ADR-0011](docs/adr/0011-licensing-and-gui-contract-addendum.md) for the
redistribution notes.

---

<sub>iPhone is a trademark of Apple Inc. This project is not affiliated with or
endorsed by Apple.</sub>
