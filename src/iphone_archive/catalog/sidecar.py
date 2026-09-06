"""Per-asset JSON sidecar files.

Each asset has a human-readable sidecar at ``.ibackup/sidecars/<sha256>.json``
recording its hash, size, original name, source path on the phone, capture time,
and album memberships. Sidecars make the catalog recoverable and let the archive
be understood without the application.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


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


def sidecar_path_for(sidecars_dir: Path, sha256: str) -> Path:
    """Return the sidecar file path for a given content hash.

    sidecars_dir: the ``.ibackup/sidecars`` directory.
    sha256: the asset content hash.
    Returns the full path to the asset's sidecar JSON file.
    """
    return sidecars_dir / f"{sha256}.json"


def sidecar_write(sidecars_dir: Path, data: SidecarData) -> Path:
    """Write a sidecar JSON file atomically and return its path.

    sidecars_dir: the ``.ibackup/sidecars`` directory (created if missing).
    data: the sidecar payload to serialize.
    Returns the path of the written sidecar file.
    """
    sidecars_dir.mkdir(parents=True, exist_ok=True)
    target = sidecar_path_for(sidecars_dir, data.sha256)
    temporary = target.with_suffix(".json.tmp")
    payload = json.dumps(asdict(data), indent=2, sort_keys=True, ensure_ascii=False)
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)
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
    )
