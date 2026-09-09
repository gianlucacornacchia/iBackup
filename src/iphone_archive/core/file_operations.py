"""Recoverable catalog/file edits, serialized by the service's archive lock.

An immutable intent owns a private staging directory before files are created.
Bounded per-file records identify staged inodes before no-clobber publication.
Original bytes remain until the catalog transaction commits its operation marker.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from ..catalog import repository, sidecar
from ..catalog.models import AssetFile
from ..config import ArchivePaths
from . import hashing, name_safety

file_operations_claimer: ContextVar[Callable[[Path, os.stat_result], None] | None] = ContextVar(
    "file_operations_claimer", default=None
)


@dataclass
class FileChange:
    """One selected file's destination; None location means staged purge."""

    file_id: int
    asset_id: int
    source: str
    destination: str
    location: str | None
    album_id: int | None
    sha256: str


def file_operations_ids(identifiers: list[int]) -> list[int]:
    """Validate positive integer identifiers and retain their first occurrence."""
    if any(type(identifier) is not int or identifier <= 0 for identifier in identifiers):
        raise ValueError("Identifiers must be positive integers")
    return list(dict.fromkeys(identifiers))


def file_operations_path(paths: ArchivePaths, relative: str) -> Path:
    """Validate an archive-relative, portable path without traversing symlinks."""
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not relative
        or posix.is_absolute()
        or windows.drive
        or "\\" in relative
        or any(part in {".", ".."} for part in relative.split("/"))
        or any(":" in part for part in posix.parts)
        or any(
            part.rstrip(". ") != part
            or part.split(".")[0].lower() in name_safety.RESERVED_NAMES
            or len(part) > 255
            or any(
                character in name_safety.RESERVED_CHARS or ord(character) < 32 for character in part
            )
            for part in posix.parts
        )
    ):
        raise ValueError(f"Unsafe archive path: {relative}")
    absolute = paths.root / relative
    directory = paths.root
    for component in posix.parts[:-1]:
        if directory.is_dir() and any(
            entry.name.casefold() == component.casefold() and entry.name != component
            for entry in directory.iterdir()
        ):
            raise ValueError(f"Case-insensitive directory collision: {relative}")
        directory = directory / component
    for parent in (absolute, *absolute.parents):
        if parent == paths.root:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink in archive path: {relative}")
    if not absolute.resolve().is_relative_to(paths.root.resolve()):
        raise ValueError(f"Path escapes archive: {relative}")
    return absolute


def file_operations_select(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    asset_ids: list[int],
    location: str | None = None,
    file_ids: list[int] | None = None,
    album_id: int | None = None,
) -> list[AssetFile]:
    """Resolve and preflight every requested copy, raising on invalid/missing data."""
    identifiers = file_operations_ids(asset_ids)
    requested = None if file_ids is None else set(file_operations_ids(file_ids))
    selected: list[AssetFile] = []
    for asset_id in identifiers:
        asset = repository.repository_get_asset(connection, asset_id)
        if asset is None:
            raise ValueError(f"Unknown asset: {asset_id}")
        stored_files = repository.repository_list_asset_files(connection, asset_id)
        if not stored_files:
            raise ValueError(f"Asset has no cataloged copies: {asset_id}")
        for stored in stored_files:
            if requested is not None and stored.file_id not in requested:
                continue
            if location is not None and stored.location.value != location:
                continue
            if album_id is not None and stored.album_id != album_id:
                continue
            source = file_operations_path(paths, stored.path)
            expected_root = (
                paths.photos_dir if stored.location.value == "photos" else paths.deleted_dir
            )
            if not source.is_relative_to(expected_root):
                raise ValueError(f"File path does not match its location: {stored.path}")
            if not source.is_file():
                raise FileNotFoundError(f"Missing archived file: {stored.path}")
            if source.stat().st_size != asset.size:
                raise ValueError(f"Archived file size mismatch: {stored.path}")
            if hashing.hashing_sha256_file(source) != asset.sha256:
                raise ValueError(f"Archived file hash mismatch: {stored.path}")
            selected.append(stored)
    if requested is not None and requested != {stored.file_id for stored in selected}:
        raise ValueError("Selected file ids do not match the requested assets/location/album")
    return selected


