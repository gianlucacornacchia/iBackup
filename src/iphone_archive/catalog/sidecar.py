"""Per-asset JSON sidecar files.

Each asset has a human-readable sidecar at ``.ibackup/sidecars/<sha256>.json``
recording its hash, size, original name, source path on the phone, capture time,
and album memberships. Sidecars make the catalog recoverable and let the archive
be understood without the application.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from . import repository


@dataclass
class SidecarData:
    """Serializable metadata describing a single archived asset."""

    sha256: str
    size: int
    original_name: str
    media_type: str
    source_phone_path: str | None = None
    captured_at: str | None = None
    imported_at: str | None = None
    albums: list[str] = field(default_factory=list)
    archive_state: str = "active"
    files: list[dict[str, str | int | None]] = field(default_factory=list)


def sidecar_path_for(sidecars_dir: Path, sha256: str) -> Path:
    """Return the sidecar file path for a given content hash.

    sidecars_dir: the ``.ibackup/sidecars`` directory.
    sha256: the asset content hash.
    Returns the full path to the asset's sidecar JSON file.
    """
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ValueError("Invalid SHA-256 sidecar identifier")
    return sidecars_dir / f"{sha256}.json"


def sidecar_write(sidecars_dir: Path, data: SidecarData) -> Path:
    """Write a sidecar JSON file atomically and return its path.

    sidecars_dir: the ``.ibackup/sidecars`` directory (created if missing).
    data: the sidecar payload to serialize.
    Returns the path of the written sidecar file.
    """
    sidecars_dir.mkdir(parents=True, exist_ok=True)
    target = sidecar_path_for(sidecars_dir, data.sha256)
    temporary = target.with_suffix(f".{uuid4().hex}.pending")
    payload = json.dumps(asdict(data), indent=2, sort_keys=True, ensure_ascii=False)
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def sidecar_read(sidecars_dir: Path, sha256: str) -> SidecarData:
    """Read and parse a sidecar JSON file.

    sidecars_dir: the ``.ibackup/sidecars`` directory.
    sha256: the asset content hash whose sidecar to read.
    Returns the parsed ``SidecarData``.
    """
    target = sidecar_path_for(sidecars_dir, sha256)
    raw = json.loads(target.read_text(encoding="utf-8"))
    return SidecarData(
        sha256=raw["sha256"],
        size=raw["size"],
        original_name=raw["original_name"],
        media_type=raw["media_type"],
        source_phone_path=raw.get("source_phone_path"),
        captured_at=raw.get("captured_at"),
        imported_at=raw.get("imported_at"),
        albums=list(raw.get("albums", [])),
        archive_state=raw.get("archive_state", "active"),
        files=list(raw.get("files", [])),
    )


def sidecar_from_catalog(connection: sqlite3.Connection, asset_id: int) -> SidecarData:
    """Build recovery metadata from current catalog rows for asset_id."""
    asset = repository.repository_get_asset(connection, asset_id)
    if asset is None:
        raise ValueError(f"Unknown asset: {asset_id}")
    albums = connection.execute(
        "SELECT albums.name FROM albums JOIN asset_albums ON albums.id = album_id "
        "WHERE asset_id = ? ORDER BY albums.id",
        (asset_id,),
    ).fetchall()
    files = connection.execute(
        "SELECT asset_files.path, asset_files.location, asset_files.album_id, "
        "albums.name AS album_name, asset_files.link_mode FROM asset_files "
        "LEFT JOIN albums ON albums.id = asset_files.album_id WHERE asset_id = ? "
        "ORDER BY asset_files.id",
        (asset_id,),
    ).fetchall()
    return SidecarData(
        sha256=asset.sha256,
        size=asset.size,
        original_name=asset.original_name,
        media_type=asset.media_type,
        source_phone_path=asset.phone_path,
        captured_at=asset.captured_at,
        imported_at=asset.imported_at,
        albums=[str(row["name"]) for row in albums],
        archive_state=asset.archive_state.value,
        files=[dict(row) for row in files],
    )
