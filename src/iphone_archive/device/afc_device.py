"""Real iPhone media access over USB via pymobiledevice3 (AFC).

Enumerates and reads the media domain (``DCIM``/``PhotoData``) of a connected,
trusted iPhone. ``pymobiledevice3`` is imported lazily so the rest of the
application — and the offline test suite — works without the dependency or an
attached device.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import logging
import shutil
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock, get_ident
from typing import Any, BinaryIO, cast
from uuid import uuid4

from ..catalog.models import PhoneItem
from ..core.albums import (
    albums_asset_key_sql,
    albums_parse_location_data,
    albums_parse_photos_database,
)
from .interface import DeviceError

MEDIA_ROOTS = ("/DCIM",)
# Mirrors the DCIM tree with one cached low-resolution JPEG per asset (image or
# video poster frame). iOS keeps these locally even when "Optimize Storage" has
# offloaded the full-resolution original, and uses them for its own previews.
THUMBNAIL_ROOT = "/PhotoData/Thumbnails/V2"
PREVIEW_NAME_MARKER = " (offloaded preview)"
# Resolving a thumbnail costs two AFC round-trips (listdir + stat). Offloaded
# albums are typically thousands of paths deep and do not change between
# imports, so a resolved path is cached on disk and re-imports skip the AFC
# calls entirely for anything already resolved once.
PREVIEW_CACHE_DIR_NAME = ".ibackup-device-cache"
PREVIEW_CACHE_FILE_NAME = "offloaded-preview-cache.json"
IMAGE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".dng", ".tiff"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi"}
READ_CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)


class AfcReadStream(io.RawIOBase):
    """Forward-only AFC reader: at most one bounded remote read per readinto."""

    def __init__(self, device: AfcDevice, phone_path: str) -> None:
        """Open one remote handle and retain the size needed to detect truncation."""
        super().__init__()
        self.device = device
        self.handle: int | None = None
        self.client = device.afc_device_require_client()
        self.remaining = int(device.afc_device_stat(self.client, phone_path)["st_size"])
        self.handle = device.afc_device_call(self.client.fopen, phone_path, "r")
        device.streams.add(self)

    def readable(self) -> bool:
        """Return whether the stream supports binary reads."""
        return True

    def readinto(self, buffer: Any) -> int:
        """Read a bounded block, reporting unexpected EOF rather than partial success."""
        self.device.afc_device_check_thread()
        if self.closed:
            raise ValueError("read of closed AFC stream")
        requested = min(len(buffer), READ_CHUNK_SIZE, self.remaining)
        if requested == 0:
            return 0
        try:
            block = self.device.afc_device_call(self.client.fread, self.handle, requested)
            if not isinstance(block, bytes) or not block or len(block) > requested:
                raise DeviceError("invalid or truncated AFC file read")
            buffer[: len(block)] = block
            self.remaining -= len(block)
            return len(block)
        except Exception as error:
            raise DeviceError("failed to stream AFC file") from error

    def close(self) -> None:
        """Close the remote file exactly once, surfacing remote close failures."""
        self.device.afc_device_check_thread()
        if not self.closed:
            try:
                if self.handle is not None:
                    self.device.afc_device_call(self.client.fclose, self.handle)
            except Exception as error:
                raise DeviceError("failed to close AFC file") from error
            finally:
                self.device.streams.discard(self)
                super().close()


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
    """Worker-owned AFC source; cross-thread access fails before touching resources."""

    def __init__(self, udid: str | None = None) -> None:
        """Create a device wrapper.

        udid: optional identifier to select a specific device.
        """
        self.requested_udid = udid
        self.afc_client: Any | None = None
        self.lockdown: Any | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.streams: set[AfcReadStream] = set()
        self.album_cache: dict[str, list[str]] = {}
        self.preview_cache: dict[str, Any] | None = None
        self.preview_cache_dirty = False
        self.owner_lock = Lock()
        # The lock protects ownership assignment; all other state is worker-confined.
        self.owner_thread_id: int | None = None

    def afc_device_check_thread(self) -> None:
        """Bind first use to one worker and reject concurrent access from other threads."""
        with self.owner_lock:
            if self.owner_thread_id is None:
                self.owner_thread_id = get_ident()
            elif self.owner_thread_id != get_ident():
                raise DeviceError("AfcDevice must be used and closed on its owning worker thread")

    def afc_device_call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run synchronous or async pymobiledevice3 APIs on one persistent event loop."""
        self.afc_device_check_thread()

        async def invoke() -> Any:
            value = function(*args, **kwargs)
            return await value if inspect.isawaitable(value) else value

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise DeviceError("use the synchronous device adapter outside an active asyncio loop")
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
        return self.loop.run_until_complete(invoke())

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
            self.lockdown = self.afc_device_call(create_using_usbmux, serial=self.requested_udid)
            self.afc_client = self.afc_device_call(AfcService, lockdown=self.lockdown)
            if hasattr(self.afc_client, "__aenter__"):
                self.afc_device_call(self.afc_client.__aenter__)
        except Exception as error:
            try:
                self.device_close()
            except DeviceError as cleanup_error:
                raise DeviceError(
                    f"device connection and cleanup failed: {cleanup_error}"
                ) from error
            raise DeviceError(
                "no trusted iPhone found; connect via USB, unlock, and tap Trust"
            ) from error

    def device_close(self) -> None:
        """Release open files, AFC session, lockdown transport and the owned event loop."""
        self.afc_device_check_thread()
        errors: list[Exception] = []
        for stream in list(self.streams):
            try:
                stream.close()
            except Exception as error:
                errors.append(error)
        for client in (self.afc_client, self.lockdown):
            if client is not None:
                close = getattr(client, "aclose", None) or getattr(client, "close", None)
                if close is not None:
                    try:
                        self.afc_device_call(close)
                    except Exception as error:
                        errors.append(error)
        self.afc_client = self.lockdown = None
        if self.loop is not None:
            self.loop.close()
            self.loop = None
        if errors:
            raise DeviceError(f"failed to close device resources: {errors}") from errors[0]

    def __enter__(self) -> AfcDevice:
        """Connect and return the resource-owning source."""
        self.afc_device_require_client()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close every owned device resource at context exit."""
        self.device_close()

    def afc_device_require_client(self) -> Any:
        """Return the AFC client, connecting on first use.

        Returns the live AFC client instance.
        """
        self.afc_device_check_thread()
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
        items = [item for root in MEDIA_ROOTS for item in self.afc_device_walk(client, root)]
        albums, capture_times, locations = self.afc_device_photo_metadata()
        counts = Counter(item.original_name for item in items)

        self.album_cache = {}
        for item in items:
            # Bare keys exist only for legacy databases without ZDIRECTORY.
            # Never strip the directory from a modern metadata key.
            item.album_names = list(albums.get(item.phone_path, []))
            item.captured_at = capture_times.get(item.phone_path)
            location = locations.get(item.phone_path)
            if counts[item.original_name] == 1:
                if item.phone_path not in albums:
                    item.album_names = list(albums.get(item.original_name, []))
                if item.phone_path not in capture_times:
                    item.captured_at = capture_times.get(item.original_name)
                if location is None:
                    location = locations.get(item.original_name)
            if location is not None:
                item.latitude, item.longitude = location
            if item.album_names:
                self.album_cache[item.phone_path] = list(item.album_names)
        available = {item.phone_path for item in items}
        unavailable = {
            path: names for path, names in albums.items() if "/" in path and path not in available
        }
        previews: list[PhoneItem] = []
        if unavailable:
            udid = self.device_udid() or "unknown"
            for path, names in unavailable.items():
                preview = self.afc_device_offloaded_preview(client, path, udid)
                if preview is None:
                    continue
                preview.album_names = list(names)
                preview.captured_at = capture_times.get(path)
                preview_location = locations.get(path)
                if preview_location is not None:
                    preview.latitude, preview.longitude = preview_location
                previews.append(preview)
                self.album_cache[preview.phone_path] = list(names)
            self.afc_device_save_preview_cache()
            logger.warning(
                "%d album media paths across %d albums are not in the USB media inventory. "
                "These originals may be offloaded or outside the supported media roots. "
                "%d of them have a cached low-resolution preview on the phone and will be "
                "imported as previews; the remaining %d have no preview either. Download "
                "full originals to the phone and import again for full-resolution copies. "
                "No filename-based substitutions were made.",
                len(unavailable),
                len({name for names in unavailable.values() for name in names}),
                len(previews),
                len(unavailable) - len(previews),
            )
        for item in items:
            yield item
        for preview in previews:
            yield preview

    def afc_device_preview_cache_path(self) -> Path:
        """Return the on-disk location of the resolved-thumbnail cache."""
        return Path.cwd() / PREVIEW_CACHE_DIR_NAME / PREVIEW_CACHE_FILE_NAME

    def afc_device_load_preview_cache(self) -> dict[str, Any]:
        """Load the resolved-thumbnail cache once per device instance.

        Returns the parsed cache (``{udid: {phone_path: entry}}``), or an empty
        mapping when the file is missing, unreadable or malformed. A bad cache
        file is never fatal: it just means every path is re-resolved over AFC.
        """
        if self.preview_cache is not None:
            return self.preview_cache
        cache: Any = {}
        path = self.afc_device_preview_cache_path()
        try:
            if path.exists():
                cache = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.debug("ignoring unreadable offloaded-preview cache %s: %s", path, error)
            cache = {}
        self.preview_cache = cache if isinstance(cache, dict) else {}
        return self.preview_cache

    def afc_device_save_preview_cache(self) -> None:
        """Persist the resolved-thumbnail cache when a lookup added a new entry."""
        if not self.preview_cache_dirty or self.preview_cache is None:
            return
        path = self.afc_device_preview_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.preview_cache), encoding="utf-8")
            self.preview_cache_dirty = False
        except OSError as error:
            logger.debug("could not persist offloaded-preview cache %s: %s", path, error)

    def afc_device_offloaded_preview(
        self, client: Any, phone_path: str, udid: str = "unknown"
    ) -> PhoneItem | None:
        """Return a synthetic low-resolution stand-in for an offloaded original.

        client: the live AFC client.
        phone_path: an album-member path recorded in Photos.sqlite but absent from
            the USB media inventory (``device_enumerate``'s ``unavailable`` set).
        udid: the connected device's identifier, used to scope the on-disk cache
            so two phones never share resolved paths.
        Returns a ``PhoneItem`` reading the phone's own cached thumbnail (the same
        degraded preview iOS itself shows for an optimized-storage original), or
        None when no such cache entry exists either. Never raises: a lookup
        failure here must never break enumeration of real, present media. A
        path resolved once is remembered on disk, so later imports of the same
        still-offloaded photo skip the AFC round-trips entirely.
        """
        cache = self.afc_device_load_preview_cache()
        device_cache = cache.get(udid)
        if isinstance(device_cache, dict):
            cached = device_cache.get(phone_path)
            if isinstance(cached, dict):
                try:
                    return PhoneItem(
                        phone_path=str(cached["path"]),
                        size=int(cached["size"]),
                        original_name=self.afc_device_preview_name(
                            phone_path, str(cached["suffix"])
                        ),
                        media_type="image",
                        modified_at=cast(str | None, cached.get("modified_at")),
                        is_offloaded_preview=True,
                        offloaded_original_path=phone_path,
                    )
                except (KeyError, TypeError, ValueError):
                    logger.debug("ignoring malformed cached preview entry for %s", phone_path)
        thumbnail_dir = f"{THUMBNAIL_ROOT}{phone_path}"
        try:
            entries = [
                entry
                for entry in self.afc_device_call(client.listdir, thumbnail_dir)
                if entry not in (".", "..")
            ]
            for entry in entries:
                candidate = f"{thumbnail_dir}/{entry}"
                info = self.afc_device_stat(client, candidate)
                if info.get("st_ifmt") == "S_IFREG" and "st_size" in info:
                    suffix = entry[entry.rfind(".") :] if "." in entry else ".jpg"
                    modified_at = str(info.get("st_mtime")) if info.get("st_mtime") else None
                    cache.setdefault(udid, {})[phone_path] = {
                        "path": candidate,
                        "size": int(info["st_size"]),
                        "suffix": suffix,
                        "modified_at": modified_at,
                    }
                    self.preview_cache_dirty = True
                    return PhoneItem(
                        phone_path=candidate,
                        size=int(info["st_size"]),
                        original_name=self.afc_device_preview_name(phone_path, suffix),
                        media_type="image",
                        modified_at=modified_at,
                        is_offloaded_preview=True,
                        offloaded_original_path=phone_path,
                    )
        except Exception:
            logger.debug(
                "no cached preview available for offloaded path %s", phone_path, exc_info=True
            )
        return None

    @staticmethod
    def afc_device_preview_name(phone_path: str, suffix: str) -> str:
        """Build the ``" (offloaded preview)"``-marked display name for a preview.

        phone_path: the original album-member path the preview stands in for.
        suffix: the cached thumbnail's file extension, including the leading dot.
        Returns the synthetic original name stored on the ``PhoneItem``.
        """
        stem = phone_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return f"{stem}{PREVIEW_NAME_MARKER}{suffix}"

    def afc_device_walk(self, client: Any, directory: str) -> Iterable[PhoneItem]:
        """Recursively yield media items under a device directory.

        client: the live AFC client.
        directory: absolute device path to walk.
        Yields ``PhoneItem`` metadata entries.
        """
        try:
            entries = self.afc_device_call(client.listdir, directory)
        except Exception as error:
            raise DeviceError(f"incomplete media enumeration: cannot list {directory}") from error

        for entry in entries:
            if entry in (".", ".."):
                continue
            if "/" in entry or "\\" in entry:
                raise DeviceError(f"invalid AFC directory entry: {entry}")
            child_path = f"{directory}/{entry}"
            info = self.afc_device_stat(client, child_path)
            if info.get("st_ifmt") == "S_IFDIR":
                yield from self.afc_device_walk(client, child_path)
                continue
            media_type = afc_device_classify(entry)
            if media_type is None:
                continue
            if info.get("st_ifmt") != "S_IFREG" or "st_size" not in info:
                raise DeviceError(f"unsupported media file metadata: {child_path}")
            yield PhoneItem(
                phone_path=child_path,
                size=int(info["st_size"]),
                original_name=entry,
                media_type=media_type,
                modified_at=str(info.get("st_mtime")) if info.get("st_mtime") else None,
            )

    def afc_device_stat(self, client: Any, phone_path: str) -> dict[str, Any]:
        """Return AFC file information for a device path.

        client: the live AFC client.
        phone_path: absolute device path to stat.
        Returns the info dictionary; unreadable media metadata raises DeviceError.
        """
        try:
            info = dict(self.afc_device_call(client.stat, phone_path))
        except Exception as error:
            raise DeviceError(f"cannot stat media item: {phone_path}") from error
        return info

    def device_open(self, phone_path: str) -> BinaryIO:
        """Open a device media file for streaming binary reads."""
        try:
            stream = AfcReadStream(self, phone_path)
        except Exception as error:
            raise DeviceError(f"failed to read {phone_path}") from error
        return cast(BinaryIO, io.BufferedReader(stream, buffer_size=READ_CHUNK_SIZE))

    def device_delete(self, phone_path: str) -> None:
        """Reject real-device deletion until Photos-library semantics are validated.

        phone_path: the requested media path; no device connection or mutation occurs.
        Raw AFC unlink does not establish a safe Photos-library deletion contract.
        """
        raise DeviceError(
            "unsupported: real iPhone deletion is disabled pending Windows/iPhone "
            "Photos-library deletion validation; raw AFC file removal is not supported"
        )

    def device_album_map(self) -> dict[str, list[str]]:
        """Return album membership from Photos.sqlite when readable.

        Returns a mapping of phone path to album names; empty when the photo
        database is unavailable, in which case assets are filed under _Unsorted.
        """
        list(self.device_enumerate())
        return dict(self.album_cache)

    def afc_device_photo_metadata(
        self,
    ) -> tuple[dict[str, list[str]], dict[str, str], dict[str, tuple[float, float]]]:
        """Copy accessible Photos database/WAL and parse supported schemas best-effort."""
        directory = Path.cwd() / ".ibackup-device-cache" / uuid4().hex
        database_path = directory / "Photos.sqlite"
        membership: dict[str, list[str]] = {}
        capture_times: dict[str, str] = {}
        locations: dict[str, tuple[float, float]] = {}
        try:
            directory.mkdir(parents=True)
            for suffix in ("", "-wal"):
                try:
                    with self.device_open(f"/PhotoData/Photos.sqlite{suffix}") as reader:
                        with database_path.with_name(f"Photos.sqlite{suffix}").open("xb") as writer:
                            shutil.copyfileobj(reader, writer, READ_CHUNK_SIZE)
                except DeviceError:
                    if not suffix:
                        raise
            membership = albums_parse_photos_database(database_path)
            locations = albums_parse_location_data(database_path)
            connection = sqlite3.connect(database_path)
            try:
                for table in ("ZASSET", "ZGENERICASSET"):
                    try:
                        key_sql = albums_asset_key_sql(connection, table)
                        rows = connection.execute(
                            f"SELECT {key_sql}, asset.ZDATECREATED FROM {table} AS asset"
                        ).fetchall()
                    except sqlite3.Error:
                        continue
                    key_counts = Counter(key for key, _ in rows)
                    for key, seconds in rows:
                        if key and key_counts[key] == 1 and isinstance(seconds, (int, float)):
                            capture_times[str(key)] = (
                                datetime(2001, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
                            ).isoformat()
                    break
            finally:
                connection.close()
        except (DeviceError, OSError, sqlite3.Error, OverflowError, ValueError) as error:
            logger.warning("Photos metadata unavailable; continuing without it: %s", error)
        finally:
            if directory.exists():
                shutil.rmtree(directory)
        return membership, capture_times, locations
