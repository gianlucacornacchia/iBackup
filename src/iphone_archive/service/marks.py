"""Mark-for-delete staging.

Marks record an intention to delete an asset, album, or individual file copy. Nothing is removed
from disk until the marks are explicitly committed, which supports a
"review before delete" workflow in both the CLI and the GUI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ..catalog import repository
from ..catalog.models import DeletionMark
from ..config import ArchivePaths
from ..core import file_operations, recycle

TARGET_ASSET = "asset"
TARGET_ALBUM = "album"
TARGET_FILE = "file"


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
    file_ids: list[int] = field(default_factory=list)
    mark_ids: list[int] = field(default_factory=list)
    recycle_result: recycle.RecycleResult = field(default_factory=recycle.RecycleResult)


@dataclass
class MarkTargets:
    """Concrete copy scope of pending marks; album marks never broaden to an asset."""

    asset_ids: list[int] = field(default_factory=list)
    file_ids: list[int] = field(default_factory=list)
    mark_ids: list[int] = field(default_factory=list)


def marks_validate_target(connection: sqlite3.Connection, target_type: str, target_id: int) -> None:
    """Reject malformed or nonexistent asset, album and exact-file mark targets."""
    file_operations.file_operations_ids([target_id])
    tables = {TARGET_ASSET: "assets", TARGET_ALBUM: "albums", TARGET_FILE: "asset_files"}
    if target_type not in tables:
        raise ValueError(f"Unknown mark target type: {target_type}")
    if (
        connection.execute(
            f"SELECT id FROM {tables[target_type]} WHERE id = ?", (target_id,)
        ).fetchone()
        is None
    ):
        raise ValueError(f"Unknown {target_type}: {target_id}")


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
    target_type: ``asset``, ``album``, or ``file``.
    target_id: the corresponding asset, album, or asset-file id being marked.
    reason: optional free-text note explaining the mark.
    Returns the new mark's id.
    """
    marks_validate_target(connection, target_type, target_id)
    existing = connection.execute(
        "SELECT id FROM deletion_marks WHERE target_type = ? AND target_id = ? "
        "AND committed_at IS NULL",
        (target_type, target_id),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
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
    identifiers = file_operations.file_operations_ids(asset_ids)
    for asset_id in identifiers:
        marks_validate_target(connection, TARGET_ASSET, asset_id)
    created = []
    try:
        for asset_id in identifiers:
            existing = connection.execute(
                "SELECT id FROM deletion_marks WHERE target_type = 'asset' AND target_id = ? "
                "AND committed_at IS NULL",
                (asset_id,),
            ).fetchone()
            if existing is not None:
                created.append(int(existing["id"]))
            else:
                created.append(
                    repository.repository_add_deletion_mark(
                        connection,
                        DeletionMark(
                            target_type=TARGET_ASSET,
                            target_id=asset_id,
                            marked_at=marks_now(),
                            reason=reason,
                        ),
                    )
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
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
    return marks_resolve_targets(connection).asset_ids


def marks_resolve_targets(connection: sqlite3.Connection, purge: bool = False) -> MarkTargets:
    """Resolve exact copy ids; recycled copies participate only in explicit purge."""
    result = MarkTargets()
    for mark in repository.repository_list_pending_marks(connection):
        marks_validate_target(connection, mark.target_type, mark.target_id)
        column = {TARGET_ASSET: "asset_id", TARGET_ALBUM: "album_id", TARGET_FILE: "id"}[
            mark.target_type
        ]
        statement = f"SELECT id, asset_id FROM asset_files WHERE {column} = ?"
        if not purge:
            statement += " AND location = 'photos'"
        for row in connection.execute(statement, (mark.target_id,)):
            result.file_ids.append(int(row["id"]))
            result.asset_ids.append(int(row["asset_id"]))
        if mark.mark_id is not None:
            result.mark_ids.append(mark.mark_id)
    result.file_ids = list(dict.fromkeys(result.file_ids))
    result.asset_ids = list(dict.fromkeys(result.asset_ids))
    return result


def marks_commit(
    connection: sqlite3.Connection,
    confirmed: bool = False,
    *,
    paths: ArchivePaths | None = None,
    purge: bool = False,
) -> MarkCommitResult:
    """Execute scoped deletion and mark completion in the same recoverable commit.

    connection: an open catalog connection.
    confirmed: must be True; otherwise nothing is committed.
    paths: required to execute a confirmed filesystem operation.
    purge: permanently remove selected copies rather than recycle them.
    Returns targets and recycle_result; callers must not delete the returned
    asset ids again, because album/file marks intentionally select fewer copies.
    """
    result = MarkCommitResult()
    pending = repository.repository_list_pending_marks(connection)
    if not confirmed:
        result.skipped_count = len(pending)
        return result

    if paths is None:
        raise ValueError("Archive paths are required to commit deletion marks safely")
    targets = marks_resolve_targets(connection, purge)
    result.asset_ids = targets.asset_ids
    result.file_ids = targets.file_ids
    result.mark_ids = targets.mark_ids

    def marks_finalize() -> None:
        """Record only this snapshot of marks inside the deletion transaction."""
        for mark_id in targets.mark_ids:
            repository.repository_commit_mark(connection, mark_id, marks_now())

    if purge:
        result.recycle_result = recycle.recycle_purge(
            connection,
            paths,
            targets.asset_ids,
            confirmed=True,
            file_ids=targets.file_ids,
            update=marks_finalize,
        )
    else:
        result.recycle_result = recycle.recycle_move_to_deleted(
            connection,
            paths,
            targets.asset_ids,
            file_ids=targets.file_ids,
            update=marks_finalize,
        )
    result.committed_count = len(targets.mark_ids)
    return result
