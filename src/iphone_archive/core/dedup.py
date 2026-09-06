"""Duplicate detection and multi-album storage reporting.

Duplicates are identified purely by SHA-256 content hash. This module is
**read-only**: it reports what it finds and never deletes or moves files.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog import repository
from ..config import ArchivePaths


@dataclass
class DuplicateGroup:
    """A set of stored copies sharing the same content."""

    sha256: str
    original_name: str
    copy_count: int
    size: int
    paths: list[str] = field(default_factory=list)

    @property
    def extra_bytes(self) -> int:
        """Return the bytes used by copies beyond the first."""
        return max(self.copy_count - 1, 0) * self.size


@dataclass
class DedupResult:
    """Summary of a duplicate-detection run."""

    asset_count: int = 0
    file_count: int = 0
    multi_copy_groups: list[DuplicateGroup] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        """Return total bytes attributable to additional album copies."""
        return sum(group.extra_bytes for group in self.multi_copy_groups)


def dedup_report(connection: sqlite3.Connection, paths: ArchivePaths) -> DedupResult:
    """Report duplicate content and the storage cost of multi-album copies.

    connection: an open catalog connection.
    paths: resolved archive paths (unused for I/O; kept for interface symmetry).
    Returns a ``DedupResult``. No files are modified or deleted.
    """
    result = DedupResult()
    rows = connection.execute("SELECT id, sha256, original_name, size FROM assets").fetchall()
    result.asset_count = len(rows)

    all_files = repository.repository_all_asset_files(connection)
    result.file_count = len(all_files)

    files_by_asset: dict[int, list[str]] = {}
    for stored in all_files:
        files_by_asset.setdefault(stored.asset_id, []).append(stored.path)

    for row in rows:
        asset_id = int(row["id"])
        stored_paths = files_by_asset.get(asset_id, [])
        if len(stored_paths) > 1:
            result.multi_copy_groups.append(
                DuplicateGroup(
                    sha256=str(row["sha256"]),
                    original_name=str(row["original_name"]),
                    copy_count=len(stored_paths),
                    size=int(row["size"]),
                    paths=sorted(stored_paths),
                )
            )

    return result
