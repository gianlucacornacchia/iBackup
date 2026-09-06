"""Mark-for-delete staging.

Marks record an intention to delete an asset or an album. Nothing is removed
from disk until the marks are explicitly committed, which supports a
"review before delete" workflow in both the CLI and the GUI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ..catalog import repository
from ..catalog.models import DeletionMark

TARGET_ASSET = "asset"
TARGET_ALBUM = "album"


@dataclass
class MarkSummary:
    """A staged deletion mark as presented to a frontend."""

    mark_id: int
    target_type: str
    target_id: int
    marked_at: str | None
    reason: str | None


@dataclass
class MarkCommitResult:
    """Outcome of committing staged marks."""

    committed_count: int = 0
    skipped_count: int = 0
    asset_ids: list[int] = field(default_factory=list)


def marks_now() -> str:
    """Return the current time as an ISO-8601 string.

    Returns the timestamp recorded on marks.
    """
    return datetime.now().isoformat(timespec="seconds")


def marks_add(
    connection: sqlite3.Connection,
    target_type: str,
    target_id: int,
    reason: str | None = None,
) -> int:
    """Stage a mark-for-delete without touching any file.

    connection: an open catalog connection.
    target_type: ``asset`` or ``album``.
    target_id: the id of the asset or album being marked.
    reason: optional free-text note explaining the mark.
    Returns the new mark's id.
    """
    mark_id = repository.repository_add_deletion_mark(
        connection,
        DeletionMark(
            target_type=target_type,
            target_id=target_id,
            marked_at=marks_now(),
            reason=reason,
        ),
    )
    connection.commit()
    return mark_id


def marks_add_many(
    connection: sqlite3.Connection, asset_ids: list[int], reason: str | None = None
) -> list[int]:
    """Stage marks for several assets at once (multi-select support).

    connection: an open catalog connection.
    asset_ids: the assets to mark.
    reason: optional note applied to every mark.
    Returns the ids of the created marks.
    """
    created = [marks_add(connection, TARGET_ASSET, asset_id, reason) for asset_id in asset_ids]
    return created


def marks_list_pending(connection: sqlite3.Connection) -> list[MarkSummary]:
    """List marks that have not been committed yet.

    connection: an open catalog connection.
    Returns the staged marks awaiting review.
    """
    return [
        MarkSummary(
            mark_id=mark.mark_id if mark.mark_id is not None else 0,
            target_type=mark.target_type,
            target_id=mark.target_id,
            marked_at=mark.marked_at,
            reason=mark.reason,
        )
        for mark in repository.repository_list_pending_marks(connection)
    ]


def marks_unmark(connection: sqlite3.Connection, mark_id: int) -> None:
    """Remove a staged mark, cancelling the intention to delete.

    connection: an open catalog connection.
    mark_id: the staged mark to remove.
    Returns None.
    """
    connection.execute(
        "DELETE FROM deletion_marks WHERE id = ? AND committed_at IS NULL", (mark_id,)
    )
    connection.commit()


def marks_clear(connection: sqlite3.Connection) -> int:
    """Remove every staged mark.

    connection: an open catalog connection.
    Returns the number of marks removed.
    """
    cursor = connection.execute("DELETE FROM deletion_marks WHERE committed_at IS NULL")
    connection.commit()
    return cursor.rowcount


def marks_resolve_asset_ids(connection: sqlite3.Connection) -> list[int]:
    """Expand pending marks into the concrete asset ids they cover.

    connection: an open catalog connection.
    Returns asset ids from asset marks plus all members of marked albums.
    """
    asset_ids: list[int] = []
    for mark in repository.repository_list_pending_marks(connection):
        if mark.target_type == TARGET_ASSET:
            asset_ids.append(mark.target_id)
        elif mark.target_type == TARGET_ALBUM:
            rows = connection.execute(
                "SELECT asset_id FROM asset_albums WHERE album_id = ?", (mark.target_id,)
            ).fetchall()
            asset_ids.extend(int(row["asset_id"]) for row in rows)

    unique_ids: list[int] = []
    for asset_id in asset_ids:
        if asset_id not in unique_ids:
            unique_ids.append(asset_id)
    return unique_ids


def marks_commit(connection: sqlite3.Connection, confirmed: bool = False) -> MarkCommitResult:
    """Finalize staged marks after explicit confirmation.

    connection: an open catalog connection.
    confirmed: must be True; otherwise nothing is committed.
    Returns a ``MarkCommitResult`` listing the affected asset ids so the caller
    can perform the actual removal (recycle or purge).
    """
    result = MarkCommitResult()
    pending = repository.repository_list_pending_marks(connection)
    if not confirmed:
        result.skipped_count = len(pending)
        return result

    result.asset_ids = marks_resolve_asset_ids(connection)
    committed_at = marks_now()
    for mark in pending:
        if mark.mark_id is not None:
            repository.repository_commit_mark(connection, mark.mark_id, committed_at)
            result.committed_count += 1
    connection.commit()
    return result
