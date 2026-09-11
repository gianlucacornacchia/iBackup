"""Offscreen ownership, request transport, cancellation and worker lifetime regressions."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Event, get_ident

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from iphone_archive.core.verifier import VerifyResult  # noqa: E402
from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui import application, main_window  # noqa: E402
from iphone_archive.gui.main_window import MainWindow  # noqa: E402
from iphone_archive.gui.worker import (  # noqa: E402
    MAX_PENDING_REQUESTS,
    WorkerController,
    worker_copy_data,
)
from iphone_archive.service.app_service import AppService  # noqa: E402
from iphone_archive.service.archive_lock import ArchiveBusyError  # noqa: E402
from iphone_archive.settings import Settings, settings_load  # noqa: E402


@pytest.fixture
def workers(qapp):
    """Provide controllers and join every thread before QObject teardown, even on failure."""
    created = []

    def create(**kwargs):
        controller = WorkerController(**kwargs)
        replies = {}
        failures = {}
        progress = []
        receiver_threads = []

        def completed(reply):
            receiver_threads.append(get_ident())
            replies[reply.request_id] = reply

        def failed(failure):
            receiver_threads.append(get_ident())
            failures[failure.request_id] = failure

        controller.result_ready.connect(completed)
        controller.cancelled.connect(completed)
        controller.failed.connect(failed)
        controller.progress_changed.connect(
            lambda request_id, event: progress.append((request_id, event, get_ident()))
        )
        created.append(controller)
        return controller, replies, failures, progress, receiver_threads

    yield create
    for controller in created:
        controller.worker_shutdown()
        assert controller.worker_wait(6000), "Test left archive work blocked"
    qapp.processEvents()
    for controller in created:
        controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_reply(qtbot, request_id, replies, failures):
    """Wait through Qt delivery and fail with worker details instead of an opaque timeout."""
    qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=5000)
    assert request_id not in failures, failures.get(request_id)
    return replies[request_id]


def initialize(qtbot, worker, replies, failures, path):
    """Create an archive through the worker and wait for its exclusive session."""
    return wait_reply(qtbot, worker.worker_open(path, create=True), replies, failures)


def test_service_lifetime_and_queued_receivers_use_the_correct_threads(workers, qtbot, tmp_path):
    audit = Queue()

    class TrackedService(AppService):
        def __init__(self, root):
            audit.put(("construct", get_ident()))
            super().__init__(root)

        def app_service_initialize(self):
            audit.put(("initialize", get_ident()))
            return super().app_service_initialize()

        def app_service_stats(self):
            audit.put(("stats", get_ident()))
            return super().app_service_stats()

        def app_service_close(self):
            audit.put(("close", get_ident()))
            super().app_service_close()

    worker, replies, failures, _, receivers = workers(service_factory=TrackedService)
    assert not worker.service_thread.isRunning()
    root = tmp_path / "archive"
    initialize(qtbot, worker, replies, failures, root)
    request_id = worker.worker_submit("app_service_stats")
    assert wait_reply(qtbot, request_id, replies, failures).value["assets"] == 0
    contender = AppService(root)
    with pytest.raises(ArchiveBusyError):
        contender.app_service_open()
    worker.worker_shutdown()
    assert worker.worker_wait(5000)
    qtbot.waitUntil(lambda: worker.state == "stopped")
    records = [audit.get_nowait() for _ in range(audit.qsize())]
    assert [item[0] for item in records] == ["construct", "initialize", "stats", "close"]
    assert len({item[1] for item in records}) == 1
    assert records[0][1] != get_ident()
    assert set(receivers) == {get_ident()}
    contender.app_service_open()
    contender.app_service_close()


def test_open_failure_is_reported_and_worker_accepts_a_new_archive(workers, qtbot, tmp_path):
    worker, replies, failures, _, receivers = workers()
    request_id = worker.worker_open(tmp_path / "missing")
    qtbot.waitUntil(lambda: request_id in failures)
    assert failures[request_id].error_type == "ArchiveNotFoundError"
    assert failures[request_id].traceback_text
    assert not (tmp_path / "missing").exists()
    initialize(qtbot, worker, replies, failures, tmp_path / "valid")
    assert set(receivers) == {get_ident()}


def test_failed_initialization_releases_its_partially_opened_session(workers, qtbot, tmp_path):
    class FailAfterOpen(AppService):
        def app_service_initialize(self):
            super().app_service_initialize()
            raise RuntimeError("initialization failed after acquiring lock")

    worker, _, failures, _, _ = workers(service_factory=FailAfterOpen)
    root = tmp_path / "archive"
    request_id = worker.worker_open(root, create=True)
    qtbot.waitUntil(lambda: request_id in failures)
    assert "initialization failed" in failures[request_id].message
    contender = AppService(root)
    contender.app_service_open()
    contender.app_service_close()


def test_close_then_open_serializes_archive_switches(workers, qtbot, tmp_path):
    worker, replies, failures, _, _ = workers()
    initialize(qtbot, worker, replies, failures, tmp_path / "first")
    refused = worker.worker_open(tmp_path / "second", create=True)
    qtbot.waitUntil(lambda: refused in failures)
    assert "Close the current archive" in failures[refused].message
    assert not (tmp_path / "second").exists()
    close_id = worker.worker_submit("close_archive")
    open_id = worker.worker_open(tmp_path / "second", create=True)
    stats_id = worker.worker_submit("app_service_stats")
    wait_reply(qtbot, stats_id, replies, failures)
    assert list(replies)[-3:] == [close_id, open_id, stats_id]


def test_real_import_verify_and_source_lifetime_stay_on_worker(workers, qtbot, tmp_path):
    device_threads = Queue()

    @contextmanager
    def source_factory(udid):
        device_threads.put(("open", get_ident(), udid))
        try:
            yield FakeDevice({"/DCIM/photo.jpg": b"archive payload"})
        finally:
            device_threads.put(("close", get_ident(), udid))

    worker, replies, failures, progress, _ = workers(source_factory=source_factory)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    import_id = worker.worker_submit("app_service_import", device_udid="selected-phone")
    result = wait_reply(qtbot, import_id, replies, failures)
    assert result.value.added_count == 1
    verify_id = worker.worker_submit("app_service_verify")
    verified = wait_reply(qtbot, verify_id, replies, failures).value
    assert verified.ok_count == 1
    assert all(item[2] == get_ident() for item in progress)
    assert {item[0] for item in progress} == {import_id, verify_id}
    opened, closed = device_threads.get_nowait(), device_threads.get_nowait()
    assert opened[1] == closed[1] != get_ident()
    assert opened[2] == closed[2] == "selected-phone"


def test_cancel_reaches_running_operation_without_worker_event_loop(workers, qtbot, tmp_path):
    entered = Event()

    class CancellableService(AppService):
        def app_service_verify(self, progress=None, limit=None):
            entered.set()
            progress.progress_report("verify", 1, 10)
            if not progress.cancel_event.wait(5):
                raise RuntimeError("Cancellation never reached worker")
            return VerifyResult(checked_count=1, cancelled=True)

    worker, replies, failures, _, _ = workers(service_factory=CancellableService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    request_id = worker.worker_submit("app_service_verify")
    assert entered.wait(5)
    worker.worker_cancel(request_id)
    result = wait_reply(qtbot, request_id, replies, failures)
    assert result.cancelled
    assert result.value.checked_count == 1
    stats_id = worker.worker_submit("app_service_stats")
    wait_reply(qtbot, stats_id, replies, failures)


def test_cancel_does_not_relabel_a_completed_non_cancellable_operation(workers, qtbot, tmp_path):
    entered, release = Event(), Event()

    class SlowService(AppService):
        def app_service_stats(self):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release operation")
            return super().app_service_stats()

    worker, replies, failures, _, _ = workers(service_factory=SlowService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    request_id = worker.worker_submit("app_service_stats")
    try:
        assert entered.wait(5)
        worker.worker_cancel(request_id)
    finally:
        release.set()
    assert not wait_reply(qtbot, request_id, replies, failures).cancelled


def test_bounded_queue_can_always_shutdown_and_skips_cancelled_pending_work(
    workers, qtbot, tmp_path
):
    entered, release = Event(), Event()
    executions = Queue()

    class SlowService(AppService):
        def app_service_stats(self):
            executions.put(get_ident())
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release operation")
            return super().app_service_stats()

    worker, replies, failures, _, _ = workers(service_factory=SlowService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    active = worker.worker_submit("app_service_stats")
    try:
        assert entered.wait(5)
        queued = [
            worker.worker_submit("app_service_stats") for _ in range(MAX_PENDING_REQUESTS - 1)
        ]
        with pytest.raises(RuntimeError, match="queue is full"):
            worker.worker_submit("app_service_stats")
        worker.worker_shutdown()
        assert not worker.worker_wait(1)
        with pytest.raises(RuntimeError, match="shutting down"):
            worker.worker_submit("app_service_stats")
    finally:
        release.set()
    assert worker.worker_wait(5000)
    qtbot.waitUntil(lambda: worker.state == "stopped")
    assert not failures
    assert not replies[active].cancelled
    assert all(replies[request_id].cancelled for request_id in queued)
    assert executions.qsize() == 1
    assert worker.requests.unfinished_tasks == 0


def test_request_parameters_are_snapshotted_before_enqueueing(workers, qtbot, tmp_path):
    entered, release = Event(), Event()

    class SlowService(AppService):
        def app_service_stats(self):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release operation")
            return super().app_service_stats()

    worker, replies, failures, _, _ = workers(service_factory=SlowService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    worker.worker_submit("app_service_stats")
    try:
        assert entered.wait(5)
        settings = Settings(theme="dark", recent_archives=["original"])
        request_id = worker.worker_submit("app_service_update_settings", {"settings": settings})
        settings.theme = "light"
        settings.recent_archives.append("late mutation")
    finally:
        release.set()
    saved = wait_reply(qtbot, request_id, replies, failures).value
    assert saved.theme == "dark"
    assert saved.recent_archives == ["original"]
    assert settings_load().theme == "dark"


def test_live_resources_and_internal_service_methods_cannot_cross_boundary(workers, qapp):
    worker, _, _, _, _ = workers()
    with pytest.raises(ValueError, match="Unsupported"):
        worker.worker_submit("app_service_require")
    with pytest.raises(ValueError, match="owns source"):
        worker.worker_submit("app_service_import", {"source": FakeDevice()})
    with pytest.raises(TypeError, match="Cannot transfer"):
        worker.worker_submit("app_service_stats", {"widget": qapp})
    with pytest.raises(TypeError, match="device_udid"):
        worker.worker_submit("app_service_import", device_udid=qapp)
    assert not worker.pending
    assert not worker.service_thread.isRunning()


def test_live_result_is_reported_as_error_without_leaking_connection(workers, qtbot, tmp_path):
    class BadResultService(AppService):
        def app_service_stats(self):
            return self.connection

    worker, replies, failures, _, _ = workers(service_factory=BadResultService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    request_id = worker.worker_submit("app_service_stats")
    qtbot.waitUntil(lambda: request_id in failures)
    assert failures[request_id].error_type == "TypeError"
    assert "Connection" in failures[request_id].message
    assert request_id not in replies
    verify_id = worker.worker_submit("app_service_verify")
    wait_reply(qtbot, verify_id, replies, failures)


def test_progress_notifications_are_coalesced_and_terminal_update_is_delivered(
    workers, qtbot, tmp_path
):
    emitted, release = Event(), Event()

    class ChattyService(AppService):
        def app_service_verify(self, progress=None, limit=None):
            for index in range(10000):
                progress.progress_report("verify", index + 1, 10000)
            emitted.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release operation")
            return VerifyResult(checked_count=10000)

    worker, replies, failures, progress, _ = workers(service_factory=ChattyService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    request_id = worker.worker_submit("app_service_verify")
    try:
        assert emitted.wait(5)
        assert len(worker.pending[request_id].progress.handle.events) == 256
        assert not progress
        qtbot.waitUntil(lambda: len(progress) == 1)
        assert progress[0][1].current == 10000
    finally:
        release.set()
    wait_reply(qtbot, request_id, replies, failures)
    assert len(progress) == 1


def test_worker_error_does_not_discard_later_requests(workers, qtbot, tmp_path):
    worker, replies, failures, _, _ = workers()
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    bad = worker.worker_submit("app_service_list_assets", {"unknown_argument": True})
    good = worker.worker_submit("app_service_stats")
    wait_reply(qtbot, good, replies, failures)
    assert failures[bad].error_type == "TypeError"


def test_source_is_closed_after_operation_error_and_invalid_arguments_do_not_connect(
    workers, qtbot, tmp_path
):
    resources = Queue()

    @contextmanager
    def source_factory(udid):
        resources.put("open")
        try:
            yield FakeDevice()
        finally:
            resources.put("close")

    class FailedImport(AppService):
        def app_service_import(self, source, progress=None, link_mode=None):
            raise OSError("device read failed")

    worker, _, failures, _, _ = workers(service_factory=FailedImport, source_factory=source_factory)
    # Device calls must still have an explicit archive session in this foundation step.
    missing = worker.worker_submit("app_service_import")
    qtbot.waitUntil(lambda: missing in failures)
    assert resources.empty()
    opened = worker.worker_open(tmp_path / "archive", create=True)
    qtbot.waitUntil(lambda: opened not in worker.pending)
    invalid = worker.worker_submit("app_service_import", {"unknown_argument": 1})
    qtbot.waitUntil(lambda: invalid in failures)
    assert resources.empty()
    failed = worker.worker_submit("app_service_import")
    qtbot.waitUntil(lambda: failed in failures)
    assert "device read failed" in failures[failed].message
    assert [resources.get_nowait(), resources.get_nowait()] == ["open", "close"]


def test_shutdown_close_failure_is_signalled_and_lock_is_released(workers, qtbot, tmp_path):
    class FailedClose(AppService):
        def app_service_close(self):
            super().app_service_close()
            raise OSError("close failure")

    worker, replies, failures, _, _ = workers(service_factory=FailedClose)
    root = tmp_path / "archive"
    initialize(qtbot, worker, replies, failures, root)
    worker.worker_shutdown()
    assert worker.worker_wait(5000)
    qtbot.waitUntil(lambda: worker.state == "stopped")
    assert failures[0].operation == "shutdown"
    assert "close failure" in failures[0].message
    contender = AppService(root)
    contender.app_service_open()
    contender.app_service_close()


def test_unexpected_failure_closes_session_and_never_replays_pending_mutations(
    workers, qtbot, tmp_path
):
    entered, release = Event(), Event()

    class UnexpectedFailure(Exception):
        pass

    class FailedService(AppService):
        def app_service_stats(self):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release failure")
            raise UnexpectedFailure("unanticipated operation failure")

    worker, replies, failures, _, _ = workers(service_factory=FailedService)
    root = tmp_path / "archive"
    initialize(qtbot, worker, replies, failures, root)
    with qtbot.captureExceptions() as exceptions:
        active = worker.worker_submit("app_service_stats")
        try:
            assert entered.wait(5)
            abandoned = worker.worker_submit(
                "app_service_set_setting", {"key": "theme", "value": "dark"}
            )
        finally:
            release.set()
        qtbot.waitUntil(lambda: worker.state == "idle", timeout=5000)
    assert len(exceptions) == 1
    assert failures[active].error_type == "UnexpectedFailure"
    assert "no automatic retry" in failures[abandoned].message
    assert worker.requests.unfinished_tasks == 0
    assert settings_load().theme == "system"
    reopened = worker.worker_open(root)
    wait_reply(qtbot, reopened, replies, failures)
    verified = worker.worker_submit("app_service_verify")
    wait_reply(qtbot, verified, replies, failures)


def test_cancel_pending_request_skips_dispatch_without_stopping_worker(workers, qtbot, tmp_path):
    entered, release = Event(), Event()

    class SlowService(AppService):
        def app_service_stats(self):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release operation")
            return super().app_service_stats()

    worker, replies, failures, _, _ = workers(service_factory=SlowService)
    initialize(qtbot, worker, replies, failures, tmp_path / "archive")
    worker.worker_submit("app_service_stats")
    try:
        assert entered.wait(5)
        skipped = worker.worker_submit("app_service_set_setting", {"key": "theme", "value": "dark"})
        worker.worker_cancel(skipped)
    finally:
        release.set()
    assert wait_reply(qtbot, skipped, replies, failures).cancelled
    assert settings_load().theme == "system"
    assert worker.state == "running"


def test_window_close_waits_for_cooperative_stop_and_releases_archive(qtbot, tmp_path):
    entered = Event()

    class SlowService(AppService):
        def app_service_verify(self, progress=None, limit=None):
            entered.set()
            if not progress.cancel_event.wait(5):
                raise RuntimeError("Window close did not cancel work")
            return VerifyResult(cancelled=True)

    window = MainWindow()
    window.worker.service_thread.service_factory = SlowService
    qtbot.addWidget(window)
    window.show()
    root = tmp_path / "archive"
    with qtbot.waitSignal(window.worker.result_ready, timeout=5000):
        window.worker.worker_open(root, create=True)
    window.worker.worker_submit("app_service_verify")
    try:
        assert entered.wait(5)
        window.close()
        assert window.close_pending
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)
    assert not window.worker.service_thread.isRunning()
    contender = AppService(root)
    contender.app_service_open()
    contender.app_service_close()


def test_shutdown_is_idempotent_without_starting_thread(workers):
    worker, _, _, _, _ = workers()
    worker.worker_shutdown()
    worker.worker_shutdown()
    assert worker.worker_wait(0)
    assert not worker.service_thread.isRunning()
    with pytest.raises(RuntimeError, match="shutting down"):
        worker.worker_open(Path("unused"))


def test_window_surfaces_worker_failure(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    try:
        with qtbot.waitSignal(window.worker.failed, timeout=5000):
            window.worker.worker_open(tmp_path / "missing")
        assert "not an ibackup archive" in window.statusBar().currentMessage()
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)
        qtbot.waitUntil(lambda: window.worker.state == "stopped")


def test_application_exit_joins_active_worker_without_window_close(
    qapp, qtbot, monkeypatch, tmp_path
):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QPalette

    entered = Event()
    palette, font = QPalette(qapp.palette()), QFont(qapp.font())
    window = MainWindow()

    class SlowService(AppService):
        def app_service_verify(self, progress=None, limit=None):
            entered.set()
            if not progress.cancel_event.wait(5):
                raise RuntimeError("Application exit did not cancel work")
            return VerifyResult(cancelled=True)

    window.worker.service_thread.service_factory = SlowService
    root = tmp_path / "archive"

    def event_loop():
        with qtbot.waitSignal(window.worker.result_ready, timeout=5000):
            window.worker.worker_open(root, create=True)
        window.worker.worker_submit("app_service_verify")
        assert entered.wait(5)
        return 0

    monkeypatch.setattr(application, "application_create", lambda: qapp)
    monkeypatch.setattr(main_window, "MainWindow", lambda: window)
    monkeypatch.setattr(qapp, "exec", event_loop)
    try:
        assert application.application_main([]) == 0
        assert not window.worker.service_thread.isRunning()
        contender = AppService(root)
        contender.app_service_open()
        contender.app_service_close()
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        setter = getattr(qapp.styleHints(), "setColorScheme", None)
        if setter is not None:
            setter(Qt.ColorScheme.Unknown)
        qapp.setPalette(palette)
        qapp.setFont(font)


def test_invalid_cancel_and_wait_calls_are_explicit(workers):
    worker, _, _, _, _ = workers()
    with pytest.raises(ValueError, match="No pending"):
        worker.worker_cancel(99)
    with pytest.raises(RuntimeError, match="shutdown before waiting"):
        worker.worker_wait(1)
    worker.worker_shutdown()
    with pytest.raises(ValueError, match="must not be negative"):
        worker.worker_wait(-1)


def test_controller_rejects_calls_from_non_owner_thread(workers):
    from concurrent.futures import ThreadPoolExecutor

    worker, _, _, _, _ = workers()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(RuntimeError, match="owning GUI thread"):
            executor.submit(worker.worker_submit, "app_service_stats").result(timeout=5)
    assert not worker.pending


def test_copy_data_preserves_scope_without_aliases():
    value = {"asset_ids": [1, 2], "file_ids": [3], "settings": Settings(theme="dark")}
    copied = worker_copy_data(value)
    value["file_ids"].append(4)
    assert copied["file_ids"] == [3]
    assert copied["settings"] is not value["settings"]
