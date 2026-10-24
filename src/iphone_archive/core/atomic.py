"""Atomic renames that tolerate Windows' transient sharing violations.

On Windows a rename or replace fails with ``PermissionError`` (``WinError 5``
access denied, or ``WinError 32`` sharing violation) while another process -
antivirus, the search indexer, Explorer's preview pane - briefly has the file
open. Those holds last milliseconds, so a few short retries turn a spurious
failure into success. Any other error, and ``FileExistsError`` in particular,
is raised at once: a no-clobber publication must never be retried into a
different outcome.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

# Total wait is about 1.5 s (0.05 + 0.1 + 0.2 + 0.4 + 0.8), long enough for a
# scanner's hold and short enough that a real permission problem still surfaces.
RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
# Only Windows reports a transient hold as PermissionError; elsewhere it is real.
RETRY_ON_PERMISSION_ERROR = os.name == "nt"


def atomic_replace(source: Path, target: Path) -> None:
    """Atomically replace ``target`` with ``source``, retrying transient holds.

    source: the fully written staging file.
    target: the file to replace (it may not exist yet).
    Returns None. Raises the last ``PermissionError`` if every retry fails.
    """
    atomic_retry(lambda: os.replace(source, target))


def atomic_rename(source: Path, target: Path) -> None:
    """Rename ``source`` to a new ``target`` name, never replacing an existing one.

    source: the staged file.
    target: the destination name; on Windows an existing name raises
        ``FileExistsError`` immediately, without retrying.
    Returns None. Raises the last ``PermissionError`` if every retry fails.
    """
    atomic_retry(lambda: os.rename(source, target))


def atomic_retry(operation: Callable[[], None]) -> None:
    """Run a rename-like callable, retrying only transient Windows sharing errors.

    operation: a zero-argument callable performing the rename.
    Returns None.
    """
    for delay in RETRY_DELAYS:
        try:
            operation()
            return
        except FileExistsError:
            raise
        except PermissionError:
            if not RETRY_ON_PERMISSION_ERROR:
                raise
            time.sleep(delay)
    operation()
