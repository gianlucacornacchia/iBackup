"""Offscreen safe operations: the progress dialog, summaries and command routing.

These tests drive a real ``MainWindow`` against a fake phone and a temporary
archive, so an "import" here copies real bytes into a real catalog. Nothing
destructive is exercised: that is step 9's scope and the window still refuses
those verbs.
"""

from __future__ import annotations

import inspect
import io
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from iphone_archive.core.dedup import DedupResult, DuplicateGroup  # noqa: E402
from iphone_archive.core.importer import ImportResult  # noqa: E402
from iphone_archive.core.verifier import VerifyIssue, VerifyResult  # noqa: E402
from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui import main_window as main_window_module  # noqa: E402
from iphone_archive.gui.dialogs import (  # noqa: E402
    MAX_REPORT_GROUPS,
    MoveToAlbumDialog,
    ReportDialog,
    dialogs_dedup_lines,
)
from iphone_archive.gui.main_window import OPERATION_BUSY, MainWindow  # noqa: E402
from iphone_archive.gui.models import AssetRole, AssetScope  # noqa: E402
from iphone_archive.gui.operations import (  # noqa: E402
    CANCELLABLE_OPERATIONS,
    MAX_ERROR_LINES,
    OperationDialog,
    operations_detail_lines,
    operations_format_duration,
    operations_is_problem,
    operations_remaining,
    operations_shorten,
    operations_summary,
    operations_title,
)
from iphone_archive.gui.worker import (  # noqa: E402
    SERVICE_OPERATIONS,
    WorkerController,
    WorkerFailure,
    WorkerResult,
)
from iphone_archive.service.app_service import AppService, DeviceInfo  # noqa: E402
from iphone_archive.service.selection import SelectionResult  # noqa: E402


def helper_photo_bytes(number, size=(120, 90)):
    """Encode a small real PNG whose content is unique to this asset.

    number: the asset's index, mixed into the pixels.
    size: the image dimensions.
    Returns the encoded PNG bytes. Identical bytes would be deduplicated into a
    single archived asset, which is what the archive is designed to do.
    """
    image = Image.new("RGB", size, (number * 37 % 256, number * 11 % 256, 90))
    image.putpixel((0, 0), (number % 256, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def window(qapp, qtbot, tmp_path, monkeypatch):
    """Build a real window wired to a fake phone, and shut it down afterwards."""
    created = []

    def create(count=4, open_archive=True):
        files = {
            f"/DCIM/IMG_{number:04d}.png": helper_photo_bytes(number) for number in range(count)
        }
        albums = {path: ["Trip"] for index, path in enumerate(files) if index % 2 == 0}

        @contextmanager
        def source_factory(udid):
            yield FakeDevice(files, album_map=albums)

        original = main_window_module.WorkerController
        monkeypatch.setattr(
            main_window_module,
            "WorkerController",
            lambda parent=None: original(parent, source_factory=source_factory),
        )
        main = MainWindow()
        qtbot.addWidget(main)
        main.resize(1000, 700)
        main.show()
        replies, failures = {}, {}
        main.worker.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
        main.worker.cancelled.connect(lambda reply: replies.update({reply.request_id: reply}))
        main.worker.failed.connect(lambda error: failures.update({error.request_id: error}))
        created.append(main)

        def wait(request_id):
            qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=15000)
            assert request_id not in failures, failures.get(request_id)
            return replies[request_id]

        root = tmp_path / f"archive-{len(created)}"
        if open_archive:
            monkeypatch.setattr(main, "main_window_choose_directory", lambda title: str(root))
            main.main_window_command("create")
            qtbot.waitUntil(lambda: main.worker.archive_root == root, timeout=15000)
        return main, wait, root

    yield create
    for main in created:
        main.worker.worker_shutdown()
        assert main.worker.worker_wait(5000)
        main.previews.previews_shutdown()
        main.viewer_previews.previews_shutdown()
        qapp.processEvents()
        main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def helper_import(main, wait, qtbot):
    """Run a full import through the progress dialog and return its summary text.

    main: the window under test.
    wait: the fixture's request waiter.
    qtbot: the pytest-qt bot.
    Returns the status text the dialog reported.
    """
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)
    return dialog.detail_label.text()


