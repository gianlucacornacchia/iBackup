"""Desktop interface for the archive.

The GUI is a *presentation layer only*. Every archive operation it performs goes
through :class:`iphone_archive.service.app_service.AppService`, the same facade
the CLI uses, so the two cannot drift apart in behaviour or in safety rules. No
module in this package may touch the catalog, the filesystem or the device
directly.

Importing this package must not import PySide6, so ``ibackup`` keeps working on
a machine where Qt is unusable; the Qt dependency lives in the submodules.
"""

from __future__ import annotations
