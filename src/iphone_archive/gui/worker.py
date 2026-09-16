"""Serialized archive work with worker-owned resources and queued GUI delivery.

The GUI owns controller state. Queue internals, ProgressHandle and ProgressMailbox
protect the only shared mutable state. Request/result data is detached at the
boundary; no service, connection, device, widget or exception object is exported.
"""

from __future__ import annotations

import inspect
import logging
import sqlite3
import sys
import traceback
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from typing import Literal

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from ..config import ArchivePaths
from ..device.interface import MediaSource
from ..service.app_service import ARCHIVE_FREE_OPERATIONS, AppService, app_service_preferences
from ..service.progress import ProgressEvent, ProgressHandle

LOGGER = logging.getLogger(__name__)
MAX_PENDING_REQUESTS = 32
EXPECTED_ERRORS = (
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    LookupError,
    sqlite3.Error,
    ImportError,
)
LIFECYCLE_OPERATIONS = frozenset({"open_archive", "create_archive", "close_archive"})
SERVICE_OPERATIONS = frozenset(
    name
    for name, method in vars(AppService).items()
    if name.startswith("app_service_")
    and callable(method)
    and name
    not in {
        "app_service_check_thread",
        "app_service_require",
        "app_service_open",
        "app_service_initialize",
        "app_service_close",
    }
)
SourceFactory = Callable[[str | None], AbstractContextManager[MediaSource]]
ServiceFactory = Callable[[Path], AppService]


@dataclass(frozen=True)
class WorkerFailure:
    """Error details detached from the worker's exception and traceback objects."""

    request_id: int
    operation: str
    error_type: str
    message: str
    traceback_text: str


@dataclass(frozen=True)
class WorkerResult:
    """One terminal result; cancellation is acknowledged, not merely requested."""

    request_id: int
    operation: str
    value: object = None
    cancelled: bool = False