def test_durations_are_short_and_readable():
    """The dialog shows mm:ss until an operation passes an hour."""
    assert operations_format_duration(0) == "00:00"
    assert operations_format_duration(372) == "06:12"
    assert operations_format_duration(3661) == "1:01:01"
    assert operations_format_duration(-5) == "00:00"


def test_remaining_time_is_only_estimated_when_it_is_meaningful():
    """A guess made from no progress at all would be worse than saying nothing."""
    assert operations_remaining(10.0, 0.0) == ""
    assert operations_remaining(10.0, 1.0) == ""
    assert operations_remaining(0.0, 0.5) == ""
    assert operations_remaining(60.0, 0.5) == "Remaining ~01:00"


def test_progress_details_are_shortened_in_the_middle():
    """A long album path must not widen the dialog as the operation walks it."""
    long_path = "Photos/Summer trip 2019/IMG_a_very_long_original_name_indeed.HEIC"
    shortened = operations_shorten(long_path, 30)

    assert len(shortened) == 30
    assert shortened.startswith("Photos/Sum")
    assert shortened.endswith(".HEIC")
    assert operations_shorten("IMG_0001.png", 30) == "IMG_0001.png"


def test_cancellation_is_only_offered_where_the_backend_implements_it():
    """A Cancel button that cannot stop anything is worse than no button at all.

    Only an operation handed a ProgressHandle ever observes the cancel event,
    so the set must match the real signatures exactly in both directions.
    """
    expected = {
        name
        for name in SERVICE_OPERATIONS
        if "progress" in inspect.signature(getattr(AppService, name)).parameters
    }

    assert set(CANCELLABLE_OPERATIONS) == expected
    assert "app_service_import" in CANCELLABLE_OPERATIONS
    assert "app_service_verify" in CANCELLABLE_OPERATIONS
    assert "app_service_stats" not in CANCELLABLE_OPERATIONS


def test_a_non_cancellable_operation_hides_its_cancel_button(qtbot):
    """A scan cannot be interrupted, so it must not appear to be interruptible."""
    worker = WorkerController()
    try:
        scan = OperationDialog(worker, 1, "app_service_scan_phone", None)
        importing = OperationDialog(worker, 2, "app_service_import", None)
        qtbot.addWidget(scan)
        qtbot.addWidget(importing)
        scan.show()
        importing.show()

        assert scan.cancel_button.isVisibleTo(scan) is False
        assert "cannot be interrupted" in scan.count_label.text()
        assert importing.cancel_button.isVisibleTo(importing) is True
    finally:
        worker.worker_shutdown()
        worker.worker_wait(5000)


def test_every_result_type_is_summarised_in_one_line():
    """The user reads the summary, not the DTO."""
    summary = operations_summary(
        "app_service_import", ImportResult(added_count=12, skipped_count=3, duplicate_count=1)
    )
    assert "Added 12" in summary and "duplicates 1" in summary
    assert "ok" in operations_summary(
        "app_service_verify", VerifyResult(checked_count=5, ok_count=5)
    )
    assert "Moved 4" in operations_summary(
        "app_service_move_selection", SelectionResult(affected_count=4)
    )
    assert "40 albums" in operations_summary("app_service_stats", {"assets": 9, "albums": 40})
    assert "7 items" in operations_summary("app_service_device_info", DeviceInfo("udid-1", 7))
    assert "5 cached previews" in operations_summary("app_service_clear_thumbnails", 5)
    assert "Phone scan complete" in operations_summary("app_service_scan_phone", None)


