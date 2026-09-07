"""Headless application service facade.

Every operation the product offers is exposed here as a plain Python call
returning structured results. The CLI and the GUI are thin adapters over this
class, which is what guarantees full feature parity between them. No printing,
no widgets, and no argument parsing belong in this layer.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ..browse import gallery, thumbnails
from ..catalog import database, repository
from ..config import ArchivePaths, config_initialize_archive, config_is_archive
from ..core import albums, dedup, importer, phone_diff, reclaim, recycle, verifier
from ..core.archive_layout import LINK_MODE_COPY
from ..device.fake_device import FakeDevice
from ..device.interface import MediaSource
from ..settings import (
    Settings,
    settings_load,
    settings_remember_archive,
    settings_save,
    settings_validate,
)
from . import marks, selection
from .progress import ProgressHandle


class ArchiveNotFoundError(RuntimeError):
    """Raised when an operation targets a folder that is not an archive."""


class AppService:
    """Facade exposing every archive operation to any frontend."""

    def __init__(self, archive_root: Path) -> None:
        """Create a service bound to an archive root.

        archive_root: the archive directory to operate on.
        """
        self.archive_root = Path(archive_root)
        self.paths: ArchivePaths | None = None
        self.connection: sqlite3.Connection | None = None

    def app_service_initialize(self) -> ArchivePaths:
        """Create the archive folder structure and catalog.

        Returns the resolved ``ArchivePaths`` of the initialized archive.
        """
        self.paths = config_initialize_archive(self.archive_root)
        connection = database.database_connect(self.paths.catalog_path)
        database.database_initialize(connection)
        self.connection = connection
        settings_remember_archive(self.paths.root)
        return self.paths

    def app_service_open(self) -> ArchivePaths:
        """Open an existing archive.

        Returns the resolved ``ArchivePaths``. Raises ``ArchiveNotFoundError``
        when the folder has not been initialized.
        """
        if not config_is_archive(self.archive_root):
            raise ArchiveNotFoundError(f"not an ibackup archive: {self.archive_root}")
        return self.app_service_initialize()

    def app_service_require(self) -> tuple[sqlite3.Connection, ArchivePaths]:
        """Return the open connection and paths, opening the archive if needed.

        Returns a tuple of (connection, paths).
        """
        if self.connection is None or self.paths is None:
            self.app_service_open()
        assert self.connection is not None and self.paths is not None
        return self.connection, self.paths

    def app_service_close(self) -> None:
        """Close the catalog connection.

        Returns None.
        """
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def app_service_import(
        self,
        source: MediaSource,
        progress: ProgressHandle | None = None,
        link_mode: str = LINK_MODE_COPY,
    ) -> importer.ImportResult:
        """Import new media from a source into the archive.

        source: the media source to import from.
        progress: optional progress/cancellation handle.
        link_mode: ``copy`` or ``hardlink`` for extra album copies.
        Returns the ``ImportResult`` summary.
        """
        connection, paths = self.app_service_require()
        return importer.importer_run(connection, paths, source, progress, link_mode)

    def app_service_verify(
        self, progress: ProgressHandle | None = None, limit: int | None = None
    ) -> verifier.VerifyResult:
        """Verify archived files against their recorded hashes.

        progress: optional progress/cancellation handle.
        limit: when set, verify at most this many files.
        Returns the ``VerifyResult``.
        """
        connection, paths = self.app_service_require()
        return verifier.verifier_run(connection, paths, progress, limit)

    def app_service_dedup_report(self) -> dedup.DedupResult:
        """Report duplicate content and multi-album storage cost.

        Returns the ``DedupResult``. Nothing is deleted.
        """
        connection, paths = self.app_service_require()
        return dedup.dedup_report(connection, paths)

    def app_service_list_albums(self) -> list[albums.AlbumSummary]:
        """List albums with their active asset counts.

        Returns the album summaries.
        """
        connection, _ = self.app_service_require()
        return albums.albums_list(connection)

    def app_service_list_assets(
        self,
        album_id: int | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[gallery.AssetView]:
        """List assets, optionally filtered to one album.

        album_id: restrict to this album, or None for all.
        include_deleted: include recycled assets when True.
        limit: maximum number of assets to return.
        offset: number of assets to skip, for paged views.
        Returns the matching ``AssetView`` models.
        """
        connection, _ = self.app_service_require()
        return gallery.gallery_list_assets(connection, album_id, include_deleted, limit, offset)

    def app_service_list_unsorted(self) -> list[gallery.AssetView]:
        """List assets that belong to no album.

        Returns the album-less ``AssetView`` models.
        """
        connection, _ = self.app_service_require()
        return gallery.gallery_list_unsorted(connection)

    def app_service_list_recycled(self) -> list[gallery.AssetView]:
        """List assets held in the ``Deleted/`` recycle bin.

        Returns the recycled ``AssetView`` models.
        """
        connection, _ = self.app_service_require()
        return gallery.gallery_list_recycled(connection)

    def app_service_scan_phone(self, source: MediaSource) -> None:
        """Refresh present-on-phone state from a metadata-only device scan.

        source: the media source to enumerate.
        Returns None.
        """
        connection, _ = self.app_service_require()
        scanned_at = datetime.now().isoformat(timespec="seconds")
        phone_diff.phone_diff_scan_presence(connection, source, scanned_at)

    def app_service_deleted_on_phone(self) -> phone_diff.PhoneDiffResult:
        """List archived assets absent from the latest phone scan.

        Returns the read-only ``PhoneDiffResult``.
        """
        connection, paths = self.app_service_require()
        return phone_diff.phone_diff_list(connection, paths)

    def app_service_move_to_deleted(self, asset_ids: list[int]) -> recycle.RecycleResult:
        """Move assets into the reversible ``Deleted/`` recycle bin.

        asset_ids: the assets to recycle.
        Returns the ``RecycleResult``.
        """
        connection, paths = self.app_service_require()
        return recycle.recycle_move_to_deleted(connection, paths, asset_ids)

    def app_service_restore(self, asset_ids: list[int]) -> recycle.RecycleResult:
        """Restore recycled assets to the browsable ``Photos/`` tree.

        asset_ids: the assets to restore.
        Returns the ``RecycleResult``.
        """
        connection, paths = self.app_service_require()
        return recycle.recycle_restore(connection, paths, asset_ids)

    def app_service_purge(
        self, asset_ids: list[int], confirmed: bool = False
    ) -> recycle.RecycleResult:
        """Permanently delete assets from the archive after confirmation.

        asset_ids: the assets to purge.
        confirmed: must be True for anything to be removed.
        Returns the ``RecycleResult``.
        """
        connection, paths = self.app_service_require()
        return recycle.recycle_purge(connection, paths, asset_ids, confirmed)

    def app_service_reclaim(
        self,
        source: MediaSource,
        confirmed: bool = False,
        progress: ProgressHandle | None = None,
    ) -> reclaim.ReclaimResult:
        """Report or perform phone space reclamation.

        source: the media source to reclaim space on.
        confirmed: when False this is a non-destructive dry run.
        progress: optional progress/cancellation handle.
        Returns the ``ReclaimResult``. The archive is never modified.
        """
        connection, paths = self.app_service_require()
        return reclaim.reclaim_run(connection, paths, source, confirmed, progress)

    def app_service_mark(self, target_type: str, target_id: int, reason: str | None = None) -> int:
        """Stage a mark-for-delete on an asset or album.

        target_type: ``asset`` or ``album``.
        target_id: the id being marked.
        reason: optional note.
        Returns the new mark id.
        """
        connection, _ = self.app_service_require()
        return marks.marks_add(connection, target_type, target_id, reason)

    def app_service_mark_many(self, asset_ids: list[int], reason: str | None = None) -> list[int]:
        """Stage marks for several assets (multi-select).

        asset_ids: the assets to mark.
        reason: optional note applied to each mark.
        Returns the created mark ids.
        """
        connection, _ = self.app_service_require()
        return marks.marks_add_many(connection, asset_ids, reason)

    def app_service_list_marks(self) -> list[marks.MarkSummary]:
        """List staged, uncommitted deletion marks.

        Returns the pending marks.
        """
        connection, _ = self.app_service_require()
        return marks.marks_list_pending(connection)

    def app_service_unmark(self, mark_id: int) -> None:
        """Cancel a staged deletion mark.

        mark_id: the mark to remove.
        Returns None.
        """
        connection, _ = self.app_service_require()
        marks.marks_unmark(connection, mark_id)

    def app_service_commit_marks(
        self, confirmed: bool = False, purge: bool = False
    ) -> recycle.RecycleResult:
        """Apply staged marks by recycling or purging the marked assets.

        confirmed: must be True for anything to happen.
        purge: when True permanently delete instead of recycling.
        Returns the resulting ``RecycleResult``.
        """
        connection, paths = self.app_service_require()
        commit = marks.marks_commit(connection, confirmed)
        if not confirmed or not commit.asset_ids:
            return recycle.RecycleResult(skipped_count=commit.skipped_count)
        if purge:
            outcome = recycle.recycle_purge(connection, paths, commit.asset_ids, True)
        else:
            outcome = recycle.recycle_move_to_deleted(connection, paths, commit.asset_ids)
        return outcome

    def app_service_move_selection(
        self, asset_ids: list[int], album_name: str
    ) -> selection.SelectionResult:
        """Move a multi-selection of assets into another album.

        asset_ids: the selected assets.
        album_name: destination album display name.
        Returns the ``SelectionResult``.
        """
        connection, paths = self.app_service_require()
        return selection.selection_move_to_album(connection, paths, asset_ids, album_name)

    def app_service_stats(self) -> dict[str, int]:
        """Return headline archive counts for status displays.

        Returns a mapping with asset, file, album, recycled, and missing counts.
        """
        connection, _ = self.app_service_require()
        return {
            "assets": gallery.gallery_count_assets(connection),
            "assets_including_deleted": gallery.gallery_count_assets(
                connection, include_deleted=True
            ),
            "files": len(repository.repository_all_asset_files(connection)),
            "albums": len(repository.repository_list_albums(connection)),
            "recycled": len(recycle.recycle_list_deleted(connection)),
            "unsorted": albums.albums_unsorted_count(connection),
            "deleted_on_phone": len(repository.repository_list_deleted_from_phone(connection)),
        }

    def app_service_get_settings(self) -> Settings:
        """Read the persisted user preferences.

        Returns the stored ``Settings``. No archive needs to be open.
        """
        return settings_load()

    def app_service_update_settings(self, settings: Settings) -> Settings:
        """Persist user preferences after validating them.

        settings: the preferences to store.
        Returns the saved ``Settings``. Raises ``SettingsError`` when a value is
        not supported, in which case nothing is written.
        """
        settings_validate(settings)
        settings_save(settings)
        return settings

    def app_service_thumbnail(
        self,
        asset_id: int,
        size: int = thumbnails.DEFAULT_THUMBNAIL_SIZE,
        refresh: bool = False,
    ) -> thumbnails.ThumbnailResult:
        """Return a cached preview image for an asset, generating it if needed.

        asset_id: the asset to preview.
        size: bounding-box size in pixels for the longest edge.
        refresh: regenerate the preview even when one is already cached.
        Returns a ``ThumbnailResult``; unsupported media report an error instead.
        """
        connection, paths = self.app_service_require()
        asset = repository.repository_get_asset(connection, asset_id)
        if asset is None:
            result = thumbnails.ThumbnailResult("", None, False, "unknown asset")
        else:
            files = repository.repository_list_asset_files(connection, asset_id)
            if not files:
                result = thumbnails.ThumbnailResult(asset.sha256, None, False, "no stored copy")
            else:
                source = paths.root / files[0].path
                result = thumbnails.thumbnails_get(paths, asset.sha256, source, size, refresh)
        return result

    def app_service_clear_thumbnails(self) -> int:
        """Delete the whole thumbnail cache.

        Returns the number of cached preview files removed.
        """
        _, paths = self.app_service_require()
        return thumbnails.thumbnails_clear_cache(paths)


def app_service_fake_source(items: dict[str, bytes]) -> MediaSource:
    """Build an in-memory media source, used for demos and tests.

    items: mapping of phone path to file content.
    Returns a ``MediaSource`` backed by the fake device.
    """
    return FakeDevice(items)
