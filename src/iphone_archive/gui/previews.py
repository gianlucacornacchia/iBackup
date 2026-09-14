"""Background preview pipeline for the gallery.

Thumbnails are the only part of the GUI that must scale to tens of thousands of
tiles, so they deliberately do **not** travel over the single service worker.
That worker owns the archive lock and serialises every catalog operation; an
import or a verify would otherwise stall every visible tile, and a fast scroll
would flood its 32-slot queue with work the user has already scrolled past.

Instead the loader renders from immutable data only - the archive root, the
asset SHA-256 and the archive-relative path already carried by ``AssetView`` -
on a dedicated ``QThreadPool``. No SQLite connection, service or device object
ever crosses this boundary, which is what allows it to run concurrently with the
service worker. Rendering reuses ``browse.thumbnails`` so the GUI and the
``ibackup thumbnail`` command produce and share exactly the same cache files.

Decoded pixmaps are held in a bounded LRU cache: a 1 297-item library at 256px
would otherwise retain hundreds of megabytes of decoded image data. Requests are
coalesced per cache key, scrolled-past requests are cancelled before they start,
and failures are remembered so a broken file is not retried on every repaint.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from ..browse import thumbnails
from ..config import ArchivePaths

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_ENTRIES = 512
MAX_CACHE_ENTRIES = 8192
# Enough outstanding work to cover a screenful plus a prefetch margin. Anything
# beyond that is almost certainly already scrolled out of view.
DEFAULT_PENDING_LIMIT = 96
MAX_PENDING_LIMIT = 1024
DEFAULT_WORKER_COUNT = 3
MAX_WORKER_COUNT = 16
MIN_PREVIEW_SIZE = 32
MAX_PREVIEW_SIZE = 2048
# Window close must not hang on an in-flight HEIC or video decode forever.
SHUTDOWN_WAIT_MS = 5000

PreviewKey = tuple[str, int]


class PreviewState(Enum):
    """What the view should paint for a tile right now."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class PreviewEntry:
    """A tile's current preview state; ``pixmap`` is set only when ready."""

    state: PreviewState
    pixmap: QPixmap | None = None
    error: str | None = None


@dataclass(frozen=True)
class PreviewReply:
    """A finished render crossing back from a pool thread to the GUI thread.

    ``token`` identifies the exact render that produced it. A cancelled task can
    already have emitted its reply before the cancellation is seen, so the key
    alone cannot distinguish it from the reply of a task that replaced it after
    the tile scrolled back into view.
    """

    key: PreviewKey
    token: Event
    image: QImage | None = None
    error: str | None = None


def previews_check_hash(sha256: str) -> str:
    """Reject preview keys that could escape the thumbnail cache folder.

    sha256: the content hash identifying the asset.
    Returns the validated hash. Raises ``ValueError`` for anything that is not a
    plain alphanumeric token, since the hash becomes part of a cache file name.
    """
    if not isinstance(sha256, str) or not sha256 or not sha256.isalnum():
        raise ValueError("Preview hash must be a non-empty alphanumeric string")
    return sha256


def previews_check_relative(relative_path: str) -> str:
    """Reject stored paths that do not stay inside the archive root.

    relative_path: an archive-relative path taken from an ``AssetView``.
    Returns the validated path. Raises ``ValueError`` when it is empty, absolute
    or contains a parent reference on either path flavour.
    """
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("Preview source path must be a non-empty string")
    for flavour in (PurePosixPath(relative_path), PureWindowsPath(relative_path)):
        if flavour.is_absolute() or flavour.anchor or ".." in flavour.parts:
            raise ValueError(f"Preview source path must stay inside the archive: {relative_path}")
    return relative_path


