# 0003. Python core + PySide6 GUI

- **Status:** Accepted; interop rationale corrected by ADR-0011
- **Date:** 2026-09-07
- **Deciders:** Project author

## Context

The application needs USB access to an iPhone, a durable catalog, and a desktop
GUI able to show thumbnail grids, multi-select, and run long operations with
progress/cancel. The most mature iPhone-access library (`pymobiledevice3`) is
Python. Even after narrowing to Windows-only, a native rewrite was reconsidered.

## Decision

Implement the whole application in **Python 3.11+**, with the desktop GUI built on
**PySide6** (Qt for Python, LGPL). CLI and GUI are thin adapters over a headless
service layer (see ADR-0009).

## Alternatives considered

- **Native WinUI 3 / C#** — rejected: would require rewriting the entire core
  (device access, catalog, importer) and reimplementing/binding
  `pymobiledevice3`, for little payoff on a solo Windows-only project.
- **HTML/JS shells (PyWebView, Tauri, Electron, FastAPI+SPA)** — viable but add a
  web toolchain and, for HEIC, still need server-side thumbnailing; PySide6 keeps
  an all-Python, single-language stack with native widgets.

## Consequences

- **Positive:** Single language end-to-end; reuse of the mature Python device
  library; native desktop widgets, Qt threading, and built-in multi-select;
  packages to a portable `.exe` with PyInstaller.
- **Negative / trade-offs:** Qt/LGPL bundle size; HEIC/HEVC must be transcoded for
  thumbnails (via `pillow-heif`) since Qt cannot render them natively.
