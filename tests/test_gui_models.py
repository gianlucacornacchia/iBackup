"""Offscreen paging, index lifetime and exact-copy selection regressions."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from queue import Queue
from threading import get_ident
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtTest import QAbstractItemModelTester  # noqa: E402

from iphone_archive.browse.gallery import AssetView  # noqa: E402
from iphone_archive.core.albums import AlbumSummary  # noqa: E402
from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui.models import (  # noqa: E402
    DEFAULT_PAGE_SIZE,
    AlbumRole,
    ArchiveModels,
    AssetRole,
    AssetScope,
)
from iphone_archive.gui.worker import (  # noqa: E402
    WorkerController,
    WorkerFailure,
    WorkerResult,
)
from iphone_archive.service.app_service import AppService  # noqa: E402


class ManualWorker(QObject):
    """Deterministic GUI delivery double; real QThread integration is tested below."""

    result_ready = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)
    request_submitted = Signal(int, str)
    stopped = Signal()

    def __init__(self, root):
        super().__init__()
        self.archive_root = root
        self.state = "running"
        self.pending = {}
        self.calls = []
        self.cancellations = []
        self.next_id = 1
        self.reject = False

    def worker_check_thread(self):
        assert QThread.currentThread() == self.thread()

    def worker_submit(self, operation, parameters=None):
        if self.reject:
            raise RuntimeError("Worker request queue is full")
        request_id = self.next_id
        self.next_id += 1
        self.calls.append((request_id, operation, dict(parameters or {})))
        self.pending[request_id] = SimpleNamespace(operation=operation)
        self.request_submitted.emit(request_id, operation)
        return request_id

    def worker_cancel(self, request_id):
        assert request_id in self.pending
        self.cancellations.append(request_id)

    def finish(self, request_id, value):
        request = self.pending.pop(request_id)
        self.result_ready.emit(WorkerResult(request_id, request.operation, value))


@pytest.fixture
def manual(qapp, tmp_path):
    worker = ManualWorker(tmp_path / "archive")
    models = ArchiveModels(worker, page_size=3)
    yield worker, models
    models.deleteLater()
    worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def asset(identifier, *, files=None, name=None):
    identifiers = [identifier * 10] if files is None else files
    return AssetView(
        identifier,
        f"{identifier:064x}",
        name or f"image-{identifier}.jpg",
        "image",
        100,
        None,
        True,
        "active",
        [f"Photos/Trip/{file_id}.jpg" for file_id in identifiers],
        identifiers,
    )


def fetch_manual(worker, model, rows):
    model.fetchMore()
    request_id = model.pending_request
    assert request_id is not None
    worker.finish(request_id, rows)
    return request_id


def test_lazy_pages_and_cached_roles_do_no_extra_io(manual):
    worker, models = manual
    model = models.assets
    assert not worker.calls
    assert model.rowCount() == 0 and model.canFetchMore()
    model.fetchMore()
    first_id = model.pending_request
    model.fetchMore()
    assert worker.calls == [
        (first_id, "app_service_list_assets", {"album_id": None, "limit": 4, "offset": 0})
    ]
    worker.finish(first_id, [asset(identifier) for identifier in range(1, 5)])
    assert model.rowCount() == 3 and model.canFetchMore()
    assert model.data(model.index(0)) == "image-1.jpg"
    assert model.data(model.index(0), AssetRole.FILE_IDS) == (10,)
    assert model.data(model.index(0), AssetRole.PATHS) == ("Photos/Trip/10.jpg",)
    assert model.roleNames()[AssetRole.ASSET_ID] == b"asset_id"
    assert model.data(model.index(0), 99999) is None
    assert model.rowCount(model.index(0)) == 0
    assert not model.canFetchMore(model.index(0))
    assert not model.index(0, 1).isValid()
    assert not model.index(-1).isValid()
    assert model.data(QModelIndex()) is None
    assert len(worker.calls) == 1
    fetch_manual(worker, model, [asset(identifier) for identifier in range(4, 7)])
    assert worker.calls[-1][2] == {"album_id": None, "limit": 4, "offset": 3}
    assert model.rowCount() == 6 and not model.canFetchMore()


def test_album_roles_and_empty_page(manual):
    worker, models = manual
    fetch_manual(worker, models.albums, [AlbumSummary(2, "Trip", "Trip", 5)])
    index = models.albums.index(0)
    assert models.albums.data(index) == "Trip"
    assert models.albums.data(index, AlbumRole.ASSET_COUNT) == 5
    assert models.albums.data(index, AlbumRole.ALBUM_ID) == 2
    assert models.albums.roleNames()[AlbumRole.SAFE_NAME] == b"safe_name"
    assert worker.calls[-1][2] == {"limit": 4, "offset": 0}
    fetch_manual(worker, models.assets, [])
    assert models.assets.rowCount() == 0 and not models.assets.canFetchMore()


@pytest.mark.parametrize(
    "scope,operation,album_id",
    [
        (AssetScope(), "app_service_list_assets", None),
        (AssetScope("album", 2), "app_service_list_assets", 2),
        (AssetScope("unsorted"), "app_service_list_unsorted", None),
        (AssetScope("recycled"), "app_service_list_recycled", None),
    ],
)
def test_all_scopes_use_bounded_queries(manual, scope, operation, album_id):
    worker, models = manual
    models.assets.asset_model_set_scope(scope)
    models.assets.fetchMore()
    _, called, parameters = worker.calls[-1]
    assert called == operation
    assert parameters["limit"] == 4 and parameters["offset"] == 0
    assert parameters.get("album_id") == album_id


def test_scope_reset_ignores_old_success_failure_and_cancellation(manual):
    worker, models = manual
    model = models.assets
    model.fetchMore()
    old_id = model.pending_request
    model.asset_model_set_scope(AssetScope("album", 2))
    assert old_id in worker.cancellations
    model.fetchMore()
    new_id = model.pending_request
    worker.finish(old_id, [asset(1)])
    worker.failed.emit(WorkerFailure(old_id, "app_service_list_assets", "OSError", "old", ""))
    worker.cancelled.emit(WorkerResult(old_id, "app_service_list_assets", cancelled=True))
    assert model.rowCount() == 0 and model.loading and model.last_error is None
    worker.finish(new_id, [asset(2)])
    assert model.data(model.index(0), AssetRole.ASSET_ID) == 2


def test_synchronous_scope_change_during_submission_cannot_accept_old_page(manual):
    worker, models = manual
    model = models.assets

    def change_scope(request_id, operation):
        if operation == "app_service_list_assets":
            model.asset_model_set_scope(AssetScope("recycled"))

    worker.request_submitted.connect(change_scope)
    model.fetchMore()
    old_id = worker.calls[-1][0]
    assert old_id in worker.cancellations and not model.loading
    worker.finish(old_id, [asset(1)])
    assert model.rowCount() == 0
    worker.request_submitted.disconnect(change_scope)
    fetch_manual(worker, model, [asset(2)])
    assert worker.calls[-1][1] == "app_service_list_recycled"


def test_fetch_failure_stops_automatic_retries_and_retries_same_offset(manual):
    worker, models = manual
    model = models.assets
    fetch_manual(worker, model, [asset(identifier) for identifier in range(1, 5)])
    model.fetchMore()
    request_id = model.pending_request
    worker.pending.pop(request_id)
    worker.failed.emit(WorkerFailure(request_id, "app_service_list_assets", "OSError", "busy", ""))
    assert "busy" in model.last_error and not model.canFetchMore()
    assert model.rowCount() == 3 and not model.loading
    model.model_retry()
    assert worker.calls[-1][2]["offset"] == 3
    worker.finish(model.pending_request, [asset(4)])
    assert model.rowCount() == 4 and model.last_error is None


def test_queue_rejection_and_cancelled_page_are_visible(manual):
    worker, models = manual
    model = models.assets
    worker.reject = True
    model.fetchMore()
    assert "queue is full" in model.last_error and not model.loading
    worker.reject = False
    model.model_retry()
    request_id = model.pending_request
    worker.pending.pop(request_id)
    worker.cancelled.emit(WorkerResult(request_id, "app_service_list_assets", cancelled=True))
    assert model.last_error == "Page request cancelled" and not model.canFetchMore()


@pytest.mark.parametrize(
    "rows",
    [
        None,
        [AlbumSummary(1, "wrong", "wrong", 0)],
        [asset(1), asset(1)],
        [asset(index) for index in range(1, 6)],
        [replace(asset(1), file_ids=[])],
        [replace(asset(1), file_ids=[0])],
    ],
)
def test_invalid_pages_never_partially_insert_rows(manual, rows):
    worker, models = manual
    fetch_manual(worker, models.assets, rows)
    assert models.assets.last_error
    assert models.assets.rowCount() == 0 and not models.assets.canFetchMore()


def test_duplicate_across_pages_is_not_silently_appended(manual):
    worker, models = manual
    fetch_manual(worker, models.assets, [asset(index) for index in range(1, 5)])
    fetch_manual(worker, models.assets, [asset(3)])
    assert "Duplicate row" in models.assets.last_error
    assert models.assets.rowCount() == 3


def test_pages_are_detached_from_other_gui_signal_receivers(manual):
    worker, models = manual
    row = asset(1)
    fetch_manual(worker, models.assets, [row])
    row.file_ids.append(99)
    row.original_name = "mutated"
    assert models.assets.data(models.assets.index(0)) == "image-1.jpg"
    assert models.assets.data(models.assets.index(0), AssetRole.FILE_IDS) == (10,)


def test_qt_model_contract_and_persistent_selection_across_insertions(manual, qtlog):
    worker, models = manual
    tester = QAbstractItemModelTester(
        models.assets, QAbstractItemModelTester.FailureReportingMode.Warning
    )
    tester.setUseFetchMore(False)
    # The tester may ask for the initial page during construction.
    if not models.assets.loading:
        models.assets.fetchMore()
    worker.finish(models.assets.pending_request, [asset(index) for index in range(1, 5)])
    first = QPersistentModelIndex(models.assets.index(0))
    models.selection.select(models.assets.index(0), QItemSelectionModel.SelectionFlag.Select)
    fetch_manual(worker, models.assets, [asset(4)])
    assert first.isValid() and first.data(AssetRole.ASSET_ID) == 1
    assert models.assets.asset_model_selection(models.selection.selectedRows()).file_ids == (10,)
    assert not [record.message for record in qtlog.records if "FAIL!" in record.message]


def test_qt_tester_fetching_never_repeats_the_insertion_offset(manual, qtlog):
    """Qt may fetch during insertion notifications; those requests must be deferred."""
    worker, models = manual
    tester = QAbstractItemModelTester(
        models.assets, QAbstractItemModelTester.FailureReportingMode.Warning
    )
    assert tester.model() is models.assets
    if not models.assets.loading:
        models.assets.fetchMore()
    worker.finish(models.assets.pending_request, [asset(index) for index in range(1, 5)])
    assert [call[2]["offset"] for call in worker.calls] == [0]
    fetch_manual(worker, models.assets, [asset(4)])
    assert [call[2]["offset"] for call in worker.calls] == [0, 3]
    assert models.assets.rowCount() == 4 and models.assets.last_error is None
    assert not [record.message for record in qtlog.records if "FAIL!" in record.message]


@pytest.mark.parametrize("notification", ["rowsAboutToBeInserted", "rowsInserted"])
def test_scope_reset_during_insertion_cannot_relabel_old_copies(manual, notification):
    """Scope changes are applied after the insert closes, and discard the old page."""
    worker, models = manual
    model = models.assets
    requested = []

    def switch_scope(*arguments):
        """Request a single reentrant reset while a page is being published."""
        if not requested:
            requested.append(True)
            model.asset_model_set_scope(AssetScope("recycled"))
            model.fetchMore()

    getattr(model, notification).connect(switch_scope)
    fetch_manual(worker, model, [asset(1)])
    assert model.scope == AssetScope("recycled")
    assert model.rowCount() == 0 and not model.loading
    assert len(worker.calls) == 1
    fetch_manual(worker, model, [asset(2, files=[22])])
    assert worker.calls[-1][1:] == ("app_service_list_recycled", {"limit": 4, "offset": 0})
    assert model.asset_model_selection([model.index(0)]).file_ids == (22,)


def test_reset_notifications_cannot_fetch_or_use_selections(manual):
    """A reset must block paging and old snapshots before Qt emits its first notification."""
    worker, models = manual
    model = models.assets
    fetch_manual(worker, model, [asset(index) for index in range(1, 5)])
    snapshot = model.asset_model_selection([model.index(0)])

    def during_reset():
        """Try the operations a reentrant UI callback must not perform."""
        model.fetchMore()
        with pytest.raises(ValueError, match="stale"):
            model.asset_model_selection_parameters(snapshot)
        with pytest.raises(ValueError, match="active archive"):
            model.asset_model_selection([])

    model.modelAboutToBeReset.connect(during_reset)
    model.modelReset.connect(during_reset)
    model.model_reset()
    assert len(worker.calls) == 1
    fetch_manual(worker, model, [asset(1)])
    assert worker.calls[-1][2]["offset"] == 0


def test_selection_preserves_copy_ids_through_nested_proxy_models(manual):
    worker, models = manual
    model = models.assets
    model.asset_model_set_scope(AssetScope("album", 2))
    fetch_manual(worker, model, [asset(1, files=[11], name="B"), asset(2, files=[22], name="A")])
    proxy = QSortFilterProxyModel(models)
    proxy.setSourceModel(model)
    proxy.sort(0)
    outer = QSortFilterProxyModel(models)
    outer.setSourceModel(proxy)
    snapshot = model.asset_model_selection(
        [QPersistentModelIndex(outer.index(row, 0)) for row in (0, 1, 0)]
    )
    assert snapshot.asset_ids == (2, 1) and snapshot.file_ids == (22, 11)
    assert snapshot.scope == AssetScope("album", 2)
    assert model.asset_model_selection_parameters(snapshot) == {
        "asset_ids": [2, 1],
        "file_ids": [22, 11],
    }
    empty = model.asset_model_selection([])
    assert model.asset_model_selection_parameters(empty) == {"asset_ids": [], "file_ids": []}


def test_proxy_selection_rejects_nonpersistent_and_reset_indexes(manual):
    """Never pass stale ordinary proxy pointers into Qt's native mapToSource."""
    worker, models = manual
    model = models.assets
    fetch_manual(worker, model, [asset(1)])
    proxy = QSortFilterProxyModel(models)
    proxy.setSourceModel(model)
    ordinary = proxy.index(0, 0)
    persistent = QPersistentModelIndex(ordinary)
    with pytest.raises(ValueError, match="persistent"):
        model.asset_model_selection([ordinary])
    model.asset_model_set_scope(AssetScope("recycled"))
    fetch_manual(worker, model, [asset(2)])
    assert not persistent.isValid()
    with pytest.raises(ValueError, match="foreign"):
        model.asset_model_selection([persistent])
    with pytest.raises(ValueError, match="persistent"):
        model.asset_model_selection([ordinary])


