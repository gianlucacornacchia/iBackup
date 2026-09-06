"""Catalog data models.

Plain dataclasses describing catalog rows shared across the repository, importer,
and service layers. These are storage models; UI-facing data-transfer objects
live in ``service/results.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ArchiveState(StrEnum):
    """Lifecycle state of an asset within the archive."""

    ACTIVE = "active"
    DELETED = "deleted"


class FileLocation(StrEnum):
    """On-disk location class of a stored file copy."""

    PHOTOS = "photos"
    DELETED = "deleted"


@dataclass
class Asset:
    """A single archived media asset keyed by its content hash."""

    sha256: str
    size: int
    original_name: str
    media_type: str
    asset_id: int | None = None
    captured_at: str | None = None
    imported_at: str | None = None
    verified_at: str | None = None
    first_seen_on_phone_at: str | None = None
    last_seen_on_phone_at: str | None = None
    present_on_phone: bool = True
    archive_state: ArchiveState = ArchiveState.ACTIVE
    phone_asset_id: str | None = None
    phone_path: str | None = None
    phone_size: int | None = None
    phone_modified_at: str | None = None


@dataclass
class AssetFile:
    """One on-disk copy of an asset (an album folder, _Unsorted, or Deleted)."""

    asset_id: int
    path: str
    location: FileLocation = FileLocation.PHOTOS
    album_id: int | None = None
    link_mode: str = "copy"
    file_id: int | None = None


@dataclass
class Album:
    """A phone album mirrored as a browsable folder."""

    name: str
    safe_name: str
    phone_album_id: str | None = None
    kind: str = "user"
    album_id: int | None = None


@dataclass
class ImportSession:
    """Summary of a single import run."""

    device_udid: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    added_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    session_id: int | None = None


@dataclass
class DeletionMark:
    """A staged mark-for-delete awaiting explicit commit."""

    target_type: str
    target_id: int
    marked_at: str | None = None
    reason: str | None = None
    committed_at: str | None = None
    mark_id: int | None = None


@dataclass
class PhoneItem:
    """A media item enumerated on the phone (device-layer input to import)."""

    phone_path: str
    size: int
    original_name: str
    media_type: str
    phone_asset_id: str | None = None
    modified_at: str | None = None
    captured_at: str | None = None
    album_names: list[str] = field(default_factory=list)