def file_operations_destination(paths: ArchivePaths, desired: Path, reserved: set[str]) -> str:
    """Reserve a Windows-safe, case-insensitively unique destination."""
    relative = desired.relative_to(paths.root).as_posix()
    file_operations_path(paths, relative)
    existing = (
        {entry.name.casefold() for entry in desired.parent.iterdir()}
        if (desired.parent.is_dir())
        else set()
    )
    existing.update(
        PurePosixPath(path).name.casefold()
        for path in reserved
        if PurePosixPath(path).parent == PurePosixPath(relative).parent
    )
    candidate = name_safety.name_safety_safe_file_name(desired.name)
    filename = name_safety.name_safety_resolve_collision(candidate, existing)
    result = desired.with_name(filename).relative_to(paths.root).as_posix()
    reserved.add(result)
    return result


def file_operations_sync_directory(directory: Path) -> None:
    """Persist directory entries where directory fsync is supported (POSIX)."""
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def file_operations_copy(source: Path, destination: Path) -> None:
    """Copy into the operation's already-owned private staging namespace."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        claimer = file_operations_claimer.get()
        if claimer is not None:
            claimer(destination, os.fstat(writer.fileno()))
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    file_operations_sync_directory(destination.parent)


def file_operations_publish(staged: Path, destination: Path) -> None:
    """Publish a staged inode atomically without replacing any existing name.

    Windows rename refuses existing destinations. POSIX hardlinks preserve the
    recorded identity; filesystems without that primitive fail before publication.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.rename(staged, destination)
    else:
        os.link(staged, destination)
    file_operations_sync_directory(destination.parent)


def file_operations_update_assets(connection: sqlite3.Connection, asset_ids: list[int]) -> None:
    """Derive lifecycle and browsable memberships from surviving active copies."""
    for asset_id in asset_ids:
        connection.execute("DELETE FROM asset_albums WHERE asset_id = ?", (asset_id,))
        connection.execute(
            "INSERT OR IGNORE INTO asset_albums(asset_id, album_id) "
            "SELECT asset_id, album_id FROM asset_files WHERE asset_id = ? "
            "AND location = 'photos' AND album_id IS NOT NULL",
            (asset_id,),
        )
        connection.execute(
            "UPDATE assets SET archive_state = CASE WHEN EXISTS "
            "(SELECT 1 FROM asset_files WHERE asset_id = ? AND location = 'photos') "
            "THEN 'active' ELSE 'deleted' END WHERE id = ?",
            (asset_id, asset_id),
        )
        connection.execute(
            "DELETE FROM assets WHERE id = ? "
            "AND NOT EXISTS (SELECT 1 FROM asset_files WHERE asset_id = ?)",
            (asset_id, asset_id),
        )


def file_operations_preserve_partial(paths: ArchivePaths, partial: Path) -> None:
    """Keep known-owned interrupted bytes outside browsable folders for inspection."""
    conflicts = paths.internal_dir / "operation_conflicts" / uuid4().hex
    conflicts.mkdir(parents=True, exist_ok=False)
    partial.rename(conflicts / partial.name)
    file_operations_sync_directory(conflicts)
    file_operations_sync_directory(partial.parent)


def file_operations_finish_change(
    paths: ArchivePaths,
    change: FileChange,
    source_identity: list[int] | None,
    owned_identity: list[int] | None,
    committed: bool,
    staged: Path | None,
) -> None:
    """Recover one copy, distinguishing private creation from published ownership."""
    source = file_operations_path(paths, change.source)
    destination = file_operations_path(paths, change.destination)
    if staged is not None and staged.exists() and owned_identity is not None:
        identity = staged.stat()
        if owned_identity != [identity.st_dev, identity.st_ino]:
            raise RuntimeError(f"Recovery staging identity changed: {staged}")
    if destination.exists():
        identity = destination.stat()
        private_unpublished = destination == staged and not committed and owned_identity is None
        if not private_unpublished and owned_identity != [identity.st_dev, identity.st_ino]:
            raise RuntimeError(
                f"Recovery cannot establish destination ownership: {change.destination}"
            )
    if source.exists():
        identity = source.stat()
        if source_identity != [identity.st_dev, identity.st_ino]:
            raise RuntimeError(f"Recovery source identity changed: {change.source}")
    if committed:
        if change.location is not None:
            if not destination.is_file() or (
                hashing.hashing_sha256_file(destination) != change.sha256
            ):
                raise RuntimeError(f"Recovery destination damaged: {change.destination}")
        if source.exists():
            if hashing.hashing_sha256_file(source) != change.sha256:
                raise RuntimeError(f"Recovery source changed: {change.source}")
            source.unlink()
            file_operations_sync_directory(source.parent)
        if change.location is None:
            destination.unlink(missing_ok=True)
    else:
        if not source.is_file() or hashing.hashing_sha256_file(source) != change.sha256:
            raise RuntimeError(f"Recovery source damaged: {change.source}")
        if destination.exists():
            if hashing.hashing_sha256_file(destination) != change.sha256:
                file_operations_preserve_partial(paths, destination)
            else:
                destination.unlink()
        if staged is not None and staged.exists():
            if hashing.hashing_sha256_file(staged) != change.sha256:
                file_operations_preserve_partial(paths, staged)
    if destination.parent.exists():
        file_operations_sync_directory(destination.parent)