def test_a_cancelled_import_is_reported_as_a_partial_success():
    """Everything copied before a cancel is already committed and must be said so."""
    summary = operations_summary("app_service_import", ImportResult(added_count=40, cancelled=True))

    assert "stopped early" in summary
    assert "Added 40" in summary
    assert "archived" in summary


def test_an_unexpected_result_type_still_produces_a_summary():
    """This text is shown while the user waits, so it must never raise."""
    assert "finished" in operations_summary("app_service_import", object())
    assert "finished" in operations_summary("app_service_not_a_real_operation", None)


def test_only_outcomes_needing_attention_count_as_problems():
    """A cancelled run is what the user asked for; a failed file is not."""
    assert operations_is_problem("app_service_import", ImportResult(error_count=2))
    assert not operations_is_problem("app_service_import", ImportResult(cancelled=True))
    assert operations_is_problem("app_service_verify", VerifyResult(mismatch_count=1))
    assert not operations_is_problem(
        "app_service_verify", VerifyResult(checked_count=3, ok_count=3)
    )
    assert operations_is_problem("app_service_move_selection", SelectionResult(errors=["nope"]))


def test_error_details_are_listed_not_just_counted():
    """A count alone gives the user nothing to act on."""
    assert operations_detail_lines("app_service_import", ImportResult(errors=["a", "b"])) == [
        "a",
        "b",
    ]
    issues = [VerifyIssue(path="Photos/a.png", status="mismatch", expected_sha256="x")]
    assert operations_detail_lines("app_service_verify", VerifyResult(issues=issues)) == [
        "Photos/a.png: mismatch"
    ]
    assert operations_detail_lines("app_service_stats", {"assets": 1}) == []


def test_the_duplicate_report_leads_with_the_biggest_waste():
    """The report exists to explain storage, so the costliest groups come first."""
    groups = [
        DuplicateGroup("a" * 64, "small.png", 2, 100, ["Photos/A/small.png"]),
        DuplicateGroup("b" * 64, "large.png", 3, 10_000, ["Photos/B/large.png"]),
    ]
    lines = dialogs_dedup_lines(DedupResult(asset_count=2, file_count=5, multi_copy_groups=groups))
    body = "\n".join(lines)

    assert body.index("large.png") < body.index("small.png")
    assert "Nothing is deleted by this report." in body
    assert "Photos/B/large.png" in body


def test_the_duplicate_report_is_bounded():
    """A report that printed every group would be an export, not a summary."""
    groups = [DuplicateGroup(f"{index:064d}", f"f{index}.png", 2, 1000, []) for index in range(120)]
    lines = dialogs_dedup_lines(DedupResult(multi_copy_groups=groups))

    assert f"...and {120 - MAX_REPORT_GROUPS} more groups." in lines


def test_an_unreadable_duplicate_result_says_so(qtbot):
    """A surprise payload must produce a report, not an exception behind a modal dialog."""
    assert dialogs_dedup_lines(None) == ["The duplicate report could not be read."]
    dialog = ReportDialog("Report", ["line one"], None)
    qtbot.addWidget(dialog)

    assert "line one" in dialog.body.toPlainText()


def test_the_move_dialog_refuses_an_empty_album_name(qtbot):
    """An empty name would reach the service as an invalid album after the dialog closed."""
    dialog = MoveToAlbumDialog(3, ["Trip"], False, None)
    qtbot.addWidget(dialog)
    requested = []
    dialog.move_requested.connect(requested.append)

    dialog.move_confirm()
    assert requested == []
    assert dialog.isVisible() is False or dialog.result() == 0

    dialog.album_box.setCurrentText("  Holiday  ")
    dialog.move_confirm()
    assert requested == ["Holiday"]


def test_the_move_dialog_states_whether_the_move_is_album_scoped(qtbot):
    """An album view must never silently move every copy of an asset."""
    scoped = MoveToAlbumDialog(2, [], True, None)
    unscoped = MoveToAlbumDialog(2, [], False, None)
    qtbot.addWidget(scoped)
    qtbot.addWidget(unscoped)

    assert "Only the copies stored in the album" in scoped.caption.text()
    assert "Every active copy" in unscoped.caption.text()
    assert "Moving 2 photos and videos" in scoped.caption.text()
    assert "Moving 1 photo or video" in MoveToAlbumDialog(1, [], False, None).caption.text()


