"""Archive paths and configuration.

Defines the on-disk archive structure (browsable ``Photos/`` album folders, the
``Deleted/`` recycle bin, and the hidden ``.ibackup/`` internals) and resolves
the paths used by every other module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PHOTOS_DIR_NAME = "Photos"
DELETED_DIR_NAME = "Deleted"
INTERNAL_DIR_NAME = ".ibackup"
UNSORTED_ALBUM_NAME = "_Unsorted"

CATALOG_FILE_NAME = "catalog.sqlite"
SIDECARS_DIR_NAME = "sidecars"
THUMBNAILS_DIR_NAME = "thumbnails"
TEMP_DIR_NAME = "tmp"
LOGS_DIR_NAME = "logs"


@dataclass(frozen=True)
class ArchivePaths:
    """Resolved locations of every part of an archive."""

    root: Path

    @property
    def photos_dir(self) -> Path:
        """Return the browsable album root (``Photos/``)."""
        return self.root / PHOTOS_DIR_NAME

    @property
    def deleted_dir(self) -> Path:
        """Return the recycle-bin root (``Deleted/``)."""
        return self.root / DELETED_DIR_NAME

    @property
    def internal_dir(self) -> Path:
        """Return the hidden internals folder (``.ibackup/``)."""
        return self.root / INTERNAL_DIR_NAME

    @property
    def catalog_path(self) -> Path:
        """Return the SQLite catalog path."""
        return self.internal_dir / CATALOG_FILE_NAME

    @property
    def sidecars_dir(self) -> Path:
        """Return the per-asset JSON sidecar folder."""
        return self.internal_dir / SIDECARS_DIR_NAME

    @property
    def thumbnails_dir(self) -> Path:
        """Return the thumbnail cache folder."""
        return self.internal_dir / THUMBNAILS_DIR_NAME

    @property
    def temp_dir(self) -> Path:
        """Return the staging folder used for atomic writes."""
        return self.internal_dir / TEMP_DIR_NAME

    @property
    def logs_dir(self) -> Path:
        """Return the log folder."""
        return self.internal_dir / LOGS_DIR_NAME

    @property
    def unsorted_dir(self) -> Path:
        """Return the album-less asset root (``Photos/_Unsorted``)."""
        return self.photos_dir / UNSORTED_ALBUM_NAME


def config_resolve_paths(archive_root: Path) -> ArchivePaths:
    """Resolve all archive paths from a root folder.

    archive_root: the archive root directory (may be relative).
    Returns an ``ArchivePaths`` describing every archive location.
    """
    return ArchivePaths(root=Path(archive_root).expanduser().resolve())


def config_initialize_archive(archive_root: Path) -> ArchivePaths:
    """Create the archive folder structure if it does not already exist.

    archive_root: the archive root directory to initialize.
    Returns the resolved ``ArchivePaths`` for the initialized archive.
    """
    paths = config_resolve_paths(archive_root)
    for directory in (
        paths.photos_dir,
        paths.unsorted_dir,
        paths.deleted_dir,
        paths.internal_dir,
        paths.sidecars_dir,
        paths.thumbnails_dir,
        paths.temp_dir,
        paths.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def config_is_archive(archive_root: Path) -> bool:
    """Report whether a folder looks like an initialized archive.

    archive_root: the directory to test.
    Returns True when the hidden internals folder exists.
    """
    paths = config_resolve_paths(archive_root)
    return paths.internal_dir.is_dir()
