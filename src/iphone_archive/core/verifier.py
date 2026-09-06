"""Integrity verification of archived files.

Re-hashes stored copies and compares them against the catalog, reporting any
file whose content changed (corruption) or that has disappeared. Verification is
read-only: it never modifies or deletes archive content.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ..catalog import repository
from ..config import ArchivePaths
from ..service.progress import ProgressHandle
from . import hashing

OPERATION_NAME = "verify"

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_MISSING = "missing"


@dataclass
class VerifyIssue:
    """A single file that failed verification."""

    path: str
    status: str
    expected_sha256: str
    actual_sha256: str | None = None


@dataclass
class VerifyResult:
    """Summary of a verification run."""

    checked_count: int = 0
    ok_count: int = 0
    mismatch_count: int = 0
    missing_count: int = 0
    cancelled: bool = False
    issues: list[VerifyIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return True when no mismatches or missing files were found."""
        return self.mismatch_count == 0 and self.missing_count == 0


def verifier_run(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    progress: ProgressHandle | None = None,
    limit: int | None = None,
) -> VerifyResult:
    """Verify archived files against their recorded content hashes.

    connection: an open catalog connection.
    paths: resolved archive paths.
    progress: optional progress/cancellation handle.
    limit: when set, verify at most this many files (rolling subset).
    Returns a ``VerifyResult`` describing what was checked and any issues.
    """
    handle = progress if progress is not None else ProgressHandle()
    result = VerifyResult()

    stored_files = repository.repository_all_asset_files(connection)
    if limit is not None:
        stored_files = stored_files[:limit]
    total = len(stored_files)

    hash_by_asset: dict[int, str] = {}
    for row in connection.execute("SELECT id, sha256 FROM assets"):
        hash_by_asset[int(row["id"])] = str(row["sha256"])

    verified_at = datetime.now().isoformat(timespec="seconds")
    for index, stored in enumerate(stored_files, start=1):
        if handle.progress_is_cancelled():
            result.cancelled = True
            break
        handle.progress_report(OPERATION_NAME, index, total, stored.path)

        expected = hash_by_asset.get(stored.asset_id, "")
        absolute = paths.root / stored.path
        result.checked_count += 1

        if not absolute.is_file():
            result.missing_count += 1
            result.issues.append(
                VerifyIssue(path=stored.path, status=STATUS_MISSING, expected_sha256=expected)
            )
            continue

        actual = hashing.hashing_sha256_file(absolute)
        if actual != expected:
            result.mismatch_count += 1
            result.issues.append(
                VerifyIssue(
                    path=stored.path,
                    status=STATUS_MISMATCH,
                    expected_sha256=expected,
                    actual_sha256=actual,
                )
            )
        else:
            result.ok_count += 1
            repository.repository_set_verified_at(connection, stored.asset_id, verified_at)

    connection.commit()
    return result


def verifier_asset_is_verified(
    connection: sqlite3.Connection, paths: ArchivePaths, asset_id: int
) -> bool:
    """Check every stored copy of one asset against its recorded hash.

    connection: an open catalog connection.
    paths: resolved archive paths.
    asset_id: the asset to verify.
    Returns True only when at least one copy exists and all copies match.
    """
    row = connection.execute("SELECT sha256 FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return False
    expected = str(row["sha256"])

    stored_files = repository.repository_list_asset_files(connection, asset_id)
    if not stored_files:
        return False

    verified = True
    for stored in stored_files:
        absolute = paths.root / stored.path
        if not absolute.is_file() or hashing.hashing_sha256_file(absolute) != expected:
            verified = False
            break
    return verified
