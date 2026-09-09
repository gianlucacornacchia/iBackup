"""Placement of asset files into the archive's plain album folders.

Content is streamed and verified in a private staging folder, then published
without replacing existing files. The staging inode is durably identified before
publication, using native Windows rename or POSIX hardlink. Multi-album assets get a real file
in every album folder, either copied or hardlinked; **symbolic links are never
created** so the archive stays valid when copied to another disk.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from ..config import ArchivePaths
from . import hashing, name_safety
from .file_operations import file_operations_path, file_operations_publish

LINK_MODE_COPY = "copy"
LINK_MODE_HARDLINK = "hardlink"
placement_recorder: ContextVar[Callable[[Path], None] | None] = ContextVar(
    "placement_recorder", default=None
)
placement_claimer: ContextVar[Callable[[Path, bool], None] | None] = ContextVar(
    "placement_claimer", default=None
)
placement_staging_dir: ContextVar[Path | None] = ContextVar("placement_staging_dir", default=None)
placement_preparer: ContextVar[Callable[[Path, Path], None] | None] = ContextVar(
    "placement_preparer", default=None
)


def archive_layout_record(path: Path) -> None:
    """Write durable import intent before exclusively creating a new file."""
    recorder = placement_recorder.get()
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    if recorder is not None:
        recorder(path)


def archive_layout_claim(path: Path, created: bool = True) -> None:
    """Notify private creation, or withdraw an intent after a publication collision."""
    claimer = placement_claimer.get()
    if claimer is not None:
        claimer(path, created)


def archive_layout_sync(directory: Path) -> None:
    """Sync directory entries on platforms supporting directory fsync."""
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass
class PlacedFile:
    """Result of placing one file into the archive."""

    path: Path
    sha256: str
    size: int
    link_mode: str


def archive_layout_album_dir(paths: ArchivePaths, album_name: str | None) -> Path:
    """Return the folder for an album, or the unsorted root when album-less.

    paths: resolved archive paths.
    album_name: the album's display name, or None for album-less assets.
    Returns the directory that should contain the asset's file.
    """
    if album_name is None:
        result = paths.unsorted_dir
    else:
        safe_album = name_safety.name_safety_sanitize_component(album_name, fallback="Album")
        result = paths.photos_dir / safe_album
    return result


def archive_layout_unsorted_dir(paths: ArchivePaths, captured_at: str | None) -> Path:
    """Return the ``_Unsorted/YYYY/MM`` folder for an album-less asset.

    paths: resolved archive paths.
    captured_at: ISO capture timestamp; when unparsable the current date is used.
    Returns the dated folder under the unsorted root.
    """
    moment = datetime.now()
    if captured_at:
        try:
            moment = datetime.fromisoformat(captured_at)
        except ValueError:
            # Unparsable capture times fall back to today's date so the asset is
            # still filed deterministically rather than rejected.
            moment = datetime.now()
    return paths.unsorted_dir / f"{moment.year:04d}" / f"{moment.month:02d}"


def archive_layout_unique_target(target_dir: Path, file_name: str) -> Path:
    """Return a non-colliding target path inside a directory.

    target_dir: the directory the file will be placed in.
    file_name: the desired (already sanitized) file name.
    Returns a path whose name does not collide case-insensitively with existing
    entries in the directory.
    """
    existing = set()
    if target_dir.is_dir():
        existing = {entry.name.lower() for entry in target_dir.iterdir()}
    unique_name = name_safety.name_safety_resolve_collision(file_name, existing)
    return target_dir / unique_name


def archive_layout_store_stream(
    paths: ArchivePaths,
    source_stream: BinaryIO,
    target_dir: Path,
    original_name: str,
) -> PlacedFile:
    """Stream content into the archive atomically, hashing as it is written.

    paths: resolved archive paths; imports use their journal-owned private staging namespace.
    source_stream: an open binary stream positioned at the start of the content.
    target_dir: the album folder the file should end up in.
    original_name: the source file name, sanitized before use.
    Returns a ``PlacedFile`` describing the stored file.
    """
    staging_dir = placement_staging_dir.get() or paths.internal_dir / "import-staging"
    file_operations_path(paths, staging_dir.relative_to(paths.root).as_posix())
    file_operations_path(paths, target_dir.relative_to(paths.root).as_posix())
    staging_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name_safety.name_safety_safe_file_name(original_name)
    staging_path = staging_dir / f"{uuid4().hex}.partial"

    written_size = 0
    source_hasher = hashlib.sha256()
    staging_created = False
    archive_layout_record(staging_path)
    try:
        with open(staging_path, "xb") as staging_handle:
            staging_created = True
            archive_layout_claim(staging_path)
            while True:
                block = source_stream.read(hashing.CHUNK_SIZE)
                if not block:
                    break
                staging_handle.write(block)
                source_hasher.update(block)
                written_size += len(block)
            staging_handle.flush()
            os.fsync(staging_handle.fileno())
        hasher_source = source_hasher.hexdigest()
        if hashing.hashing_sha256_file(staging_path) != hasher_source:
            raise OSError("staged content does not match the source stream")
        final_path = archive_layout_unique_target(target_dir, safe_name)
        archive_layout_record(final_path)
        archive_layout_publish(staging_path, final_path)
        if (
            final_path.stat().st_size != written_size
            or hashing.hashing_sha256_file(final_path) != hasher_source
        ):
            final_path.unlink()
            raise OSError("placed content does not match the source stream")
    except FileExistsError:
        if not staging_created:
            archive_layout_claim(staging_path, False)
        raise
    finally:
        if staging_created:
            staging_path.unlink(missing_ok=True)
    return PlacedFile(
        path=final_path,
        sha256=hasher_source,
        size=written_size,
        link_mode=LINK_MODE_COPY,
    )


def archive_layout_duplicate_file(
    source_path: Path, target_dir: Path, link_mode: str = LINK_MODE_COPY
) -> PlacedFile:
    """Place an additional copy of an already-stored file into another album.

    source_path: an existing archived file to duplicate.
    target_dir: the album folder receiving the additional copy.
    link_mode: ``copy`` or ``hardlink``; hardlink falls back to copy when the
        filesystem does not support it (for example exFAT).
    Returns a ``PlacedFile`` describing the new copy. No symlink is ever created.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    expected_hash = hashing.hashing_sha256_file(source_path)
    expected_size = source_path.stat().st_size
    final_path = archive_layout_unique_target(target_dir, source_path.name)
    effective_mode = link_mode
    staging_dir = placement_staging_dir.get() or target_dir
    staged = staging_dir / f"{uuid4().hex}.partial"
    try:
        if link_mode == LINK_MODE_HARDLINK:
            try:
                os.link(source_path, staged)
            except FileExistsError:
                raise
            except OSError:
                archive_layout_copy_exclusive(source_path, staged)
                effective_mode = LINK_MODE_COPY
        else:
            archive_layout_copy_exclusive(source_path, staged)
        if (
            staged.stat().st_size != expected_size
            or hashing.hashing_sha256_file(staged) != expected_hash
        ):
            raise OSError("staged album copy does not match the source")
        archive_layout_record(final_path)
        archive_layout_publish(staged, final_path)
    finally:
        staged.unlink(missing_ok=True)

    if (
        final_path.stat().st_size != expected_size
        or hashing.hashing_sha256_file(final_path) != expected_hash
    ):
        final_path.unlink()
        raise OSError("album copy does not match the source")
    return PlacedFile(
        path=final_path,
        sha256=expected_hash,
        size=expected_size,
        link_mode=effective_mode,
    )


def archive_layout_copy_exclusive(source: Path, destination: Path) -> None:
    """Copy and fsync bytes without ever replacing an existing destination."""
    created = False
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            created = True
            archive_layout_claim(destination)
            shutil.copyfileobj(reader, writer, hashing.CHUNK_SIZE)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, destination)
        archive_layout_sync(destination.parent)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        else:
            archive_layout_claim(destination, False)
        raise


def archive_layout_publish(source: Path, destination: Path) -> None:
    """Persist staged ownership before atomic no-clobber publication of that inode."""
    preparer = placement_preparer.get()
    if preparer is not None:
        preparer(source, destination)
    try:
        file_operations_publish(source, destination)
    except FileExistsError:
        archive_layout_claim(destination, False)
        raise


def archive_layout_relative_path(paths: ArchivePaths, absolute_path: Path) -> str:
    """Return an archive-relative POSIX path for storage in the catalog.

    paths: resolved archive paths.
    absolute_path: a path inside the archive.
    Returns the path relative to the archive root using forward slashes.
    """
    return absolute_path.resolve().relative_to(paths.root).as_posix()