def previews_check_size(size: int) -> int:
    """Validate a requested bounding-box size.

    size: the longest-edge size in pixels.
    Returns the validated size. Raises ``ValueError`` when out of range.
    """
    if not isinstance(size, int) or isinstance(size, bool):
        raise ValueError("Preview size must be an integer")
    if not MIN_PREVIEW_SIZE <= size <= MAX_PREVIEW_SIZE:
        raise ValueError(f"Preview size must be between {MIN_PREVIEW_SIZE} and {MAX_PREVIEW_SIZE}")
    return size


class PreviewCache:
    """Bounded least-recently-used cache of decoded pixmaps, GUI-thread-only."""

    def __init__(self, capacity: int = DEFAULT_CACHE_ENTRIES) -> None:
        """Create an empty cache.

        capacity: how many decoded pixmaps to retain, 1..``MAX_CACHE_ENTRIES``.
        """
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise ValueError("Cache capacity must be an integer")
        if not 1 <= capacity <= MAX_CACHE_ENTRIES:
            raise ValueError(f"Cache capacity must be between 1 and {MAX_CACHE_ENTRIES}")
        self.capacity = capacity
        self.entries: OrderedDict[PreviewKey, QPixmap] = OrderedDict()

    def previews_cache_get(self, key: PreviewKey) -> QPixmap | None:
        """Return a cached pixmap and mark it most recently used.

        key: the hash/size pair identifying the preview.
        Returns the pixmap, or None when it is not cached.
        """
        pixmap = self.entries.get(key)
        if pixmap is not None:
            self.entries.move_to_end(key)
        return pixmap

    def previews_cache_put(self, key: PreviewKey, pixmap: QPixmap) -> None:
        """Store a pixmap, evicting the least recently used entries past capacity.

        key: the hash/size pair identifying the preview.
        pixmap: the decoded preview image.
        Returns None.
        """
        self.entries[key] = pixmap
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)

    def previews_cache_clear(self) -> None:
        """Drop every cached pixmap, for example when the archive changes."""
        self.entries.clear()

    def previews_cache_size(self) -> int:
        """Return how many pixmaps are currently retained."""
        return len(self.entries)


class PreviewBridge(QObject):
    """GUI-owned receiver whose signal carries pool results back queued."""

    finished = Signal(object)


class PreviewTask(QRunnable):
    """One render, cancellable up to the moment it starts decoding."""

    def __init__(
        self,
        bridge: PreviewBridge,
        archive_root: Path,
        key: PreviewKey,
        relative_path: str,
        cancelled: Event,
    ) -> None:
        """Capture immutable inputs only; no service, connection or widget is referenced."""
        super().__init__()
        self.bridge = bridge
        self.archive_root = archive_root
        self.key = key
        self.relative_path = relative_path
        self.cancelled = cancelled

    def run(self) -> None:
        """Render and decode one preview, always reporting exactly one outcome."""
        if self.cancelled.is_set():
            return
        reply = PreviewReply(self.key, self.cancelled, error="preview failed")
        try:
            sha256, size = self.key
            paths = ArchivePaths(self.archive_root)
            source = self.archive_root / Path(self.relative_path)
            result = thumbnails.thumbnails_get(paths, sha256, source, size)
            if self.cancelled.is_set():
                return
            if result.path is None:
                reply = PreviewReply(self.key, self.cancelled, error=result.error or "no preview")
            else:
                image = QImage(str(result.path))
                if image.isNull():
                    reply = PreviewReply(
                        self.key, self.cancelled, error="preview could not be decoded"
                    )
                else:
                    reply = PreviewReply(self.key, self.cancelled, image=image)
        except Exception as error:
            LOGGER.warning("preview task failed for %s: %s", self.relative_path, error)
            reply = PreviewReply(self.key, self.cancelled, error=str(error))
        finally:
            if not self.cancelled.is_set():
                self.bridge.finished.emit(reply)