def file_operations_remove_stage(stage: Path, count: int) -> None:
    """Remove only expected files inside the validated private operation namespace."""
    expected = {
        f"{index}.{suffix}" for index in range(count) for suffix in ("data", "owner", "pending")
    }
    if stage.exists():
        for entry in stage.iterdir():
            if entry.name not in expected or not entry.is_file() or entry.is_symlink():
                raise RuntimeError(f"Unexpected entry in private operation staging: {entry}")
            entry.unlink()
        stage.rmdir()
        file_operations_sync_directory(stage.parent)


def file_operations_finish(
    connection: sqlite3.Connection, paths: ArchivePaths, journal: Path
) -> None:
    """Recover immutable intent and bounded ownership records, including partial creation."""
    file_operations_path(paths, journal.relative_to(paths.root).as_posix())
    payload = json.loads(journal.read_text(encoding="utf-8"))
    changes = [FileChange(**entry) for entry in payload["changes"]]
    stage = journal.with_suffix("")
    staging = payload.get("staging")
    completed = journal.with_suffix(".done")
    if staging is not None:
        stage = file_operations_path(paths, staging["path"])
        if stage.exists():
            identity = stage.stat()
            if staging["identity"] != [identity.st_dev, identity.st_ino]:
                raise RuntimeError(f"Recovery staging namespace changed: {stage}")
        elif not completed.exists():
            raise RuntimeError(f"Recovery staging namespace missing: {stage}")
    committed = (
        connection.execute("SELECT value FROM meta WHERE key = ?", (payload["key"],)).fetchone()
        is not None
    )
    if completed.exists():
        if json.loads(completed.read_text(encoding="utf-8")) != {"key": payload["key"]}:
            raise RuntimeError(f"Invalid operation completion record: {completed}")
    else:
        for index, change in enumerate(changes):
            owned = payload.get("owned", {}).get(change.destination)
            staged = None
            if staging is not None:
                staged = stage / f"{index}.data"
                record = stage / f"{index}.owner"
                file_operations_path(paths, record.relative_to(paths.root).as_posix())
                if record.exists():
                    owned = json.loads(record.read_text(encoding="utf-8"))["identity"]
            file_operations_finish_change(
                paths,
                change,
                payload.get("sources", {}).get(change.source),
                owned,
                committed,
                staged,
            )
        if committed:
            file_operations_finish_sidecars(connection, paths, payload["assets"])
        # This bounded marker allows a crash while deleting ownership records to
        # resume housekeeping without repeating media deletion or losing proof.
        file_operations_write_journal(completed, {"key": payload["key"]})
    if staging is not None:
        file_operations_remove_stage(stage, len(changes))
    elif stage.exists():
        stage.rmdir()
    journal.unlink()
    completed.unlink(missing_ok=True)
    journal.with_suffix(".pending").unlink(missing_ok=True)
    file_operations_sync_directory(journal.parent)
    connection.execute("DELETE FROM meta WHERE key = ?", (payload["key"],))
    connection.commit()


def file_operations_finish_sidecars(
    connection: sqlite3.Connection, paths: ArchivePaths, assets: list[dict[str, str | int]]
) -> None:
    """Regenerate or remove sidecars after the catalog operation has committed."""
    for entry in assets:
        asset_id = int(entry["asset_id"])
        metadata_path = sidecar.sidecar_path_for(paths.sidecars_dir, str(entry["sha256"]))
        file_operations_path(paths, metadata_path.relative_to(paths.root).as_posix())
        if repository.repository_get_asset(connection, asset_id) is None:
            metadata_path.unlink(missing_ok=True)
        else:
            sidecar.sidecar_write(
                paths.sidecars_dir, sidecar.sidecar_from_catalog(connection, asset_id)
            )
    file_operations_sync_directory(paths.sidecars_dir)


