"""Device access interface.

Defines the contract every media source must satisfy so the rest of the
application never depends on ``pymobiledevice3`` directly. This keeps all logic
testable against an in-memory fake device and confines real USB/AFC concerns to
``afc_device.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import BinaryIO, Protocol, runtime_checkable

from ..catalog.models import PhoneItem


class DeviceError(RuntimeError):
    """Raised when the device is unavailable, untrusted, or an I/O call fails."""


@runtime_checkable
class MediaSource(Protocol):
    """A source of phone media that can be enumerated, read, and deleted from."""

    def device_udid(self) -> str | None:
        """Return the device's unique identifier, or None when unknown."""

    def device_enumerate(self) -> Iterable[PhoneItem]:
        """Yield metadata for every media item without reading file contents."""

    def device_open(self, phone_path: str) -> BinaryIO:
        """Open a media file for streaming binary reads."""

    def device_delete(self, phone_path: str) -> None:
        """Delete a media file from the phone (used only after verification)."""

    def device_album_map(self) -> dict[str, list[str]]:
        """Return a mapping of phone item path to album names, best effort."""
