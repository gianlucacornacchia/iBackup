"""Safe reclamation of space on the phone.

A phone file may only be deleted when its content is **archived and freshly
verified**. The default is a non-destructive dry run; actual deletion requires
explicit confirmation. The archive itself is never modified by this module.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog import repository
from ..config import ArchivePaths
from ..device.interface import DeviceError, MediaSource
from ..service.progress import ProgressHandle
from . import verifier

OPERATION_NAME = "reclaim"


@dataclass
class ReclaimCandidate:
    """A phone file that is safe to delete because it is archived and verified."""

    asset_id: int
    phone_path: str
    original_name: str
    size: int


@dataclass
class ReclaimResult:
    """Summary of a reclamation run."""

    candidates: list[ReclaimCandidate] = field(default_factory=list)
    deleted_count: int = 0
    skipped_count: int = 0
    dry_run: bool = True
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        """Return the phone space represented by the candidates."""
        return sum(candidate.size for candidate in self.candidates)


def reclaim_find_candidates(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    source: MediaSource,
    progress: ProgressHandle | None = None,
) -> list[ReclaimCandidate]:
    """Find phone files whose content is archived and verifies successfully.

    connection: an open catalog connection.
    paths: resolved archive paths.
    source: the media source to inspect.
    progress: optional progress/cancellation handle.
    Returns the list of safe-to-delete candidates. Nothing is deleted.
    """
    handle = progress if progress is not None else ProgressHandle()
    candidates: list[ReclaimCandidate] = []
    items = list(source.device_enumerate())
    total = len(items)

    for index, item in enumerate(items, start=1):
        if handle.progress_is_cancelled():
            break
        handle.progress_report(OPERATION_NAME, index, total, item.original_name)

        known = repository.repository_find_by_phone_identity(
            connection, item.phone_asset_id, item.phone_path, item.size
        )
        if known is None or known.asset_id is None:
            continue
        if not verifier.verifier_asset_is_verified(connection, paths, known.asset_id):
            continue
        candidates.append(
            ReclaimCandidate(
                asset_id=known.asset_id,
                phone_path=item.phone_path,
                original_name=item.original_name,
                size=item.size,
            )
        )
    return candidates


def reclaim_run(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    source: MediaSource,
    confirmed: bool = False,
    progress: ProgressHandle | None = None,
) -> ReclaimResult:
    """Report, and optionally delete, phone files that are safely archived.

    connection: an open catalog connection.
    paths: resolved archive paths.
    source: the media source to reclaim space on.
    confirmed: when False (default) this is a dry run that deletes nothing.
    progress: optional progress/cancellation handle.
    Returns a ``ReclaimResult``. The archive is never modified.
    """
    handle = progress if progress is not None else ProgressHandle()
    result = ReclaimResult(dry_run=not confirmed)
    result.candidates = reclaim_find_candidates(connection, paths, source, handle)

    if handle.progress_is_cancelled():
        result.cancelled = True
        return result

    if not confirmed:
        result.skipped_count = len(result.candidates)
        return result

    for candidate in result.candidates:
        if handle.progress_is_cancelled():
            result.cancelled = True
            break
        try:
            source.device_delete(candidate.phone_path)
            result.deleted_count += 1
        except (DeviceError, OSError) as error:
            result.errors.append(f"{candidate.phone_path}: {error}")
            result.skipped_count += 1

    return result
