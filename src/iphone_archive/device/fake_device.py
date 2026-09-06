"""In-memory fake media source used by the test suite and dry runs.

Implements the ``MediaSource`` protocol over byte blobs so the whole pipeline —
import, verify, dedup, deleted-from-phone review, reclaim — can run offline with
no iPhone attached.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from typing import BinaryIO

from ..catalog.models import PhoneItem
from .interface import DeviceError


class FakeDevice:
    """A scriptable media source backed by an in-memory dictionary."""

    def __init__(
        self,
        items: dict[str, bytes] | None = None,
        udid: str = "FAKE-UDID",
        album_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Create a fake device.

        items: mapping of phone path to file content.
        udid: the identifier reported for this device.
        album_map: optional mapping of phone path to album names.
        """
        self.items: dict[str, bytes] = dict(items or {})
        self.udid = udid
        self.albums: dict[str, list[str]] = dict(album_map or {})
        self.deleted_paths: list[str] = []
        self.metadata: dict[str, dict[str, str]] = {}

    def device_udid(self) -> str | None:
        """Return the fake device identifier."""
        return self.udid

    def device_enumerate(self) -> Iterable[PhoneItem]:
        """Yield metadata for every fake item without reading contents."""
        for phone_path, content in sorted(self.items.items()):
            extra = self.metadata.get(phone_path, {})
            name = phone_path.rsplit("/", 1)[-1]
            yield PhoneItem(
                phone_path=phone_path,
                size=len(content),
                original_name=name,
                media_type=fake_device_media_type(name),
                phone_asset_id=extra.get("phone_asset_id"),
                modified_at=extra.get("modified_at"),
                captured_at=extra.get("captured_at"),
                album_names=list(self.albums.get(phone_path, [])),
            )

    def device_open(self, phone_path: str) -> BinaryIO:
        """Return a binary stream over a fake item's content."""
        if phone_path not in self.items:
            raise DeviceError(f"no such item on device: {phone_path}")
        return io.BytesIO(self.items[phone_path])

    def device_delete(self, phone_path: str) -> None:
        """Delete a fake item, recording the call for assertions."""
        if phone_path not in self.items:
            raise DeviceError(f"no such item on device: {phone_path}")
        del self.items[phone_path]
        self.albums.pop(phone_path, None)
        self.deleted_paths.append(phone_path)

    def device_album_map(self) -> dict[str, list[str]]:
        """Return the configured album mapping."""
        return dict(self.albums)


def fake_device_media_type(file_name: str) -> str:
    """Classify a file name as image or video by extension.

    file_name: the file name to classify.
    Returns ``video`` for known video extensions, otherwise ``image``.
    """
    video_extensions = {".mov", ".mp4", ".m4v", ".avi"}
    lowered = file_name.lower()
    result = "image"
    for extension in video_extensions:
        if lowered.endswith(extension):
            result = "video"
            break
    return result
