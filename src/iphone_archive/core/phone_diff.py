"""Detection of archived assets that no longer exist on the phone.

Read-only: it reports which archived assets were absent from the most recent
phone scan so the user can decide what to do with them. It never touches the
phone and never modifies the archive.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ..catalog import repository
from ..catalog.models import Asset
from ..config import ArchivePaths
from ..device.interface import MediaSource


@dataclass
class DeletedFromPhoneItem:
    """An archived asset that was not seen in the latest phone scan."""

    asset_id: int
    sha256: str
    original_name: str
    size: int
    last_seen_on_phone_at: str | None
    paths: list[str] = field(default_factory=list)


@dataclass
class PhoneDiffResult:
    """Summary of a deleted-from-phone detection run."""

    items: list[DeletedFromPhoneItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Return how many archived assets are gone from the phone."""
        return len(self.items)

    @property
    def total_bytes(self) -> int:
        """Return the archive bytes represented by those assets."""
        return sum(item.size for item in self.items)


def phone_diff_scan_presence(
    connection: sqlite3.Connection, source: MediaSource, scanned_at: str
) -> None:
    """Refresh present-on-phone flags from a metadata-only device scan.

    connection: an open catalog connection.
    source: the media source to enumerate (no file contents are read).
    scanned_at: ISO timestamp recorded as the last-seen time.
    Returns None.
    """
    repository.repository_mark_all_absent(connection)
    for item in source.device_enumerate():
        known = repository.repository_find_by_phone_identity(
            connection, item.phone_asset_id, item.phone_path, item.size
        )
        if known is not None and known.asset_id is not None:
            repository.repository_mark_present(connection, known.asset_id, scanned_at)
    connection.commit()


def phone_diff_list(connection: sqlite3.Connection, paths: ArchivePaths) -> PhoneDiffResult:
    """List active archived assets absent from the latest phone scan.

    connection: an open catalog connection.
    paths: resolved archive paths.
    Returns a ``PhoneDiffResult``; nothing is modified on disk or on the phone.
    """
    result = PhoneDiffResult()
    for asset in repository.repository_list_deleted_from_phone(connection):
        if asset.asset_id is None:
            continue
        stored_files = repository.repository_list_asset_files(connection, asset.asset_id)
        result.items.append(
            DeletedFromPhoneItem(
                asset_id=asset.asset_id,
                sha256=asset.sha256,
                original_name=asset.original_name,
                size=asset.size,
                last_seen_on_phone_at=asset.last_seen_on_phone_at,
                paths=[stored.path for stored in stored_files],
            )
        )
    return result


def phone_diff_asset_still_on_phone(connection: sqlite3.Connection, asset_id: int) -> bool:
    """Report whether an archived asset was seen in the latest scan.

    connection: an open catalog connection.
    asset_id: the asset to test.
    Returns True when the asset is still present on the phone.
    """
    row = connection.execute(
        "SELECT present_on_phone FROM assets WHERE id = ?", (asset_id,)
    ).fetchone()
    return bool(row["present_on_phone"]) if row is not None else False


def phone_diff_assets_by_id(connection: sqlite3.Connection, asset_ids: list[int]) -> list[Asset]:
    """Fetch assets by id, preserving the requested order.

    connection: an open catalog connection.
    asset_ids: the asset ids to fetch.
    Returns the matching ``Asset`` records that exist.
    """
    found: list[Asset] = []
    for asset_id in asset_ids:
        row = connection.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is not None:
            found.append(repository.repository_row_to_asset(row))
    return found