def file_operations_recover(connection: sqlite3.Connection, paths: ArchivePaths) -> None:
    """Recover pending edits before serving an archive; caller holds writer lock."""
    if connection.in_transaction:
        raise RuntimeError("Finish or roll back the current catalog transaction before recovery")
    directory = file_operations_path(paths, ".ibackup/operations")
    if directory.exists():
        for journal in sorted(directory.glob("*.json")):
            file_operations_finish(connection, paths, journal)


def file_operations_write_journal(journal: Path, payload: object) -> None:
    """Durably replace journal metadata before changing any owned file bytes."""
    pending = journal.with_suffix(".pending")
    with pending.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    pending.replace(journal)
    file_operations_sync_directory(journal.parent)


def file_operations_execute(
    connection: sqlite3.Connection,
    paths: ArchivePaths,
    changes: list[FileChange],
    update: Callable[[], None] | None = None,
) -> None:
    """Apply one preflighted batch and optional catalog mutation recoverably.

    Caller owns the archive lock and may have uncommitted album creation. Ordinary
    failures roll back; process death leaves a journal for service-open recovery.
    """
    operation_id = uuid4().hex
    key = f"file_operation:{operation_id}"
    directory = file_operations_path(paths, ".ibackup/operations")
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / f"{operation_id}.json"
    stage = journal.with_suffix("")
    asset_ids = list(dict.fromkeys(change.asset_id for change in changes))
    assets = []
    for asset_id in asset_ids:
        asset = repository.repository_get_asset(connection, asset_id)
        if asset is None:
            raise ValueError(f"Unknown asset: {asset_id}")
        assets.append({"asset_id": asset_id, "sha256": asset.sha256})
    for index, change in enumerate(changes):
        if change.location is None:
            change.destination = f".ibackup/operations/{operation_id}/{index}.data"
        destination = file_operations_path(paths, change.destination)
        if destination.exists():
            raise FileExistsError(f"Destination already exists: {change.destination}")
    sources: dict[str, list[int]] = {}
    for change in changes:
        identity = file_operations_path(paths, change.source).stat()
        sources[change.source] = [identity.st_dev, identity.st_ino]
    stage.mkdir(mode=0o700)
    identity = stage.stat()
    file_operations_sync_directory(stage)
    payload = {
        "key": key,
        "changes": [asdict(change) for change in changes],
        "assets": assets,
        "sources": sources,
        "staging": {
            "path": stage.relative_to(paths.root).as_posix(),
            "identity": [identity.st_dev, identity.st_ino],
        },
    }
    file_operations_write_journal(journal, payload)

    def file_operations_claim(destination: Path, identity: os.stat_result) -> None:
        """Persist a bounded record before this staged inode can be published."""
        file_operations_write_journal(
            destination.with_suffix(".owner"), {"identity": [identity.st_dev, identity.st_ino]}
        )

    token = file_operations_claimer.set(file_operations_claim)
    try:
        for index, change in enumerate(changes):
            staged = stage / f"{index}.data"
            file_operations_copy(
                file_operations_path(paths, change.source),
                staged,
            )
            if hashing.hashing_sha256_file(staged) != change.sha256:
                raise ValueError(f"Copied file hash mismatch: {change.destination}")
            if change.location is None:
                connection.execute("DELETE FROM asset_files WHERE id = ?", (change.file_id,))
            else:
                file_operations_publish(staged, file_operations_path(paths, change.destination))
                connection.execute(
                    "UPDATE asset_files SET path = ?, location = ?, album_id = ?, "
                    "link_mode = 'copy' WHERE id = ?",
                    (change.destination, change.location, change.album_id, change.file_id),
                )
        file_operations_update_assets(connection, asset_ids)
        if update is not None:
            update()
        connection.execute("INSERT INTO meta(key, value) VALUES (?, 'committed')", (key,))
        connection.commit()
    except Exception:
        connection.rollback()
        file_operations_finish(connection, paths, journal)
        raise
    finally:
        file_operations_claimer.reset(token)
    try:
        file_operations_finish(connection, paths, journal)
    except Exception as error:
        raise OSError(f"Catalog committed; archive cleanup requires recovery: {error}") from error