def test_reset_rejects_stale_indexes_snapshots_and_clears_selection(manual):
    worker, models = manual
    model = models.assets
    fetch_manual(worker, model, [asset(1)])
    index = model.index(0)
    persistent = QPersistentModelIndex(index)
    snapshot = model.asset_model_selection([index])
    models.selection.select(index, QItemSelectionModel.SelectionFlag.Select)
    model.model_reset()
    fetch_manual(worker, model, [asset(2)])
    assert not persistent.isValid() and not models.selection.hasSelection()
    assert model.data(index) is None
    with pytest.raises(ValueError, match="stale"):
        model.asset_model_selection([index])
    with pytest.raises(ValueError, match="stale"):
        model.asset_model_selection_parameters(snapshot)


def test_invalid_foreign_and_unscoped_selections_are_rejected(manual):
    worker, models = manual
    fetch_manual(worker, models.assets, [asset(1, files=[])])
    assert not models.assets.flags(models.assets.index(0)) & Qt.ItemFlag.ItemIsSelectable
    with pytest.raises(ValueError, match="exact file-copy"):
        models.assets.asset_model_selection([models.assets.index(0)])
    fetch_manual(worker, models.albums, [AlbumSummary(2, "Trip", "Trip", 0)])
    for index in (QModelIndex(), models.albums.index(0)):
        with pytest.raises(ValueError, match="foreign"):
            models.assets.asset_model_selection([index])


