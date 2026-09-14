"""GUI-thread list models backed by bounded, serialized service queries.

Only fetchMore submits I/O. QModelIndex generations, request IDs and archive
mutation barriers keep stale pages and selections out of the current view.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Generic, Literal, TypeVar
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractProxyModel,
    QByteArray,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)

from ..browse.gallery import AssetView
from ..core.albums import AlbumSummary
from ..core.file_operations import file_operations_ids
from .worker import WorkerController, WorkerFailure, WorkerResult, worker_copy_data

LOGGER = logging.getLogger(__name__)
DEFAULT_PAGE_SIZE = 128
MAX_PAGE_SIZE = 512
ROOT_INDEX = QModelIndex()
ModelIndex = QModelIndex | QPersistentModelIndex
Row = TypeVar("Row", AssetView, AlbumSummary)
MODEL_MUTATIONS = frozenset(
    {
        "open_archive",
        "create_archive",
        "close_archive",
        "app_service_import",
        "app_service_scan_phone",
        "app_service_move_to_deleted",
        "app_service_restore",
        "app_service_purge",
        "app_service_commit_marks",
        "app_service_move_selection",
    }
)


@dataclass(frozen=True)
class AssetScope:
    """One browsing scope; album views contain active copies from that album only."""

    kind: Literal["all", "album", "unsorted", "recycled"] = "all"
    album_id: int | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous or invalid scope combinations before a query is submitted."""
        if self.kind not in {"all", "album", "unsorted", "recycled"}:
            raise ValueError(f"Unknown asset scope: {self.kind}")
        if self.kind == "album":
            if self.album_id is None:
                raise ValueError("Album scope requires an album ID")
            file_operations_ids([self.album_id])
        elif self.album_id is not None:
            raise ValueError("Only album scope accepts an album ID")


@dataclass(frozen=True)
class AssetSelection:
    """Exact copy IDs bound to a model generation, archive and browsing scope."""

    model_token: str
    revision: int
    archive_root: Path
    scope: AssetScope
    asset_ids: tuple[int, ...]
    file_ids: tuple[int, ...]


class AssetRole(IntEnum):
    """AssetView fields exposed to Qt views without exporting mutable DTOs."""

    ASSET_ID = Qt.ItemDataRole.UserRole + 1
    SHA256 = Qt.ItemDataRole.UserRole + 2
    ORIGINAL_NAME = Qt.ItemDataRole.UserRole + 3
    MEDIA_TYPE = Qt.ItemDataRole.UserRole + 4
    SIZE = Qt.ItemDataRole.UserRole + 5
    CAPTURED_AT = Qt.ItemDataRole.UserRole + 6
    PRESENT_ON_PHONE = Qt.ItemDataRole.UserRole + 7
    ARCHIVE_STATE = Qt.ItemDataRole.UserRole + 8
    PATHS = Qt.ItemDataRole.UserRole + 9
    FILE_IDS = Qt.ItemDataRole.UserRole + 10


class AlbumRole(IntEnum):
    """Album identity, labels and active asset counts."""

    ALBUM_ID = Qt.ItemDataRole.UserRole + 1
    NAME = Qt.ItemDataRole.UserRole + 2
    SAFE_NAME = Qt.ItemDataRole.UserRole + 3
    ASSET_COUNT = Qt.ItemDataRole.UserRole + 4


ASSET_FIELDS = {int(role): role.name.lower() for role in AssetRole}
ALBUM_FIELDS = {int(role): role.name.lower() for role in AlbumRole}