def worker_copy_data(value: object) -> object:
    """Copy plain DTO data recursively, rejecting live resources rather than sharing them."""
    if value is None or isinstance(value, (str, bool, int, float, bytes, Path)):
        return value
    if isinstance(value, list):
        return [worker_copy_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(worker_copy_data(item) for item in value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Worker data dictionaries require string keys")
        return {key: worker_copy_data(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{item.name: worker_copy_data(getattr(value, item.name)) for item in fields(value)},
        )
    raise TypeError(f"Cannot transfer {type(value).__name__} across the GUI worker boundary")


def worker_failure(request_id: int, operation: str, error: BaseException) -> WorkerFailure:
    """Log an error and return text-only details safe for queued GUI delivery."""
    LOGGER.error(
        "Worker %s failed: %s", operation, error, exc_info=(type(error), error, error.__traceback__)
    )
    return WorkerFailure(
        request_id,
        operation,
        type(error).__name__,
        str(error),
        "".join(traceback.format_exception(error)),
    )


def worker_source(udid: str | None) -> AbstractContextManager[MediaSource]:
    """Construct the real phone context on the worker, never on the GUI thread."""
    from ..device.afc_device import AfcDevice

    return AfcDevice(udid=udid)


class ProgressMailbox:
    """Coalesce progress to at most one outstanding Qt notification per request."""

    def __init__(self, notify: Callable[[], None]) -> None:
        """Create before enqueueing; notify must be a thread-safe Qt signal emission."""
        self.notify = notify
        # progress_lock protects latest and notification_pending across both threads.
        self.progress_lock = Lock()
        self.latest: ProgressEvent | None = None
        self.notification_pending = False
        self.handle = ProgressHandle(self.worker_report)

    def worker_report(self, event: ProgressEvent) -> None:
        """Publish progress from the worker; thread safe, without holding locks during emit."""
        with self.progress_lock:
            self.latest = event
            notify = not self.notification_pending
            self.notification_pending = True
        if notify:
            self.notify()

    def worker_take(self) -> ProgressEvent | None:
        """Consume the latest update from the GUI; thread safe and bounded."""
        with self.progress_lock:
            latest = self.latest
            self.latest = None
            self.notification_pending = False
        return latest


@dataclass(frozen=True)
class WorkerRequest:
    """An accepted request: parameters transfer to the worker, progress is synchronized."""

    request_id: int
    operation: str
    parameters: dict[str, object]
    progress: ProgressMailbox
    device_udid: str | None = None


class WorkerSession:
    """Resource owner constructed, used and discarded exclusively inside QThread.run."""

    def __init__(self, service_factory: ServiceFactory, source_factory: SourceFactory) -> None:
        """Store factories; neither factory is called on the GUI thread."""
        self.service_factory = service_factory
        self.source_factory = source_factory
        self.service: AppService | None = None
        # Preferences live outside every archive, so they are served by their own
        # service when none is open. It is created on this thread, on demand.
        self.preferences: AppService | None = None

    def worker_preferences(self) -> AppService:
        """Return the preferences-only service, creating it on the worker thread.

        Returns an ``AppService`` bound to a sentinel root that is not an
        archive, so an operation that needs one fails instead of inventing one.
        """
        if self.preferences is None:
            self.preferences = app_service_preferences()
        return self.preferences

    def worker_close(self) -> None:
        """Close the current archive on its owning thread, including error paths."""
        if self.service is not None:
            try:
                self.service.app_service_close()
            finally:
                self.service = None

    def worker_execute(self, request: WorkerRequest) -> object:
        """Dispatch a data-only request on the worker; callers never receive live resources."""
        if request.operation == "close_archive":
            if request.parameters:
                raise TypeError("close_archive accepts no parameters")
            self.worker_close()
            return None
        if request.operation in {"open_archive", "create_archive"}:
            if self.service is not None:
                raise RuntimeError("Close the current archive before opening another")
            if set(request.parameters) != {"archive_root"}:
                raise TypeError("Opening an archive requires only archive_root")
            archive_root = request.parameters["archive_root"]
            if not isinstance(archive_root, (str, Path)):
                raise TypeError("archive_root must be a path")
            service = self.service_factory(Path(archive_root))
            try:
                paths = (
                    service.app_service_initialize()
                    if request.operation == "create_archive"
                    else service.app_service_open()
                )
            finally:
                if sys.exception() is not None:
                    service.app_service_close()
            self.service = service
            return paths
        if self.service is None:
            if request.operation not in ARCHIVE_FREE_OPERATIONS:
                raise RuntimeError("Open an archive before requesting service operations")
            target = self.worker_preferences()
        else:
            target = self.service
        method: Callable[..., object] = getattr(target, request.operation)
        parameters = dict(request.parameters)
        signature = inspect.signature(method)
        if "progress" in signature.parameters:
            parameters["progress"] = request.progress.handle
        if "source" in signature.parameters:
            signature.bind(**parameters, source=None)
            with self.source_factory(request.device_udid) as source:
                parameters["source"] = source
                return method(**parameters)
        signature.bind(**parameters)
        return method(**parameters)


class ServiceThread(QThread):
    """One blocking FIFO consumer; it never needs GUI event processing to finish."""

    reply = Signal(object)
    progress_available = Signal(int)

    def __init__(
        self,
        requests: Queue[WorkerRequest | None],
        service_factory: ServiceFactory,
        source_factory: SourceFactory,
        parent: QObject,
    ) -> None:
        """Bind the synchronized queue and immutable factories before starting the thread."""
        super().__init__(parent)
        self.setObjectName("ArchiveServiceWorker")
        self.requests = requests
        self.service_factory = service_factory
        self.source_factory = source_factory

    def run(self) -> None:
        """Qt-required entry point; delegate to the owning worker process."""
        self.worker_process()

    def worker_process(self) -> None:
        """Consume serialized work, closing SQLite and the lock before thread completion."""
        session = WorkerSession(self.service_factory, self.source_factory)
        try:
            while True:
                request = self.requests.get()
                try:
                    if request is None:
                        break
                    self.worker_run_request(session, request)
                finally:
                    self.requests.task_done()
        finally:
            try:
                session.worker_close()
            except EXPECTED_ERRORS as error:
                self.reply.emit(worker_failure(0, "shutdown", error))

    def worker_run_request(self, session: WorkerSession, request: WorkerRequest) -> None:
        """Emit exactly one terminal reply; unexpected failures terminate after cleanup."""
        reply: WorkerResult | WorkerFailure | None = None
        try:
            if request.progress.handle.progress_is_cancelled():
                reply = WorkerResult(request.request_id, request.operation, cancelled=True)
            else:
                value = worker_copy_data(session.worker_execute(request))
                reply = WorkerResult(
                    request.request_id,
                    request.operation,
                    value,
                    cancelled=getattr(value, "cancelled", False) is True,
                )
        except EXPECTED_ERRORS as error:
            reply = worker_failure(request.request_id, request.operation, error)
        finally:
            if reply is None:
                fatal_error = sys.exception()
                if fatal_error is not None:
                    reply = worker_failure(request.request_id, request.operation, fatal_error)
            if reply is not None:
                self.reply.emit(reply)


class WorkerController(QObject):
    """GUI-affine request supervisor; all public methods enforce their owner thread."""

    result_ready = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)
    progress_changed = Signal(int, object)
    stopped = Signal()
    request_submitted = Signal(int, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        service_factory: ServiceFactory = AppService,
        source_factory: SourceFactory = worker_source,
    ) -> None:
        """Create static infrastructure; the thread starts lazily on the first request."""
        super().__init__(parent)
        # Queue protects transport. One extra slot is reserved for shutdown, never user work.
        self.requests: Queue[WorkerRequest | None] = Queue(MAX_PENDING_REQUESTS + 1)
        self.service_thread = ServiceThread(self.requests, service_factory, source_factory, self)
        self.service_thread.reply.connect(
            self.worker_deliver_reply, Qt.ConnectionType.QueuedConnection
        )
        self.service_thread.progress_available.connect(
            self.worker_deliver_progress, Qt.ConnectionType.QueuedConnection
        )
        self.service_thread.finished.connect(
            self.worker_thread_finished, Qt.ConnectionType.QueuedConnection
        )
        # GUI-thread-only metadata; request parameters are not accessed after enqueueing.
        self.pending: dict[int, WorkerRequest] = {}
        self.next_request_id = 1
        self.archive_root: Path | None = None
        self.state: Literal["idle", "running", "stopping", "stopped"] = "idle"

    def worker_check_thread(self) -> None:
        """Reject cross-thread controller calls; cancellation crosses via ProgressHandle only."""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("WorkerController must be called on its owning GUI thread")

    def worker_submit(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
        *,
        device_udid: str | None = None,
    ) -> int:
        """Snapshot and enqueue work; GUI-thread only, raises on invalid/full/stopping state."""
        self.worker_check_thread()
        if self.state in {"stopping", "stopped"}:
            raise RuntimeError("Worker is shutting down and cannot accept requests")
        if self.state == "running" and not self.service_thread.isRunning():
            raise RuntimeError("Worker is finishing; wait for its stopped signal")
        if len(self.pending) >= MAX_PENDING_REQUESTS:
            raise RuntimeError("Worker request queue is full")
        if operation not in LIFECYCLE_OPERATIONS | SERVICE_OPERATIONS:
            raise ValueError(f"Unsupported worker operation: {operation}")
        if device_udid is not None and not isinstance(device_udid, str):
            raise TypeError("device_udid must be a string or None")
        parameters = {} if parameters is None else parameters
        if operation == "close_archive" and parameters:
            raise TypeError("close_archive accepts no parameters")
        if "source" in parameters or "progress" in parameters:
            raise ValueError("The worker owns source and progress parameters")
        copied = {name: worker_copy_data(value) for name, value in parameters.items()}
        request_id = self.next_request_id
        mailbox = ProgressMailbox(lambda: self.service_thread.progress_available.emit(request_id))
        request = WorkerRequest(request_id, operation, copied, mailbox, device_udid)
        self.pending[request_id] = request
        self.next_request_id += 1
        self.requests.put_nowait(request)
        if self.state == "idle":
            self.state = "running"
            self.service_thread.start()
        self.request_submitted.emit(request_id, operation)
        return request_id

    def worker_open(self, archive_root: Path, *, create: bool = False) -> int:
        """Open/create explicitly on the worker; GUI-thread only, never auto-opens at startup."""
        return self.worker_submit(
            "create_archive" if create else "open_archive", {"archive_root": archive_root}
        )

    def worker_cancel(self, request_id: int) -> None:
        """Request cooperative cancellation immediately; GUI-thread only, no queued worker slot."""
        self.worker_check_thread()
        request = self.pending.get(request_id)
        if request is None:
            raise ValueError(f"No pending worker request: {request_id}")
        request.progress.handle.progress_cancel()

    def worker_shutdown(self) -> None:
        """Stop accepting work and cancel all accepted requests; GUI-thread only, nonblocking."""
        self.worker_check_thread()
        if self.state == "idle":
            self.state = "stopped"
            self.stopped.emit()
        elif self.state == "running":
            self.state = "stopping"
            for request in self.pending.values():
                request.progress.handle.progress_cancel()
            self.requests.put_nowait(None)

    def worker_wait(self, timeout_ms: int | None = None) -> bool:
        """Join after shutdown; GUI-thread only. Timeout leaves the worker alive, never killed."""
        self.worker_check_thread()
        if self.state not in {"stopping", "stopped"}:
            raise RuntimeError("Request worker shutdown before waiting")
        if timeout_ms is not None and timeout_ms < 0:
            raise ValueError("Worker wait timeout must not be negative")
        stopped = (
            self.service_thread.wait()
            if timeout_ms is None
            else self.service_thread.wait(timeout_ms)
        )
        if not stopped:
            LOGGER.warning("Worker shutdown still waiting for a safe operation boundary")
        return stopped

    @Slot(int)
    def worker_deliver_progress(self, request_id: int) -> None:
        """Deliver the coalesced update on the GUI thread, ignoring terminal-request leftovers."""
        self.worker_check_thread()
        request = self.pending.get(request_id)
        if request is not None:
            event = request.progress.worker_take()
            if event is not None:
                self.progress_changed.emit(request_id, event)

    @Slot(object)
    def worker_deliver_reply(self, reply: WorkerResult | WorkerFailure) -> None:
        """Deliver a terminal reply on the GUI and release its bounded request slot."""
        self.worker_check_thread()
        if reply.request_id:
            self.worker_deliver_progress(reply.request_id)
            self.pending.pop(reply.request_id, None)
        if isinstance(reply, WorkerResult) and not reply.cancelled:
            if reply.operation in {"open_archive", "create_archive"}:
                if isinstance(reply.value, ArchivePaths):
                    self.archive_root = reply.value.root
                else:
                    reply = worker_failure(
                        reply.request_id,
                        reply.operation,
                        TypeError("Archive open returned invalid paths"),
                    )
            elif reply.operation == "close_archive":
                self.archive_root = None
        elif isinstance(reply, WorkerFailure) and reply.operation == "close_archive":
            self.archive_root = None
        if isinstance(reply, WorkerFailure):
            self.failed.emit(reply)
        elif reply.cancelled:
            self.cancelled.emit(reply)
        else:
            self.result_ready.emit(reply)

    @Slot()
    def worker_thread_finished(self) -> None:
        """Join before notifying views; unexpected exit fails pending work without replaying it."""
        self.worker_check_thread()
        self.service_thread.wait()
        shutting_down = self.state == "stopping"
        self.archive_root = None
        abandoned = list(self.pending.values())
        self.pending.clear()
        while True:
            try:
                self.requests.get_nowait()
            except Empty:
                break
            else:
                self.requests.task_done()
        for request in abandoned:
            self.failed.emit(
                worker_failure(
                    request.request_id,
                    request.operation,
                    RuntimeError(
                        "Worker stopped before completing this request; no automatic retry"
                    ),
                )
            )
        if not shutting_down:
            LOGGER.error("Worker exited unexpectedly; the next request starts a fresh session")
        self.state = "stopped" if shutting_down else "idle"
        self.stopped.emit()
