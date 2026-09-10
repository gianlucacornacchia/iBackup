"""Fake archive data for the clickable mock.

MOCK ONLY. Nothing here touches a real archive, catalog or iPhone. Numbers are
invented so every screen can be reviewed with realistic-looking content before
any application code exists. Album names mirror the ones found on the test
device so the mock reads like a real library.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap


@dataclass
class MockAsset:
    """One photo or video as the grid and viewer need to show it."""

    asset_id: int
    name: str
    media_type: str
    size: int
    captured_at: str
    albums: list[str]
    on_phone: bool = True
    verified_at: str = "2026-09-07"
    sha256: str = "a3f1c09e77b41d2e5c8a0f6b93d47e15c2f8a9b0d1e3f4a5b6c7d8e9f0a1b2c3"
    gone_from_phone_at: str = ""
    marked_reason: str = ""
    duration_seconds: int = 0


@dataclass
class MockAlbum:
    """An album as the navigation pane shows it."""

    album_id: int
    name: str
    asset_ids: list[int] = field(default_factory=list)


ALBUM_NAMES = [
    "USA 2022",
    "Barcellona 2021",
    "Sardegna 2021",
    "Siviglia 2022",
    "WhatsApp",
    "Favourites",
]
EXTENSIONS = {"image": ".HEIC", "video": ".MOV"}


class MockArchive:
    """An in-memory stand-in for the archive, with stable pseudo-random content."""

    def __init__(self) -> None:
        """Build a deterministic fake library of assets and albums."""
        self.random = random.Random(20260910)
        self.assets: dict[int, MockAsset] = {}
        self.albums: list[MockAlbum] = []
        self.marked_ids: set[int] = set()
        self.thumbnail_cache: dict[int, QPixmap] = {}
        self.mock_archive_build()

    def mock_archive_build(self) -> None:
        """Populate assets, album membership, phone-deleted and marked sets."""
        next_id = 1
        for album_index, album_name in enumerate(ALBUM_NAMES, start=1):
            album = MockAlbum(album_id=album_index, name=album_name)
            for _ in range(self.random.randint(14, 26)):
                asset = self.mock_archive_make_asset(next_id, [album_name])
                self.assets[next_id] = asset
                album.asset_ids.append(next_id)
                next_id += 1
            self.albums.append(album)

        # Assets that belong to no album land in _Unsorted.
        self.unsorted_ids: list[int] = []
        for _ in range(22):
            self.assets[next_id] = self.mock_archive_make_asset(next_id, [])
            self.unsorted_ids.append(next_id)
            next_id += 1

        every_id = list(self.assets)
        self.deleted_on_phone_ids = self.random.sample(every_id, 12)
        for asset_id in self.deleted_on_phone_ids:
            self.assets[asset_id].on_phone = False
            self.assets[asset_id].gone_from_phone_at = "2026-08-14"

        self.recycled_ids = self.random.sample(
            [i for i in every_id if i not in self.deleted_on_phone_ids], 7
        )
        for asset_id in self.random.sample(every_id, 4):
            self.marked_ids.add(asset_id)
            self.assets[asset_id].marked_reason = "blurry"

    def mock_archive_make_asset(self, asset_id: int, albums: list[str]) -> MockAsset:
        """Create one plausible asset.

        asset_id: identifier used by the grid and viewer.
        albums: album names the asset belongs to.
        Returns the populated MockAsset.
        """
        media_type = "video" if self.random.random() < 0.06 else "image"
        size = (
            self.random.randint(28_000_000, 240_000_000)
            if media_type == "video"
            else self.random.randint(900_000, 4_600_000)
        )
        duration = self.random.randint(4, 340) if media_type == "video" else 0
        month = self.random.randint(1, 9)
        day = self.random.randint(1, 28)
        return MockAsset(
            asset_id=asset_id,
            name=f"IMG_{4000 + asset_id}{EXTENSIONS[media_type]}",
            media_type=media_type,
            size=size,
            captured_at=f"2026-{month:02d}-{day:02d}",
            duration_seconds=duration,
            albums=list(albums),
        )

    def mock_archive_assets_for(self, view_key: str) -> list[MockAsset]:
        """Return the assets shown for a navigation entry.

        view_key: one of ``all``, ``unsorted``, ``deleted-phone``, ``recycled``,
            ``marked``, or ``album:<name>``.
        Returns the matching assets in display order.
        """
        if view_key == "all":
            identifiers: list[int] = list(self.assets)
        elif view_key == "unsorted":
            identifiers = list(self.unsorted_ids)
        elif view_key == "deleted-phone":
            identifiers = list(self.deleted_on_phone_ids)
        elif view_key == "recycled":
            identifiers = list(self.recycled_ids)
        elif view_key == "marked":
            identifiers = sorted(self.marked_ids)
        else:
            name = view_key.split(":", 1)[1]
            album = next(a for a in self.albums if a.name == name)
            identifiers = list(album.asset_ids)
        return [self.assets[i] for i in identifiers]

    def mock_archive_thumbnail(self, asset: MockAsset) -> QPixmap:
        """Return a generated placeholder thumbnail for an asset.

        asset: the asset to draw a stand-in image for.
        Returns a cached QPixmap; the real GUI would call app_service_thumbnail.
        A drawn gradient keeps the mock free of binary image assets.
        """
        cached = self.thumbnail_cache.get(asset.asset_id)
        if cached is not None:
            return cached

        size = 240
        pixmap = QPixmap(size, size)
        seed = random.Random(asset.asset_id)
        hue = seed.randint(0, 359)
        top = QColor.fromHsl(hue, 90, 150)
        bottom = QColor.fromHsl((hue + 40) % 360, 110, 95)
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(0, 0, size, size, gradient)
        painter.setPen(QColor(255, 255, 255, 190))
        font = QFont()
        font.setPointSize(12)
        painter.setFont(font)
        label = asset.name.split(".")[0]
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

        self.thumbnail_cache[asset.asset_id] = pixmap
        return pixmap


def mock_data_format_size(num_bytes: int) -> str:
    """Format a byte count the way the UI should show it.

    num_bytes: the size to format.
    Returns a short human-readable string such as ``4.2 MB``.
    """
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def mock_data_format_duration(seconds: int) -> str:
    """Render a clip length the way a video tile badge shows it.

    seconds: the clip length.
    Returns a m:ss string.
    """
    return f"{seconds // 60}:{seconds % 60:02d}"