def test_mutation_barriers_invalidate_before_execution_and_wait_for_all_replies(manual):
    worker, models = manual
    fetch_manual(worker, models.assets, [asset(1)])
    snapshot = models.assets.asset_model_selection([models.assets.index(0)])
    first = worker.worker_submit("app_service_move_to_deleted")
    second = worker.worker_submit("app_service_import")
    assert models.assets.rowCount() == 0 and not models.assets.canFetchMore()
    with pytest.raises(ValueError, match="stale"):
        models.assets.asset_model_selection_parameters(snapshot)
    worker.finish(first, None)
    assert not models.assets.canFetchMore()
    worker.finish(second, None)
    assert models.assets.canFetchMore() and not models.assets.loading


def test_archive_switch_clears_album_scope_and_old_ids(manual, tmp_path):
    worker, models = manual
    models.assets.asset_model_set_scope(AssetScope("album", 2))
    fetch_manual(worker, models.assets, [asset(1)])
    snapshot = models.assets.asset_model_selection([models.assets.index(0)])
    closed = worker.worker_submit("close_archive")
    worker.archive_root = None
    worker.finish(closed, None)
    assert not models.assets.canFetchMore()
    opened = worker.worker_submit("open_archive")
    worker.archive_root = tmp_path / "other-archive"
    worker.finish(opened, None)
    assert models.assets.scope == AssetScope()
    fetch_manual(worker, models.assets, [asset(1)])
    with pytest.raises(ValueError, match="stale"):
        models.assets.asset_model_selection_parameters(snapshot)
    worker.archive_root = None
    worker.state = "stopped"
    worker.stopped.emit()
    assert models.assets.rowCount() == 0 and not models.assets.canFetchMore()