def test_a_command_that_needs_a_later_step_says_so(window):
    """Silently doing nothing, or silently deleting, are both unacceptable."""
    main, wait, root = window(count=1)

    main.main_window_command("settings")
    assert "step 10" in main.statusBar().currentMessage()

    # The destructive verbs now exist, but they still refuse an empty selection
    # rather than acting on nothing or on everything.
    main.main_window_selection_action("purge", None)
    assert "Select at least one" in main.statusBar().currentMessage()

    main.main_window_selection_action("delete", None)
    assert "Select at least one" in main.statusBar().currentMessage()


def test_opening_an_archive_uses_the_folder_the_user_chose(window, qtbot):
    """Nothing is opened automatically, so this is the only way a session starts."""
    main, wait, root = window(count=1)

    assert main.worker.archive_root == root
    assert (root / ".ibackup").exists()
    qtbot.waitUntil(lambda: str(root) in main.statusBar().currentMessage(), timeout=15000)


def test_cancelling_the_folder_prompt_opens_nothing(window, monkeypatch):
    """An empty answer must not be treated as the current directory."""
    main, wait, root = window(count=1, open_archive=False)
    monkeypatch.setattr(main, "main_window_choose_directory", lambda title: "")

    main.main_window_command("open")

    assert main.worker.archive_root is None
    assert main.quiet_requests == {}


def test_importing_runs_behind_the_progress_dialog(window, qtbot):
    """The sketch's §2 dialog is the surface for every long operation."""
    main, wait, root = window(count=4)

    summary = helper_import(main, wait, qtbot)

    assert "Added 4" in summary
    assert main.operation is not None
    assert main.operation.close_button.isVisibleTo(main.operation)
    assert main.operation.cancel_button.isVisibleTo(main.operation) is False
    qtbot.waitUntil(lambda: main.shell.counts.get("assets") == 4, timeout=15000)


def test_a_second_operation_is_refused_while_one_is_running(window, qtbot):
    """The worker serialises anyway; a second dialog would report queued work as running."""
    main, wait, root = window(count=3)
    main.main_window_command("import")
    first = main.operation
    assert first is not None

    main.main_window_command("verify")

    assert main.operation is first
    assert main.statusBar().currentMessage() == OPERATION_BUSY
    qtbot.waitUntil(lambda: not first.running, timeout=20000)


def test_the_dialog_only_reacts_to_its_own_request(window, qtbot):
    """A housekeeping read must not repaint or terminate somebody else's dialog."""
    main, wait, root = window(count=2)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None

    dialog.operation_reply(WorkerResult(dialog.request_id + 5000, "app_service_stats", {}))
    assert dialog.running is True

    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_hiding_keeps_the_operation_running(window, qtbot):
    """ "Hide" is the whole reason the dialog is modal; it must not cancel anything."""
    main, wait, root = window(count=3)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None

    dialog.operation_hide()

    assert dialog.isVisible() is False
    assert dialog.running is True
    assert "continues in the background" in main.statusBar().currentMessage()
    qtbot.waitUntil(lambda: main.shell.counts.get("assets") == 3, timeout=20000)


def test_closing_a_running_dialog_hides_it_instead_of_destroying_it(window, qtbot):
    """A destroyed dialog would leave a running operation with nothing to report it."""
    main, wait, root = window(count=2)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    destroyed = []
    dialog.destroyed.connect(lambda *arguments: destroyed.append(True))

    dialog.reject()

    assert destroyed == []
    assert main.operation is dialog
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_a_clean_hidden_run_closes_itself(window, qtbot):
    """A hidden dialog that finished cleanly would otherwise linger forever."""
    main, wait, root = window(count=2)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    dialog.operation_hide()

    qtbot.waitUntil(lambda: main.operation is None, timeout=20000)
    assert "Added 2" in main.statusBar().currentMessage()


