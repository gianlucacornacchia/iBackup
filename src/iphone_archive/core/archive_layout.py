"""Placement of asset files into the archive's plain album folders.

Files are written atomically: content is streamed into the hidden ``tmp`` folder
(hashing as it goes), then renamed into place. Multi-album assets get a real file
in every album folder, either copied or hardlinked; **symbolic links are never
created** so the archive stays valid when copied to another disk.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from ..config import ArchivePaths
from . import hashing, name_safety

LINK_MODE_COPY = "copy"
LINK_MODE_HARDLINK = "hardlink"


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

    paths: resolved archive paths (its temp folder is used for staging).
    source_stream: an open binary stream positioned at the start of the content.
    target_dir: the album folder the file should end up in.
    original_name: the source file name, sanitized before use.
    Returns a ``PlacedFile`` describing the stored file.
    """
    paths.temp_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name_safety.name_safety_safe_file_name(original_name)
    staging_path = paths.temp_dir / f"{safe_name}.partial"

    written_size = 0
    hasher_source = None
    with open(staging_path, "wb") as staging_handle:
        while True:
            block = source_stream.read(hashing.CHUNK_SIZE)
            if not block:
                break
            staging_handle.write(block)
            written_size += len(block)
    hasher_source = hashing.hashing_sha256_file(staging_path)

    final_path = archive_layout_unique_target(target_dir, safe_name)
    os.replace(staging_path, final_path)
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
    final_path = archive_layout_unique_target(target_dir, source_path.name)
    effective_mode = link_mode
    if link_mode == LINK_MODE_HARDLINK:
        try:
            os.link(source_path, final_path)
        except OSError:
            # Hardlinks are unavailable across devices and on exFAT/FAT volumes;
            # a real copy still satisfies the archive's "plain files" guarantee.
            shutil.copy2(source_path, final_path)
            effective_mode = LINK_MODE_COPY
    else:
        shutil.copy2(source_path, final_path)

    return PlacedFile(
        path=final_path,
        sha256=hashing.hashing_sha256_file(final_path),
        size=final_path.stat().st_size,
        link_mode=effective_mode,
    )


def archive_layout_relative_path(paths: ArchivePaths, absolute_path: Path) -> str:
    """Return an archive-relative POSIX path for storage in the catalog.

    paths: resolved archive paths.
    absolute_path: a path inside the archive.
    Returns the path relative to the archive root using forward slashes.
    """
    return absolute_path.resolve().relative_to(paths.root).as_posix()