class PagedListModel(QAbstractListModel, Generic[Row]):
    """Cached rows with one outstanding page; all methods are GUI-thread-affine."""

    loading_changed = Signal(bool)
    error_changed = Signal(object)
    page_loaded = Signal(int)

    def __init__(
        self,
        worker: WorkerController,
        row_type: type[Row],
        parent: QObject | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        """Bind a worker and DTO type; construction and row access perform no queries."""
        worker.worker_check_thread()
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        super().__init__(parent)
        self.worker: WorkerController = worker
        self.row_type: type[Row] = row_type
        self.page_size: int = page_size
        self.rows: list[Row] = []
        self.identifiers: set[int] = set()
        self.pending_request: int | None = None
        self.submitting: bool = False
        self.transitioning: bool = False
        self.reset_requested: bool = False
        self.reset_active: bool | None = None
        self.revision: int = 1
        self.model_token: str = uuid4().hex
        self.active: bool = worker.archive_root is not None
        self.has_more: bool = True
        self.last_error: str | None = None
        worker.result_ready.connect(self.model_receive_page)
        worker.failed.connect(self.model_receive_failure)
        worker.cancelled.connect(self.model_receive_cancelled)

    @property
    def loading(self) -> bool:
        """Return whether this model is waiting for a page."""
        return self.submitting or self.pending_request is not None or self.transitioning

    def rowCount(self, parent: ModelIndex = ROOT_INDEX) -> int:
        """Return cached row count, not a database count; children do not exist."""
        self.worker.worker_check_thread()
        return 0 if parent.isValid() else len(self.rows)

    def index(
        self, row: int, column: int | None = 0, parent: ModelIndex = ROOT_INDEX
    ) -> QModelIndex:
        """Tag indexes with a reset generation so stale ordinary indexes are rejected."""
        self.worker.worker_check_thread()
        column = 0 if column is None else column
        if parent.isValid() or column != 0 or not 0 <= row < len(self.rows):
            return QModelIndex()
        return self.createIndex(row, column, self.revision)

    def model_valid_index(self, index: ModelIndex) -> bool:
        """Check ownership, generation and bounds without doing any I/O."""
        self.worker.worker_check_thread()
        return (
            index.isValid()
            and index.model() is self
            and index.column() == 0
            and index.internalId() == self.revision
            and 0 <= index.row() < len(self.rows)
        )

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        """Expose valid cached rows as enabled/selectable, never editable."""
        if not self.model_valid_index(index):
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def canFetchMore(self, parent: ModelIndex = ROOT_INDEX) -> bool:
        """Permit one page only while the current archive scope is usable."""
        self.worker.worker_check_thread()
        return (
            not parent.isValid()
            and self.active
            and self.worker.state == "running"
            and not self.loading
            and self.has_more
            and self.last_error is None
        )

    def model_query(self) -> tuple[str, dict[str, object]]:
        """Return the subclass's read operation and scope parameters."""
        raise NotImplementedError

    def fetchMore(self, parent: ModelIndex = ROOT_INDEX) -> None:
        """Request a bounded page plus one lookahead row; GUI-thread-only and nonblocking."""
        if not self.canFetchMore(parent):
            return
        operation, parameters = self.model_query()
        parameters.update(limit=self.page_size + 1, offset=len(self.rows))
        revision = self.revision
        self.submitting = True
        try:
            request_id = self.worker.worker_submit(operation, parameters)
        except (RuntimeError, ValueError, TypeError) as error:
            if revision == self.revision:
                self.model_error(str(error))
        else:
            if revision == self.revision:
                self.pending_request = request_id
            elif request_id in self.worker.pending:
                self.worker.worker_cancel(request_id)
        finally:
            self.submitting = False
        self.loading_changed.emit(self.loading)

    def model_reset(self, *, active: bool | None = None) -> None:
        """Cancel stale pages and defer reentrant resets until Qt's transaction has closed."""
        self.worker.worker_check_thread()
        self.reset_requested = True
        if active is not None:
            self.reset_active = active
        request_id = self.pending_request
        self.pending_request = None
        self.submitting = False
        if request_id is not None and request_id in self.worker.pending:
            self.worker.worker_cancel(request_id)
        if self.transitioning:
            return
        self.model_flush_reset()

    def model_apply_scope(self) -> None:
        """Apply any deferred scope inside a reset; album models have no scope to change."""

    def model_flush_reset(self) -> None:
        """Complete queued resets with fetches and selections blocked during Qt notifications."""
        while self.reset_requested:
            self.reset_requested = False
            self.transitioning = True
            try:
                self.beginResetModel()
                self.revision += 1
                self.rows.clear()
                self.identifiers.clear()
                self.has_more = True
                self.last_error = None
                if self.reset_active is not None:
                    self.active = self.reset_active
                    self.reset_active = None
                self.model_apply_scope()
                self.endResetModel()
            finally:
                self.transitioning = False
        self.loading_changed.emit(self.loading)
        self.error_changed.emit(self.last_error)

    def model_retry(self) -> None:
        """Explicitly retry a failed/cancelled page without discarding already loaded rows."""
        self.worker.worker_check_thread()
        self.last_error = None
        self.error_changed.emit(None)
        self.fetchMore()

    def model_error(self, message: str) -> None:
        """Surface a paging failure and stop automatic retries at the same offset."""
        self.worker.worker_check_thread()
        self.pending_request = None
        self.last_error = message
        LOGGER.error("%s: %s", type(self).__name__, message)
        self.loading_changed.emit(False)
        self.error_changed.emit(message)

    def model_validate_row(self, row: Row) -> int:
        """Validate subclass DTO fields and return its stable identity."""
        raise NotImplementedError

    def model_validate_page(self, value: object) -> list[Row]:
        """Reject malformed, oversized or duplicate pages before notifying Qt of inserts."""
        if not isinstance(value, list) or len(value) > self.page_size + 1:
            raise ValueError("Invalid or oversized model page")
        page: list[Row] = []
        seen: set[int] = set()
        for item in value:
            copied = worker_copy_data(item)
            if not isinstance(copied, self.row_type):
                raise TypeError(f"Expected {self.row_type.__name__} rows")
            identifier = self.model_validate_row(copied)
            if identifier in seen or identifier in self.identifiers:
                raise ValueError("Duplicate row identity; refresh the listing")
            seen.add(identifier)
            page.append(copied)
        return page

    @Slot(object)
    def model_receive_page(self, reply: WorkerResult) -> None:
        """Publish only the active request's detached rows using Qt insertion notifications."""
        self.worker.worker_check_thread()
        if reply.request_id != self.pending_request:
            return
        try:
            page = self.model_validate_page(reply.value)
        except (TypeError, ValueError) as error:
            self.model_error(str(error))
            return
        self.has_more = len(page) > self.page_size
        page = page[: self.page_size]
        self.transitioning = True
        try:
            if page:
                first = len(self.rows)
                self.beginInsertRows(ROOT_INDEX, first, first + len(page) - 1)
                self.rows.extend(page)
                self.identifiers.update(self.model_validate_row(row) for row in page)
                self.endInsertRows()
        finally:
            self.pending_request = None
            self.transitioning = False
        if self.reset_requested:
            self.model_flush_reset()
            return
        self.loading_changed.emit(self.loading)
        self.page_loaded.emit(len(page))

    @Slot(object)
    def model_receive_failure(self, failure: WorkerFailure) -> None:
        """Keep valid cached rows but expose failures for the current page only."""
        self.worker.worker_check_thread()
        if failure.request_id == self.pending_request:
            self.model_error(f"{failure.error_type}: {failure.message}")

    @Slot(object)
    def model_receive_cancelled(self, reply: WorkerResult) -> None:
        """Make a current-page cancellation explicit; cancelled stale requests are ignored."""
        self.worker.worker_check_thread()
        if reply.request_id == self.pending_request:
            self.model_error("Page request cancelled")


class AssetModel(PagedListModel[AssetView]):
    """Lazy active/all-album, single-album, unsorted or recycled asset rows."""

    def __init__(
        self,
        worker: WorkerController,
        parent: QObject | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        """Start with an empty all-active-assets scope."""
        super().__init__(worker, AssetView, parent, page_size=page_size)
        self.scope = AssetScope()
        self.pending_scope: AssetScope | None = None

    def model_query(self) -> tuple[str, dict[str, object]]:
        """Translate the current scope into a bounded service listing."""
        if self.scope.kind == "unsorted":
            return "app_service_list_unsorted", {}
        if self.scope.kind == "recycled":
            return "app_service_list_recycled", {}
        return "app_service_list_assets", {"album_id": self.scope.album_id}

    def asset_model_set_scope(self, scope: AssetScope) -> None:
        """Reset and cancel old pages when the view changes scope; GUI-thread-only."""
        self.worker.worker_check_thread()
        if not isinstance(scope, AssetScope):
            raise TypeError("Asset scope must be an AssetScope")
        self.pending_scope = scope
        self.model_reset()

    def model_apply_scope(self) -> None:
        """Change scope only inside a reset, never halfway through a page insertion."""
        if self.pending_scope is not None:
            self.scope = self.pending_scope
            self.pending_scope = None

    def model_validate_row(self, row: AssetView) -> int:
        """Require positive identity and aligned exact-copy paths/IDs; empty copies are visible."""
        file_operations_ids([row.asset_id])
        if len(row.paths) != len(row.file_ids) or any(
            not isinstance(path, str) for path in row.paths
        ):
            raise ValueError("Asset paths and file IDs must be aligned")
        if len(file_operations_ids(row.file_ids)) != len(row.file_ids):
            raise ValueError("Duplicate file IDs in asset row")
        return row.asset_id

    def roleNames(self) -> dict[int, QByteArray]:
        """Expose stable field names alongside Qt's standard display roles."""
        return {
            **super().roleNames(),
            **{role: QByteArray(name.encode()) for role, name in ASSET_FIELDS.items()},
        }

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Return cached metadata only; paths and file IDs are immutable tuples."""
        if not self.model_valid_index(index):
            return None
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return row.original_name
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(row.paths)
        if role in ASSET_FIELDS:
            value = getattr(row, ASSET_FIELDS[role])
            return tuple(value) if isinstance(value, list) else value
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        """Prevent selecting rows without exact copy IDs, rather than broadening their scope."""
        flags = super().flags(index)
        if self.model_valid_index(index) and not self.rows[index.row()].file_ids:
            flags &= ~Qt.ItemFlag.ItemIsSelectable
        return flags

    def asset_model_selection(self, indexes: Iterable[ModelIndex]) -> AssetSelection:
        """Map exact copies; proxy indexes must be persistent before any reset can occur.

        Ordinary stale proxy indexes can crash Qt's mapToSource. Callers must create
        QPersistentModelIndex values while those proxy indexes are still current.
        """
        self.worker.worker_check_thread()
        root = self.worker.archive_root
        if (
            not self.active
            or root is None
            or self.worker.state != "running"
            or self.transitioning
            or self.reset_requested
        ):
            raise ValueError("No active archive selection scope")
        selected: dict[int, AssetView] = {}
        for index in indexes:
            if isinstance(index.model(), QAbstractProxyModel) and not isinstance(
                index, QPersistentModelIndex
            ):
                raise ValueError(
                    "Proxy selections require persistent indexes captured while current"
                )
            source: ModelIndex = index
            while isinstance(source.model(), QAbstractProxyModel):
                proxy = source.model()
                if not isinstance(proxy, QAbstractProxyModel):
                    raise ValueError("Invalid proxy selection")
                source = proxy.mapToSource(source)
            if not self.model_valid_index(source):
                raise ValueError("Selection contains a foreign, stale or invalid index")
            row = self.rows[source.row()]
            if not row.file_ids:
                raise ValueError("Selected asset has no exact file-copy scope")
            selected[row.asset_id] = row
        files = tuple(
            dict.fromkeys(file_id for row in selected.values() for file_id in row.file_ids)
        )
        return AssetSelection(
            self.model_token, self.revision, root, self.scope, tuple(selected), files
        )

    def asset_model_selection_parameters(self, selection: AssetSelection) -> dict[str, object]:
        """Build copy-scoped mutation parameters immediately before enqueueing on the GUI."""
        self.worker.worker_check_thread()
        if (
            not self.active
            or self.transitioning
            or self.reset_requested
            or self.worker.state != "running"
            or selection.model_token != self.model_token
            or selection.revision != self.revision
            or selection.archive_root != self.worker.archive_root
            or selection.scope != self.scope
        ):
            raise ValueError("Selection is stale; select again in the current archive view")
        return {"asset_ids": list(selection.asset_ids), "file_ids": list(selection.file_ids)}


class AlbumModel(PagedListModel[AlbumSummary]):
    """Lazy album navigation rows with active asset counts."""

    def __init__(
        self,
        worker: WorkerController,
        parent: QObject | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        """Bind the worker without eagerly enumerating albums."""
        super().__init__(worker, AlbumSummary, parent, page_size=page_size)

    def model_query(self) -> tuple[str, dict[str, object]]:
        """Request an ordered album page with counts computed on the worker."""
        return "app_service_list_albums", {}

    def model_validate_row(self, row: AlbumSummary) -> int:
        """Validate album identity and count before exposing the page."""
        file_operations_ids([row.album_id])
        if type(row.asset_count) is not int or row.asset_count < 0:
            raise ValueError("Album asset count must be a non-negative integer")
        return row.album_id

    def roleNames(self) -> dict[int, QByteArray]:
        """Expose stable album field names and Qt's standard display roles."""
        return {
            **super().roleNames(),
            **{role: QByteArray(name.encode()) for role, name in ALBUM_FIELDS.items()},
        }

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Read cached identity/name/count data without requesting I/O."""
        if not self.model_valid_index(index):
            return None
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return row.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{row.name}: {row.asset_count} assets"
        if role in ALBUM_FIELDS:
            return getattr(row, ALBUM_FIELDS[role])
        return None


class ArchiveModels(QObject):
    """Own shared asset/album models and selection, invalidating them before archive edits."""

    def __init__(
        self,
        worker: WorkerController,
        parent: QObject | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        """Create model plumbing only; opening an archive still does not eagerly fetch pages."""
        super().__init__(parent)
        self.worker = worker
        self.archive_root = worker.archive_root
        self.barriers = {
            request_id
            for request_id, request in worker.pending.items()
            if request.operation in MODEL_MUTATIONS
        }
        self.assets = AssetModel(worker, self, page_size=page_size)
        self.albums = AlbumModel(worker, self, page_size=page_size)
        self.selection = QItemSelectionModel(self.assets, self)
        if self.barriers:
            self.assets.model_reset(active=False)
            self.albums.model_reset(active=False)
        worker.request_submitted.connect(self.models_request_submitted)
        worker.result_ready.connect(self.models_request_finished)
        worker.failed.connect(self.models_request_finished)
        worker.cancelled.connect(self.models_request_finished)
        worker.stopped.connect(self.models_stopped)

    @Slot(int, str)
    def models_request_submitted(self, request_id: int, operation: str) -> None:
        """Invalidate before queued mutations run, not after an already stale page is displayed."""
        self.worker.worker_check_thread()
        if operation in MODEL_MUTATIONS:
            self.barriers.add(request_id)
            self.assets.model_reset(active=False)
            self.albums.model_reset(active=False)

    @Slot(object)
    def models_request_finished(self, reply: WorkerResult | WorkerFailure) -> None:
        """Re-enable fresh reads only after all accepted mutations/lifecycle changes finish."""
        self.worker.worker_check_thread()
        if reply.request_id not in self.barriers:
            return
        self.barriers.remove(reply.request_id)
        if not self.barriers:
            self.models_refresh()

    def models_refresh(self) -> None:
        """Reset both models for the current archive; GUI-thread-only, no eager queries."""
        self.worker.worker_check_thread()
        if self.archive_root != self.worker.archive_root:
            self.assets.pending_scope = AssetScope()
        self.archive_root = self.worker.archive_root
        active = (
            self.archive_root is not None and not self.barriers and self.worker.state == "running"
        )
        self.assets.model_reset(active=active)
        self.albums.model_reset(active=active)

    @Slot()
    def models_stopped(self) -> None:
        """Clear old archive data and selections after shutdown or an unexpected worker exit."""
        self.worker.worker_check_thread()
        self.barriers.clear()
        self.models_refresh()