def test_a_hidden_run_with_errors_comes_back(window, qtbot):
    """A list of failures must not be reduced to one replaceable status line."""
    main, wait, root = window(count=2)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    dialog.operation_hide()
    assert dialog.isVisible() is False

    dialog.operation_reply(
        WorkerResult(
            dialog.request_id,
            "app_service_import",
            ImportResult(error_count=1, errors=["disk full"]),
        )
    )

    assert dialog.isVisible() is True
    assert "disk full" in dialog.errors_label.text()


def test_long_error_lists_are_truncated_in_the_dialog(window, qtbot):
    """The dialog reports; the log keeps the whole story."""
    main, wait, root = window(count=1)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    errors = [f"file {index} failed" for index in range(MAX_ERROR_LINES + 4)]

    dialog.operation_reply(
        WorkerResult(
            dialog.request_id,
            "app_service_import",
            ImportResult(error_count=len(errors), errors=errors),
        )
    )

    assert "...and 4 more." in dialog.errors_label.text()


def test_cancelling_reaches_the_running_request(window, qtbot):
    """Cancel must set the operation's own event, not merely disable a button."""
    main, wait, root = window(count=6)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    request = main.worker.pending.get(dialog.request_id)

    dialog.operation_cancel()

    assert request is not None
    assert request.progress.handle.progress_is_cancelled() is True
    assert dialog.cancel_button.isEnabled() is False
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_cancelling_after_completion_is_harmless(window, qtbot):
    """The click and the slot are separated by the event loop; the run may already be over."""
    main, wait, root = window(count=1)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)

    dialog.running = True
    dialog.operation_cancel()

    assert dialog.cancelling is False


def test_progress_updates_move_the_bar(window, qtbot):
    """An unknown total stays indeterminate rather than sitting at zero percent."""
    main, wait, root = window(count=2)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    assert dialog.bar.minimum() == 0 and dialog.bar.maximum() == 0

    from iphone_archive.service.progress import ProgressEvent

    dialog.operation_progress(dialog.request_id, ProgressEvent("import", 1, 4, "IMG_0001.png"))

    assert dialog.bar.maximum() > 0
    assert dialog.bar.value() == dialog.bar.maximum() // 4
    assert dialog.count_label.text() == "1 of 4"
    assert "IMG_0001.png" in dialog.detail_label.text()
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_counts_refresh_quietly_without_a_dialog(window, qtbot):
    """A modal dialog for a counter refresh would flash open and shut saying nothing."""
    main, wait, root = window(count=2)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.operation is None, timeout=15000)

    main.main_window_command("stats")

    assert main.operation is None
    qtbot.waitUntil(lambda: "2 assets," in main.statusBar().currentMessage(), timeout=15000)
    assert "1 albums" in main.statusBar().currentMessage()


def test_the_duplicate_report_opens_its_own_window(window, qtbot):
    """Dedup produces a report to read, not a progress bar to watch."""
    main, wait, root = window(count=2)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()

    main.main_window_command("dedup")
    qtbot.waitUntil(
        lambda: any(isinstance(child, ReportDialog) for child in main.findChildren(ReportDialog)),
        timeout=15000,
    )

    report = main.findChildren(ReportDialog)[0]
    assert "Assets: 2" in report.body.toPlainText()
    report.close()


def test_moving_a_selection_puts_the_files_in_the_album(window, qtbot):
    """The move is the step's one mutation, and it must actually move the copies."""
    main, wait, root = window(count=4)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.models.assets.rowCount() == 4, timeout=15000)
    grid = main.shell.gallery.grid
    grid.selectAll()
    selection = grid.grid_selection()

    main.main_window_move_confirmed(selection, "Holiday")
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)

    assert "Moved" in dialog.detail_label.text()
    assert (root / "Photos" / "Holiday").is_dir()
    assert len(list((root / "Photos" / "Holiday").glob("*.png"))) == 4


