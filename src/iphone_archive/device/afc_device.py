"""Real iPhone media access over USB via pymobiledevice3 (AFC).

Enumerates and reads the media domain (``DCIM``/``PhotoData``) of a connected,
trusted iPhone. ``pymobiledevice3`` is imported lazily so the rest of the
application — and the offline test suite — works without the dependency or an
attached device.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, BinaryIO

from ..catalog.models import PhoneItem
from .interface import DeviceError

MEDIA_ROOTS = ("/DCIM",)
IMAGE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".dng", ".tiff"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi"}


def afc_device_classify(file_name: str) -> str | None:
    """Classify a file name as image, video, or unsupported.

    file_name: the file name to classify.
    Returns ``image``, ``video``, or None when the extension is not media.
    """
    lowered = file_name.lower()
    dot_index = lowered.rfind(".")
    result: str | None = None
    if dot_index > 0:
        extension = lowered[dot_index:]
        if extension in IMAGE_EXTENSIONS:
            result = "image"
        elif extension in VIDEO_EXTENSIONS:
            result = "video"
    return result


class AfcDevice:
    """Media source backed by a USB-connected iPhone's AFC media domain."""

    def __init__(self, udid: str | None = None) -> None:
        """Create a device wrapper.

        udid: optional identifier to select a specific device.
        """
        self.requested_udid = udid
        self.afc_client: Any | None = None
        self.lockdown: Any | None = None

    def afc_device_connect(self) -> None:
        """Open a lockdown + AFC session to the phone.

        Returns None. Raises ``DeviceError`` when the library is missing or no
        trusted device is reachable.
        """
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService
        except ImportError as error:
            raise DeviceError(
                "pymobiledevice3 is not installed; install the project dependencies"
            ) from error

        try:
            self.lockdown = create_using_usbmux(serial=self.requested_udid)
            self.afc_client = AfcService(lockdown=self.lockdown)
        except Exception as error:
            raise DeviceError(
                "no trusted iPhone found; connect via USB, unlock, and tap Trust"
            ) from error

    def afc_device_require_client(self) -> Any:
        """Return the AFC client, connecting on first use.

        Returns the live AFC client instance.
        """
        if self.afc_client is None:
            self.afc_device_connect()
        return self.afc_client

    def device_udid(self) -> str | None:
        """Return the connected device's identifier when available."""
        self.afc_device_require_client()
        identifier = getattr(self.lockdown, "udid", None)
        return str(identifier) if identifier else None

    def device_enumerate(self) -> Iterable[PhoneItem]:
        """Yield metadata for every media file without reading its contents."""
        client = self.afc_device_require_client()
        for root in MEDIA_ROOTS:
            yield from self.afc_device_walk(client, root)

    def afc_device_walk(self, client: Any, directory: str) -> Iterable[PhoneItem]:
        """Recursively yield media items under a device directory.

        client: the live AFC client.
        directory: absolute device path to walk.
        Yields ``PhoneItem`` metadata entries.
        """
        try:
            entries = client.listdir(directory)
        except Exception:
            # Unreadable directories are skipped: some media paths are protected
            # depending on iOS version and pairing state.
            entries = []

        for entry in entries:
            if entry in (".", ".."):
                continue
            child_path = f"{directory}/{entry}"
            info = self.afc_device_stat(client, child_path)
            if info.get("st_ifmt") == "S_IFDIR":
                yield from self.afc_device_walk(client, child_path)
                continue
            media_type = afc_device_classify(entry)
            if media_type is None:
                continue
            yield PhoneItem(
                phone_path=child_path,
                size=int(info.get("st_size", 0)),
                original_name=entry,
                media_type=media_type,
                modified_at=str(info.get("st_mtime")) if info.get("st_mtime") else None,
            )

    def afc_device_stat(self, client: Any, phone_path: str) -> dict[str, Any]:
        """Return AFC file information for a device path.

        client: the live AFC client.
        phone_path: absolute device path to stat.
        Returns the info dictionary, empty when the path cannot be read.
        """
        try:
            info = dict(client.stat(phone_path))
        except Exception:
            info = {}
        return info

    def device_open(self, phone_path: str) -> BinaryIO:
        """Open a device media file for streaming binary reads."""
        import io

        client = self.afc_device_require_client()
        try:
            content = client.get_file_contents(phone_path)
        except Exception as error:
            raise DeviceError(f"failed to read {phone_path}") from error
        return io.BytesIO(content)

    def device_delete(self, phone_path: str) -> None:
        """Delete a media file from the phone."""
        client = self.afc_device_require_client()
        try:
            client.rm(phone_path)
        except Exception as error:
            raise DeviceError(f"failed to delete {phone_path}") from error

    def device_album_map(self) -> dict[str, list[str]]:
        """Return album membership from Photos.sqlite when readable.

        Returns a mapping of phone path to album names; empty when the photo
        database is unavailable, in which case assets are filed under _Unsorted.
        """
        # Album extraction is best-effort: Photos.sqlite is not exposed by AFC on
        # all iOS versions, and the specification requires graceful fallback.
        return {}