class PreviewLoader(QObject):
    """GUI-affine supervisor of the preview pool, its LRU cache and its failures."""

    preview_ready = Signal(str, int)
    preview_failed = Signal(str, int, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        size: int = thumbnails.DEFAULT_THUMBNAIL_SIZE,
        cache_entries: int = DEFAULT_CACHE_ENTRIES,
        pending_limit: int = DEFAULT_PENDING_LIMIT,
        worker_count: int = DEFAULT_WORKER_COUNT,
    ) -> None:
        """Build an idle loader; no archive is bound and nothing is rendered yet.

        parent: owning QObject, normally the main window.
        size: initial bounding-box size in pixels.
        cache_entries: decoded-pixmap cache capacity.
        pending_limit: maximum outstanding renders before the oldest are dropped.
        worker_count: dedicated render threads, kept well below the CPU count so
            previews never starve the service worker.
        """
        super().__init__(parent)
        if not isinstance(pending_limit, int) or not 1 <= pending_limit <= MAX_PENDING_LIMIT:
            raise ValueError(f"Pending limit must be between 1 and {MAX_PENDING_LIMIT}")
        if not isinstance(worker_count, int) or not 1 <= worker_count <= MAX_WORKER_COUNT:
            raise ValueError(f"Worker count must be between 1 and {MAX_WORKER_COUNT}")
        self.size = previews_check_size(size)
        self.pending_limit = pending_limit
        self.cache = PreviewCache(cache_entries)
        self.pending: OrderedDict[PreviewKey, Event] = OrderedDict()
        self.failures: dict[PreviewKey, str] = {}
        self.archive_root: Path | None = None
        self.stopped = False
        self.bridge = PreviewBridge(self)
        self.bridge.finished.connect(self.previews_finished)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(worker_count)

    def previews_check_thread(self) -> None:
        """Reject cross-thread loader calls; pool results arrive through a queued signal."""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("PreviewLoader must be called on its owning GUI thread")

    def previews_set_archive(self, archive_root: Path | None) -> None:
        """Bind the archive previews are rendered from, discarding stale state.

        archive_root: the open archive root, or None when no archive is open.
        Returns None. Changing archives cancels in-flight work and clears both
        the pixmap cache and remembered failures, since identical hashes in a
        different archive resolve to different files.
        """
        self.previews_check_thread()
        if archive_root is not None and not isinstance(archive_root, Path):
            raise TypeError("Archive root must be a Path or None")
        if archive_root == self.archive_root:
            return
        self.previews_cancel_all()
        self.cache.previews_cache_clear()
        self.failures.clear()
        self.archive_root = archive_root

    def previews_set_size(self, size: int) -> None:
        """Switch to another bounding-box size, as the thumbnail_size setting allows.

        size: the new longest-edge size in pixels.
        Returns None. Cached previews at other sizes are kept, because the cache
        key includes the size and the LRU bound still applies.
        """
        self.previews_check_thread()
        size = previews_check_size(size)
        if size == self.size:
            return
        self.previews_cancel_all()
        self.size = size

    def previews_entry(self, sha256: str, relative_path: str) -> PreviewEntry:
        """Return a tile's preview, scheduling a background render on first request.

        sha256: the asset's content hash.
        relative_path: an archive-relative path of one stored copy.
        Returns a ready entry with a pixmap, a failed entry with an error, or a
        pending entry. This method never touches the disk on the GUI thread.
        """
        self.previews_check_thread()
        key = (previews_check_hash(sha256), self.size)
        relative_path = previews_check_relative(relative_path)
        pixmap = self.cache.previews_cache_get(key)
        if pixmap is not None:
            return PreviewEntry(PreviewState.READY, pixmap)
        error = self.failures.get(key)
        if error is not None:
            return PreviewEntry(PreviewState.FAILED, error=error)
        if key in self.pending:
            # Coalesced: one render per key regardless of how many tiles ask.
            self.pending.move_to_end(key)
        elif self.stopped:
            return PreviewEntry(PreviewState.FAILED, error="previews stopped")
        elif self.archive_root is None:
            return PreviewEntry(PreviewState.FAILED, error="no archive open")
        else:
            self.previews_schedule(key, relative_path)
        return PreviewEntry(PreviewState.PENDING)

    def previews_schedule(self, key: PreviewKey, relative_path: str) -> None:
        """Queue one render, dropping the oldest outstanding work past the bound.

        key: the hash/size pair to render.
        relative_path: the archive-relative source path.
        Returns None. Overflow cancels the least recently requested tiles, which
        are the ones furthest from the current viewport.
        """
        if self.archive_root is None:
            raise RuntimeError("Cannot schedule a preview without an open archive")
        while len(self.pending) >= self.pending_limit:
            stale_key, stale_event = self.pending.popitem(last=False)
            stale_event.set()
            LOGGER.debug("dropping scrolled-past preview %s", stale_key[0])
        cancelled = Event()
        self.pending[key] = cancelled
        task = PreviewTask(self.bridge, self.archive_root, key, relative_path, cancelled)
        self.pool.start(task)

    def previews_cancel_stale(self, keep: Iterable[str]) -> int:
        """Cancel outstanding renders for tiles that are no longer wanted.

        keep: the asset hashes still visible or prefetched.
        Returns how many pending renders were cancelled.
        """
        self.previews_check_thread()
        wanted = {previews_check_hash(sha256) for sha256 in keep}
        stale = [key for key in self.pending if key[0] not in wanted]
        for key in stale:
            self.pending.pop(key).set()
        return len(stale)

    def previews_cancel_all(self) -> int:
        """Cancel every outstanding render and ignore any results still in flight.

        Returns how many pending renders were cancelled. Already-running tasks
        finish their current decode but their results are discarded, because
        their token is no longer the accepted token for that key.
        """
        self.previews_check_thread()
        count = len(self.pending)
        for cancelled in self.pending.values():
            cancelled.set()
        self.pending.clear()
        return count

    def previews_retry(self, sha256: str | None = None) -> None:
        """Forget remembered failures so a tile is rendered again.

        sha256: a single asset hash, or None to clear every failure.
        Returns None.
        """
        self.previews_check_thread()
        if sha256 is None:
            self.failures.clear()
            return
        target = previews_check_hash(sha256)
        for key in [key for key in self.failures if key[0] == target]:
            del self.failures[key]

    @Slot(object)
    def previews_finished(self, reply: PreviewReply) -> None:
        """Absorb one render result on the GUI thread, ignoring superseded renders."""
        self.previews_check_thread()
        if not isinstance(reply, PreviewReply):
            raise TypeError("Preview replies must be PreviewReply instances")
        # Accept only the render still owning this key. A reply emitted just
        # before its cancellation must never fail the request that replaced it.
        if self.pending.get(reply.key) is not reply.token:
            return
        del self.pending[reply.key]
        sha256, size = reply.key
        if reply.image is None:
            message = reply.error or "preview failed"
            self.failures[reply.key] = message
            self.preview_failed.emit(sha256, size, message)
            return
        # QPixmap may only be created on the GUI thread, so the pool returns a
        # QImage and the conversion happens here.
        self.cache.previews_cache_put(reply.key, QPixmap.fromImage(reply.image))
        self.preview_ready.emit(sha256, size)

    def previews_shutdown(self, timeout_ms: int = SHUTDOWN_WAIT_MS) -> bool:
        """Stop accepting work and wait for render threads to reach a safe boundary.

        timeout_ms: how long to wait for running renders to return.
        Returns True when the pool is idle; False when a decode is still running,
        in which case the pool is left alive rather than being forced.
        """
        self.previews_check_thread()
        self.stopped = True
        self.previews_cancel_all()
        idle = self.pool.waitForDone(timeout_ms)
        if not idle:
            LOGGER.warning("preview threads still busy after %d ms", timeout_ms)
        return idle