def test_a_move_from_an_album_view_stays_scoped_to_that_album(window, qtbot):
    """An album grid shows one album's copies; the move must not promote to all of them."""
    main, wait, root = window(count=4)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.models.assets.rowCount() == 4, timeout=15000)
    submitted = []
    main.worker.request_submitted.connect(
        lambda request_id, operation: submitted.append((request_id, operation))
    )
    main.models.assets.asset_model_set_scope(AssetScope("album", 1))
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    grid = main.shell.gallery.grid
    grid.selectAll()
    selection = grid.grid_selection()

    main.main_window_move_confirmed(selection, "Holiday")

    dialog = main.operation
    assert dialog is not None
    request = main.worker.pending.get(dialog.request_id)
    if request is not None:
        assert request.parameters.get("source_album_id") == 1
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_a_stale_selection_never_reaches_the_service(window, qtbot):
    """The prompt is non-blocking, so the archive may have changed while it was open."""
    main, wait, root = window(count=3)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.models.assets.rowCount() == 3, timeout=15000)
    grid = main.shell.gallery.grid
    grid.selectAll()
    selection = grid.grid_selection()
    submitted = []
    main.worker.request_submitted.connect(lambda request_id, operation: submitted.append(operation))
    main.models.assets.model_reset()

    main.main_window_move_confirmed(selection, "Holiday")

    assert "app_service_move_selection" not in submitted
    assert main.main_window_busy() is False
    assert "not started" in main.statusBar().currentMessage()
    assert main.status_override is not None


def test_moving_nothing_asks_for_a_selection_first(window):
    """A move with no selection must explain itself rather than open an empty prompt."""
    main, wait, root = window(count=1)

    main.main_window_selection_action("move", None)

    assert "Select at least one" in main.statusBar().currentMessage()


def test_a_refused_submission_stays_on_screen(window, qtbot):
    """A command that never started must not be erased by the next routine refresh."""
    main, wait, root = window(count=1)
    main.worker.worker_shutdown()
    assert main.worker.worker_wait(5000)

    main.main_window_command("verify")

    assert main.operation is None
    assert "could not start" in main.statusBar().currentMessage()
    assert main.status_override == main.statusBar().currentMessage()


def test_a_failed_operation_keeps_its_error_on_screen(window, qtbot):
    """The shell re-reads its counters after a mutation; those reads must not hide the failure."""
    main, wait, root = window(count=1)
    request_id = main.main_window_start(
        "app_service_move_selection", {"asset_ids": [], "album_name": ""}
    )
    dialog = main.operation
    assert dialog is not None and request_id is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)

    assert "failed" in main.statusBar().currentMessage()
    assert main.status_override == main.statusBar().currentMessage()
    main.shell.shell_refresh()
    qtbot.wait(200)
    assert "failed" in main.statusBar().currentMessage()


def test_closing_the_window_closes_a_running_dialog(window, qtbot):
    """A modal dialog must not outlive the shell it belongs to."""
    main, wait, root = window(count=4)
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None

    main.close()

    assert main.operation is None
    assert dialog.isVisible() is False
    qtbot.waitUntil(lambda: not main.worker.service_thread.isRunning(), timeout=20000)


def test_an_unknown_verb_is_reported_rather_than_ignored(window):
    """No button may silently do nothing, including one added without a route."""
    main, wait, root = window(count=1)

    main.main_window_command("not-a-command")
    assert "not a command" in main.statusBar().currentMessage()

    main.main_window_selection_action("open", None)
    assert "not a batch action" in main.statusBar().currentMessage()


def test_titles_exist_for_every_routed_operation():
    """A blank dialog heading would leave the user guessing what is running."""
    for operation in ("app_service_import", "app_service_verify", "app_service_scan_phone"):
        assert operations_title(operation)[0].isupper()
    assert operations_title("app_service_made_up") == "made up"