@pytest.mark.parametrize("size", [0, -1, 513, True, 1.5])
def test_invalid_page_sizes_are_rejected(qapp, tmp_path, size):
    with pytest.raises(ValueError, match="page_size"):
        ArchiveModels(ManualWorker(tmp_path), page_size=size)


@pytest.mark.parametrize(
    "kind,identifier", [("unknown", None), ("album", None), ("album", 0), ("all", 2)]
)
def test_invalid_scope_combinations_are_rejected(kind, identifier):
    with pytest.raises(ValueError):
        AssetScope(kind, identifier)


@pytest.fixture
def real_models(qapp, qtbot, tmp_path):
    created = []

    def create(**kwargs):
        worker = WorkerController(**kwargs)
        models = ArchiveModels(worker)
        replies, failures = {}, {}
        worker.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
        worker.failed.connect(lambda error: failures.update({error.request_id: error}))
        created.append((worker, models))

        def wait(request_id):
            qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=5000)
            assert request_id not in failures, failures.get(request_id)
            return replies[request_id].value

        root = tmp_path / f"archive-{len(created)}"
        wait(worker.worker_open(root, create=True))
        return worker, models, wait, root

    yield create
    for worker, models in created:
        worker.worker_shutdown()
        assert worker.worker_wait(5000)
        qapp.processEvents()
        models.deleteLater()
        worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def fetch_real(model, qtbot):
    model.fetchMore()
    qtbot.waitUntil(lambda: not model.loading, timeout=5000)
    assert model.last_error is None


def test_1297_assets_are_loaded_in_bounded_pages_on_the_worker(real_models, qtbot):
    audit = Queue()

    class SeededService(AppService):
        def app_service_initialize(self):
            paths = super().app_service_initialize()
            self.connection.executemany(
                "INSERT INTO assets(id, sha256, size, original_name, media_type) "
                "VALUES (?, ?, 1, 'same.jpg', 'image')",
                [(identifier, f"{identifier:064x}") for identifier in range(1, 1298)],
            )
            self.connection.executemany(
                "INSERT INTO asset_files(asset_id, path) VALUES (?, ?)",
                [
                    (identifier, f"Photos/_Unsorted/{identifier}.jpg")
                    for identifier in range(1, 1298)
                ],
            )
            self.connection.commit()
            return paths

        def app_service_list_assets(
            self, album_id=None, include_deleted=False, limit=None, offset=0
        ):
            audit.put((limit, offset, get_ident()))
            return super().app_service_list_assets(album_id, include_deleted, limit, offset)

    _, models, _, _ = real_models(service_factory=SeededService)
    assert models.assets.rowCount() == 0 and audit.empty()
    fetch_real(models.assets, qtbot)
    assert models.assets.rowCount() == DEFAULT_PAGE_SIZE
    assert audit.qsize() == 1
    while models.assets.canFetchMore():
        fetch_real(models.assets, qtbot)
    assert models.assets.rowCount() == 1297
    assert [
        models.assets.data(models.assets.index(row), AssetRole.ASSET_ID) for row in range(1297)
    ] == list(range(1, 1298))
    requests = [audit.get_nowait() for _ in range(audit.qsize())]
    assert [item[1] for item in requests] == list(range(0, 1297, DEFAULT_PAGE_SIZE))
    assert all(item[0] == DEFAULT_PAGE_SIZE + 1 and item[2] != get_ident() for item in requests)