def test_a_worker_failure_dialog_reports_the_message(qtbot):
    """A failure summary must name the operation and the error."""
    worker = WorkerController()
    try:
        dialog = OperationDialog(worker, 7, "app_service_verify", None)
        qtbot.addWidget(dialog)
        dialog.show()

        dialog.operation_reply(WorkerFailure(7, "app_service_verify", "OSError", "disk gone", ""))

        assert "disk gone" in dialog.detail_label.text()
        assert dialog.running is False
        assert dialog.close_button.isVisibleTo(dialog)
    finally:
        worker.worker_shutdown()
        worker.worker_wait(5000)


def test_a_replaced_dialog_does_not_orphan_the_running_one(window, qtbot):
    """A finished dialog dies an event-loop turn later, by which time it may be replaced."""
    main, wait, root = window(count=2)
    helper_import(main, wait, qtbot)
    finished = main.operation
    assert finished is not None
    finished.operation_close_now()
    # The replacement is installed while the old dialog is still awaiting its
    # deferred deletion, which is exactly the window the bug lived in.
    assert main.main_window_busy() is False
    main.main_window_command("verify")
    running = main.operation
    assert running is not None and running is not finished

    qtbot.waitUntil(lambda: not running.running, timeout=20000)

    assert main.operation is running
    assert main.main_window_busy() is False


def test_a_replaced_viewer_does_not_cancel_its_successors_renders(window, qtbot):
    """Cancelling the successor's renders would blank the image the user is looking at."""
    main, wait, root = window(count=3)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.models.assets.rowCount() == 3, timeout=15000)
    main.main_window_open_viewer(0)
    first = main.viewer
    assert first is not None
    first.close()
    main.main_window_open_viewer(1)
    second = main.viewer
    assert second is not None and second is not first

    qtbot.waitUntil(lambda: main.viewer_token > 1, timeout=5000)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert main.viewer is second
    second.close()


def test_clearing_previews_quiesces_the_loaders_first(window, qtbot):
    """The preview pools bypass the worker, so they would read files it is unlinking."""
    main, wait, root = window(count=3)
    helper_import(main, wait, qtbot)
    main.operation.operation_close_now()
    qtbot.waitUntil(lambda: main.models.assets.rowCount() == 3, timeout=15000)
    row = main.models.assets.index(0)
    main.previews.previews_entry(row.data(AssetRole.SHA256), row.data(AssetRole.PATHS)[0])
    qtbot.waitUntil(lambda: main.previews.cache.previews_cache_size() > 0, timeout=15000)

    main.main_window_command("clear-thumbnails")

    assert main.previews.pending == {}
    assert main.previews.cache.previews_cache_size() == 0
    assert main.viewer_previews.cache.previews_cache_size() == 0
    qtbot.waitUntil(lambda: "cached previews" in main.statusBar().currentMessage(), timeout=15000)


def test_a_locked_cache_file_does_not_abort_the_sweep(tmp_path):
    """One file a preview thread holds open must not stop the rest being deleted."""
    from unittest.mock import patch

    from iphone_archive.browse.thumbnails import THUMBNAIL_SUFFIX, thumbnails_clear_cache
    from iphone_archive.config import ArchivePaths

    paths = ArchivePaths(tmp_path)
    paths.thumbnails_dir.mkdir(parents=True)
    for index in range(3):
        (paths.thumbnails_dir / f"cached-{index}{THUMBNAIL_SUFFIX}").write_bytes(b"x")
    real_unlink = Path.unlink

    def unlink(self, *arguments, **keywords):
        if self.name.startswith("cached-1"):
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, *arguments, **keywords)

    with patch.object(Path, "unlink", unlink):
        removed = thumbnails_clear_cache(paths)

    assert removed == 2
    assert list(paths.thumbnails_dir.glob(f"*{THUMBNAIL_SUFFIX}"))