def test_real_album_and_recycle_selection_only_edits_the_visible_copy(real_models, qtbot):
    @contextmanager
    def source_factory(udid):
        yield FakeDevice(
            {"/DCIM/shared.jpg": b"shared", "/DCIM/unsorted.jpg": b"unsorted"},
            album_map={"/DCIM/shared.jpg": ["Trip", "Family"]},
        )

    worker, models, wait, root = real_models(source_factory=source_factory)
    wait(worker.worker_submit("app_service_import"))
    fetch_real(models.albums, qtbot)
    album_ids = {
        models.albums.data(models.albums.index(row)): models.albums.data(
            models.albums.index(row), AlbumRole.ALBUM_ID
        )
        for row in range(models.albums.rowCount())
    }
    models.assets.asset_model_set_scope(AssetScope("album", album_ids["Trip"]))
    fetch_real(models.assets, qtbot)
    snapshot = models.assets.asset_model_selection([models.assets.index(0)])
    assert len(snapshot.file_ids) == 1
    family_file = next((root / "Photos" / "Family").iterdir())
    family_bytes = family_file.read_bytes()
    parameters = models.assets.asset_model_selection_parameters(snapshot)
    wait(worker.worker_submit("app_service_move_to_deleted", parameters))
    assert family_file.read_bytes() == family_bytes
    fetch_real(models.albums, qtbot)
    counts = {
        models.albums.data(models.albums.index(row)): models.albums.data(
            models.albums.index(row), AlbumRole.ASSET_COUNT
        )
        for row in range(models.albums.rowCount())
    }
    assert counts == {"Family": 1, "Trip": 0}
    models.assets.asset_model_set_scope(AssetScope("recycled"))
    fetch_real(models.assets, qtbot)
    recycled = models.assets.asset_model_selection([models.assets.index(0)])
    assert recycled.file_ids == snapshot.file_ids
    assert all(
        path.startswith("Deleted/Trip/")
        for path in models.assets.data(models.assets.index(0), AssetRole.PATHS)
    )
    wait(
        worker.worker_submit(
            "app_service_restore", models.assets.asset_model_selection_parameters(recycled)
        )
    )
    assert family_file.read_bytes() == family_bytes
    assert len(list((root / "Photos" / "Trip").iterdir())) == 1
    models.assets.asset_model_set_scope(AssetScope("unsorted"))
    fetch_real(models.assets, qtbot)
    assert models.assets.rowCount() == 1
    assert models.assets.data(models.assets.index(0)) == "unsorted.jpg"
