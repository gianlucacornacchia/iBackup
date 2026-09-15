"""Offscreen destructive operations: confirmation, recycle bin, marks and reclaim.

These tests drive a real ``MainWindow`` against a fake phone and a temporary
archive, and unlike step 8 they really do delete things - inside ``tmp_path``,
never on a real device. That is the point: the guarantee being tested is that a
deletion happens only after the confirmation dialog has been satisfied, and
never before.

The confirmation dialog is shown rather than executed, so these tests type into
it and press its button exactly as a user would.
"""

from __future__ import annotations

import io
import os
from contextlib import contextmanager

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from iphone_archive.core.phone_diff import DeletedFromPhoneItem, PhoneDiffResult  # noqa: E402
from iphone_archive.core.reclaim import ReclaimCandidate, ReclaimResult  # noqa: E402
from iphone_archive.core.recycle import RecycleResult  # noqa: E402
from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui import main_window as main_window_module  # noqa: E402
from iphone_archive.gui.confirm import (  # noqa: E402
    CONFIRM_WORD,
    ConfirmDialog,
    ConfirmSpec,
    confirm_count_text,
    confirm_marks_spec,
    confirm_purge_spec,
    confirm_reclaim_spec,
    confirm_recycle_spec,
    confirm_size_line,
)
from iphone_archive.gui.main_window import MAX_BULK_REQUESTS, MainWindow  # noqa: E402
from iphone_archive.gui.operations import operations_summary  # noqa: E402
from iphone_archive.gui.reclaim import (  # noqa: E402
    ReclaimDialog,
    reclaim_caption,
    reclaim_rows,
    reclaim_selected_bytes,
)
from iphone_archive.gui.review import (  # noqa: E402
    MAX_REVIEW_ROWS,
    ReviewRow,
    review_mark_caption,
    review_mark_rows,
    review_phone_caption,
    review_phone_rows,
)
from iphone_archive.service.marks import MarkSummary  # noqa: E402


def helper_photo_bytes(number, size=(120, 90)):
    """Encode a small real PNG whose content is unique to this asset.

    number: the asset's index, mixed into the pixels.
    size: the image dimensions.
    Returns the encoded PNG bytes.
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
        device = FakeDevice(files, album_map=albums)

        @contextmanager
        def source_factory(udid):
            yield device

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
        return main, wait, root, device

    yield create
    for main in created:
        main.worker.worker_shutdown()
        assert main.worker.worker_wait(5000)
        main.previews.previews_shutdown()
        main.viewer_previews.previews_shutdown()
        qapp.processEvents()
        main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def helper_import(main, qtbot):
    """Run a full import and wait for it to finish.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns None.
    """
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)


def helper_select(main, rows):
    """Select grid rows and return the window's captured selection.

    main: the window under test.
    rows: the model rows to select.
    Returns None; the selection lives in the grid.
    """
    grid = main.shell.gallery.grid
    grid.grid_clear_selection()
    model = main.models.assets
    for position, row in enumerate(rows):
        index = model.index(row)
        flag = (
            grid.selectionModel().SelectionFlag.Select
            if position
            else grid.selectionModel().SelectionFlag.ClearAndSelect
        )
        grid.selectionModel().select(index, flag)
        grid.setCurrentIndex(index)


def helper_pending(main):
    """Return the operations the worker has been asked to run.

    main: the window under test.
    Returns the set of pending operation names. Asserting on this is the honest
    form of "nothing was submitted": the window's progress dialog reference
    survives for one event-loop turn after a previous operation finished, so it
    says nothing about whether new work was enqueued.
    """
    return {request.operation for request in main.worker.pending.values()}


def helper_statuses(main):
    """Collect every status-bar message the window shows from now on.

    main: the window under test.
    Returns the list, which fills as messages arrive. A transient message is
    legitimately replaced by the shell's state line within milliseconds, so it
    has to be recorded as it happens rather than read afterwards.
    """
    messages = []
    main.statusBar().messageChanged.connect(messages.append)
    return messages


def helper_confirm_dialog(main):
    """Return the confirmation dialog the window has open.

    main: the window under test.
    Returns the single ``ConfirmDialog`` child.
    """
    dialogs = [child for child in main.children() if isinstance(child, ConfirmDialog)]
    assert len(dialogs) == 1, dialogs
    return dialogs[0]


def helper_finish(main, qtbot):
    """Wait for the progress dialog the confirmation started.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns None.
    """
    qtbot.waitUntil(lambda: main.operation is not None, timeout=5000)
    dialog = main.operation
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_permanent_actions_demand_the_typed_word(qtbot):
    """A click alone must never be enough for something that cannot be undone."""
    spec = confirm_purge_spec(3, 1024, {"asset_ids": [1, 2, 3]}, False)
    dialog = ConfirmDialog(spec)
    qtbot.addWidget(dialog)
    approved = []
    dialog.confirmed.connect(approved.append)

    assert dialog.action_button.isEnabled() is False
    dialog.entry.setText("delete")
    assert dialog.action_button.isEnabled() is False
    dialog.entry.setText(CONFIRM_WORD)
    assert dialog.action_button.isEnabled() is True
    dialog.action_button.click()

    assert approved == [spec]


def test_the_typed_word_is_rechecked_when_the_button_is_pressed(qtbot):
    """The enabled state is a hint; the word itself is the gate."""
    dialog = ConfirmDialog(confirm_purge_spec(1, 0, {"asset_ids": [1]}, False))
    qtbot.addWidget(dialog)
    approved = []
    dialog.confirmed.connect(approved.append)

    # Force the button live without the word, as a stray shortcut or a future
    # change to the enabling rule could. The action must still refuse.
    dialog.action_button.setEnabled(True)
    dialog.action_button.click()

    assert approved == []
    # Still open and not accepted: refusing must not look like confirming.
    assert dialog.result() == 0


def test_a_reversible_action_is_confirmed_but_not_word_gated(qtbot):
    """Demanding the permanence word for something restorable teaches it away."""
    dialog = ConfirmDialog(confirm_recycle_spec(2, {"asset_ids": [1, 2]}))
    qtbot.addWidget(dialog)
    approved = []
    dialog.confirmed.connect(approved.append)

    assert dialog.entry is None
    assert dialog.action_button.isEnabled() is True
    dialog.action_button.click()

    assert len(approved) == 1
    assert approved[0].operation == "app_service_move_to_deleted"


def test_cancel_holds_default_focus_so_enter_dismisses(qtbot):
    """The safe choice must be the one an absent-minded keypress reaches."""
    dialog = ConfirmDialog(confirm_purge_spec(1, 0, {}, False))
    qtbot.addWidget(dialog)

    assert dialog.cancel_button.isDefault() is True
    assert dialog.action_button.isDefault() is False


def test_confirmation_texts_state_scope_and_reversibility():
    """The dialog must say what it will touch, and offer the reversible option."""
    whole = confirm_purge_spec(4, 2048, {}, False)
    recycled = confirm_purge_spec(4, 2048, {}, True)

    assert whole.permanent is True
    assert "cannot be undone" in " ".join(whole.body)
    assert "reversible" in whole.tip
    assert whole.parameters["recycled_only"] is False
    # A recycle-bin purge must not reach the asset's still-active copies, and
    # must not advertise moving to Deleted as an alternative to itself.
    assert recycled.parameters["recycled_only"] is True
    assert "already in the recycle bin" in " ".join(recycled.body)
    assert recycled.tip == ""
    assert confirm_count_text(1, "photo") == "1 photo"
    assert confirm_count_text(2, "photo") == "2 photos"
    assert confirm_size_line(0) == ""
    assert "Total size" in confirm_size_line(4096)


def test_only_the_permanent_mark_commit_asks_for_the_word():
    """Committing marks reversibly does not deserve the permanence word."""
    reversible = confirm_marks_spec(5, purge=False)
    permanent = confirm_marks_spec(5, purge=True)

    assert reversible.permanent is False
    assert reversible.parameters == {"confirmed": True, "purge": False}
    assert permanent.permanent is True
    assert permanent.parameters == {"confirmed": True, "purge": True}
    # An album mark deletes that album's copies only; saying so prevents the
    # user reading "5 items" as "5 whole assets".
    assert "not every copy" in " ".join(permanent.body)


def test_reclaim_confirmation_promises_the_archive_is_untouched():
    """The one operation that deletes outside the archive must say what it spares."""
    spec = confirm_reclaim_spec(12, 5_000_000, [1, 2, 3])

    assert spec.permanent is True
    assert spec.operation == "app_service_reclaim"
    assert spec.parameters == {"confirmed": True, "asset_ids": [1, 2, 3]}
    assert "archive is not modified" in " ".join(spec.body)


def test_moving_to_the_recycle_bin_requires_confirmation_and_then_moves(window, qtbot):
    """The reversible delete still asks, and only then moves any file."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])

    main.shell.shell_gallery_action("delete")
    # Nothing may have been submitted yet: the dialog is the gate.
    assert "app_service_move_to_deleted" not in helper_pending(main)
    dialog = helper_confirm_dialog(main)
    assert dialog.spec.operation == "app_service_move_to_deleted"
    dialog.action_button.click()
    helper_finish(main, qtbot)

    deleted = list((root / "Deleted").rglob("*.png"))
    assert len(deleted) >= 1


def test_cancelling_the_confirmation_deletes_nothing(window, qtbot):
    """The whole point of the gate is that declining it changes nothing."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    before = sorted(path.name for path in (root / "Photos").rglob("*.png"))
    helper_select(main, [0])

    main.shell.shell_gallery_action("purge")
    dialog = helper_confirm_dialog(main)
    dialog.cancel_button.click()
    qtbot.wait(100)

    assert "app_service_purge" not in helper_pending(main)
    assert sorted(path.name for path in (root / "Photos").rglob("*.png")) == before
    assert not (root / "Deleted").exists() or not list((root / "Deleted").rglob("*.png"))


def test_a_purge_really_removes_the_files_after_the_word_is_typed(window, qtbot):
    """Permanent means permanent; the test proves the bytes are gone."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    before = list((root / "Photos").rglob("*.png"))
    assert before
    helper_select(main, [0])

    main.shell.shell_gallery_action("purge")
    dialog = helper_confirm_dialog(main)
    dialog.entry.setText(CONFIRM_WORD)
    dialog.action_button.click()
    helper_finish(main, qtbot)

    after = list((root / "Photos").rglob("*.png"))
    assert len(after) < len(before)


def test_a_stale_selection_cannot_be_purged_after_the_dialog_opens(window, qtbot):
    """A non-blocking prompt means the world can move while it is on screen."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])
    selection = main.shell.gallery.grid.grid_selection()

    # The dialog is already open when the view changes underneath it.
    main.shell.shell_show_view("unsorted")
    qtbot.wait(50)
    statuses = helper_statuses(main)
    main.main_window_selection_confirmed(selection, confirm_purge_spec(1, 0, {}, False))

    assert "app_service_purge" not in helper_pending(main)
    assert any("was not started" in message for message in statuses)


def test_a_recycle_bin_purge_is_restricted_to_the_recycled_copies(window, qtbot):
    """Purging what you can see must not reach copies you cannot."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])
    main.shell.shell_gallery_action("delete")
    helper_confirm_dialog(main).action_button.click()
    helper_finish(main, qtbot)

    main.shell.shell_show_view("recycled")
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    helper_select(main, [0])
    main.shell.shell_gallery_action("purge")
    dialog = helper_confirm_dialog(main)

    assert dialog.spec.parameters["recycled_only"] is True


def test_restoring_needs_no_confirmation_and_returns_the_file(window, qtbot):
    """Putting something back is not destructive, so it is not gated."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])
    main.shell.shell_gallery_action("delete")
    helper_confirm_dialog(main).action_button.click()
    helper_finish(main, qtbot)
    assert list((root / "Deleted").rglob("*.png"))

    main.shell.shell_show_view("recycled")
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    helper_select(main, [0])
    main.shell.shell_gallery_action("restore")

    assert not [child for child in main.children() if isinstance(child, ConfirmDialog)]
    helper_finish(main, qtbot)
    assert not list((root / "Deleted").rglob("*.png"))


def test_marking_stages_a_deletion_without_deleting(window, qtbot):
    """A mark is a note, not an action, and the GUI must never blur the two."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    before = sorted(path.name for path in (root / "Photos").rglob("*.png"))
    helper_select(main, [0])
    statuses = helper_statuses(main)

    main.shell.shell_gallery_action("mark")
    qtbot.waitUntil(lambda: main.shell.counts.get("marked", 0) > 0, timeout=15000)

    assert sorted(path.name for path in (root / "Photos").rglob("*.png")) == before
    assert list((root / "Deleted").rglob("*.png")) == []
    assert any("Nothing has been deleted" in message for message in statuses)


def test_marking_from_an_album_says_it_covers_every_copy(window, qtbot):
    """A whole-asset mark shown in an album view must not imply album scope."""
    main, wait, root, device = window(count=4)
    helper_import(main, qtbot)
    qtbot.waitUntil(lambda: bool(main.shell.navigation.albums), timeout=15000)
    album_id = main.shell.navigation.albums[0][0]
    from iphone_archive.gui.navigation import navigation_album_key

    main.shell.shell_show_view(navigation_album_key(album_id))
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    helper_select(main, [0])

    statuses = helper_statuses(main)
    main.shell.shell_gallery_action("mark")

    assert any("copies in other albums" in message for message in statuses)


def test_committing_marks_applies_the_whole_queue_after_confirmation(window, qtbot):
    """The CLI commits the queue, so the GUI must not pretend it commits a selection."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])
    main.shell.shell_gallery_action("mark")
    qtbot.waitUntil(lambda: main.shell.counts.get("marked", 0) > 0, timeout=15000)
    main.shell.shell_show_view("marked")
    qtbot.waitUntil(lambda: bool(main.shell.reviews["marked"].review_list.rows), timeout=15000)

    # Nothing is ticked: a commit is queue-wide and must still be offered.
    main.main_window_review_action("marked", "commit-recycle")
    dialog = helper_confirm_dialog(main)
    assert dialog.spec.parameters == {"confirmed": True, "purge": False}
    dialog.action_button.click()
    helper_finish(main, qtbot)

    assert list((root / "Deleted").rglob("*.png"))


def test_clearing_marks_never_asks_because_it_deletes_nothing(window, qtbot):
    """Confirmation fatigue is a safety problem: only ask where it matters."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0])
    main.shell.shell_gallery_action("mark")
    qtbot.waitUntil(lambda: main.shell.counts.get("marked", 0) > 0, timeout=15000)

    main.main_window_review_action("marked", "clear")

    assert not [child for child in main.children() if isinstance(child, ConfirmDialog)]
    qtbot.waitUntil(lambda: main.shell.counts.get("marked", 1) == 0, timeout=15000)


def test_a_huge_unmark_is_refused_rather_than_flooding_the_queue(window, qtbot):
    """The worker's queue is bounded; a bulk action must not overflow it."""
    main, wait, root, device = window(count=1)
    page = main.shell.reviews["marked"]
    page.review_set_rows(
        [ReviewRow(number, f"Asset {number}") for number in range(MAX_BULK_REQUESTS + 5)],
        "many marks",
    )
    page.review_set_all(True)

    statuses = helper_statuses(main)
    main.main_window_review_action("marked", "unmark")

    assert any("Clear all marks" in message for message in statuses)
    assert "app_service_unmark" not in helper_pending(main)


def test_the_deleted_on_phone_report_lists_and_gates_its_actions(window, qtbot):
    """Section 3's whole purpose is deciding per item, so it must list them."""
    main, wait, root, device = window(count=2)
    page = main.shell.reviews["deleted-phone"]
    result = PhoneDiffResult(
        items=[
            DeletedFromPhoneItem(7, "a" * 64, "IMG_0102.HEIC", 4096, "2026-08-14"),
            DeletedFromPhoneItem(8, "b" * 64, "IMG_0103.HEIC", 8192, None),
        ]
    )
    main.shell.shell_set_review("deleted-phone", result)

    assert [row.identifier for row in page.review_list.rows] == [7, 8]
    # With nothing ticked, the destructive buttons must be unusable.
    assert page.buttons["purge"].isEnabled() is False
    page.review_set_all(True)
    assert page.buttons["purge"].isEnabled() is True

    main.main_window_review_action("deleted-phone", "purge")
    dialog = helper_confirm_dialog(main)
    assert dialog.spec.parameters["asset_ids"] == [7, 8]
    assert dialog.spec.parameters["recycled_only"] is False


def test_keeping_in_archive_changes_nothing_at_all(window, qtbot):
    """The default answer to "this is gone from your phone" must be inaction."""
    main, wait, root, device = window(count=1)
    page = main.shell.reviews["deleted-phone"]
    main.shell.shell_set_review(
        "deleted-phone",
        PhoneDiffResult(items=[DeletedFromPhoneItem(7, "a" * 64, "IMG.HEIC", 4096, None)]),
    )
    page.review_set_all(True)

    statuses = helper_statuses(main)
    main.main_window_review_action("deleted-phone", "keep")

    assert page.review_checked_ids() == []
    assert not helper_pending(main) & {"app_service_purge", "app_service_move_to_deleted"}
    assert any("Nothing was changed" in message for message in statuses)


def test_a_refreshed_report_never_carries_its_ticks_across(window, qtbot):
    """Re-checking a replaced row would aim a deletion at something unchosen."""
    main, wait, root, device = window(count=1)
    page = main.shell.reviews["deleted-phone"]
    main.shell.shell_set_review(
        "deleted-phone",
        PhoneDiffResult(items=[DeletedFromPhoneItem(7, "a" * 64, "A.HEIC", 1, None)]),
    )
    page.review_set_all(True)
    assert page.review_checked_ids() == [7]

    main.shell.shell_set_review(
        "deleted-phone",
        PhoneDiffResult(items=[DeletedFromPhoneItem(9, "b" * 64, "B.HEIC", 1, None)]),
    )

    assert page.review_checked_ids() == []


def test_review_rows_and_captions_describe_what_is_at_stake():
    """A count alone does not tell the user whether it is safe to act."""
    result = PhoneDiffResult(
        items=[DeletedFromPhoneItem(7, "a" * 64, "IMG.HEIC", 4096, "2026-08-14")]
    )
    rows = review_phone_rows(result)

    assert rows[0].identifier == 7
    assert "last seen on phone 2026-08-14" in rows[0].detail
    assert "still safe" not in review_phone_caption(result)
    assert "Nothing happens automatically" in review_phone_caption(result)
    assert "still on the iPhone" in review_phone_caption(PhoneDiffResult())
    assert review_phone_rows("not a result") == []

    marks = [
        MarkSummary(1, "asset", 5, "2026-09-01", "blurry"),
        MarkSummary(2, "album", 3, None, None),
    ]
    mark_rows = review_mark_rows(marks)
    assert [row.identifier for row in mark_rows] == [1, 2]
    assert "Album 3" == mark_rows[1].label
    assert "nothing has been deleted yet" in review_mark_caption(marks)
    assert "whole albums" in review_mark_caption(marks)
    assert "never deletes" in review_mark_caption([])


def test_long_reports_are_bounded_and_say_so():
    """An unbounded listing would freeze the window it is meant to inform."""
    items = [
        DeletedFromPhoneItem(number, f"{number:064d}", f"IMG_{number}.HEIC", 10, None)
        for number in range(MAX_REVIEW_ROWS + 25)
    ]
    result = PhoneDiffResult(items=items)

    assert len(review_phone_rows(result)) == MAX_REVIEW_ROWS
    assert f"first {MAX_REVIEW_ROWS}" in review_phone_caption(result)


def test_reclaim_runs_a_dry_run_before_offering_any_deletion(window, qtbot):
    """A preview is not an authorization, so the first pass must not delete."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)

    main.main_window_command("reclaim")
    dialog = main.operation
    assert dialog is not None
    assert dialog.operation == "app_service_reclaim"
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)

    # The dry run submits no confirmation, so the phone still holds every file.
    assert device.deleted_paths == []
    assert len(device.items) == 2
    assert "Nothing has been deleted" in operations_summary(
        "app_service_reclaim", ReclaimResult(dry_run=True)
    )


def test_the_reclaim_dialog_is_the_only_route_to_a_phone_deletion(qtbot):
    """Every phone-side deletion must be traceable to a reviewed candidate list."""
    result = ReclaimResult(
        candidates=[
            ReclaimCandidate(1, "/DCIM/IMG_0001.PNG", "IMG_0001.PNG", 4000),
            ReclaimCandidate(2, "/DCIM/IMG_0002.PNG", "IMG_0002.PNG", 6000),
        ],
        skipped_count=1,
        dry_run=True,
    )
    dialog = ReclaimDialog(result)
    qtbot.addWidget(dialog)
    requested = []
    dialog.reclaim_requested.connect(requested.append)

    # Nothing ticked: the destructive button cannot be pressed into acting.
    assert dialog.delete_button.isEnabled() is False
    dialog.reclaim_request()
    assert requested == []

    dialog.review_list.review_set_all(True)
    assert dialog.delete_button.isEnabled() is True
    assert "2 items" in dialog.delete_button.text()
    dialog.delete_button.click()

    assert requested == [[1, 2]]


def test_the_reclaim_dialog_still_reports_whether_it_was_accepted(qtbot):
    """Holding the preview must not shadow the dialog's own accepted/rejected code."""
    result = ReclaimResult(
        candidates=[ReclaimCandidate(1, "/DCIM/A.PNG", "A.PNG", 4000)], dry_run=True
    )
    dialog = ReclaimDialog(result)
    qtbot.addWidget(dialog)

    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.review_list.review_set_all(True)
    dialog.delete_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_the_reclaim_report_names_what_it_refused_to_offer(qtbot):
    """A file that failed its re-check is the most important thing on that screen."""
    result = ReclaimResult(
        candidates=[ReclaimCandidate(1, "/DCIM/A.PNG", "A.PNG", 4000)],
        skipped_count=4,
        dry_run=True,
    )

    caption = reclaim_caption(result)
    assert "4 were skipped" in caption
    assert "integrity check" in caption
    assert [row.identifier for row in reclaim_rows(result)] == [1]
    assert reclaim_selected_bytes(result, [1]) == 4000
    assert reclaim_selected_bytes(result, [99]) == 0


def test_a_reclaim_request_still_has_to_pass_the_typed_confirmation(window, qtbot):
    """The dialog chooses the candidates; the word is still what permits deletion."""
    main, wait, root, device = window(count=2)
    preview = ReclaimResult(
        candidates=[ReclaimCandidate(1, "/DCIM/A.PNG", "A.PNG", 4000)], dry_run=True
    )

    main.main_window_reclaim_requested(preview, [1])

    dialog = helper_confirm_dialog(main)
    assert dialog.spec.permanent is True
    assert dialog.spec.parameters == {"confirmed": True, "asset_ids": [1]}
    assert dialog.action_button.isEnabled() is False


def test_an_empty_dry_run_opens_no_dialog_to_dismiss(window, qtbot):
    """There is nothing to decide, and a dialog saying so is just another click."""
    main, wait, root, device = window(count=1)

    main.main_window_open_reclaim(ReclaimResult(dry_run=True))

    assert not [child for child in main.children() if isinstance(child, ReclaimDialog)]


def test_a_completed_deletion_is_never_mistaken_for_a_preview():
    """ "3918 items" after a dry run would imply a deletion that did not happen."""
    preview = operations_summary("app_service_reclaim", ReclaimResult(dry_run=True, candidates=[]))
    real = operations_summary("app_service_reclaim", ReclaimResult(dry_run=False, deleted_count=12))

    assert "Nothing has been deleted" in preview
    assert "Deleted 12 items" in real
    assert "archive is unchanged" in real


def test_recycle_summaries_report_only_what_happened():
    """A restore reporting "0 deleted" invites exactly the wrong conclusion."""
    moved = operations_summary("app_service_move_to_deleted", RecycleResult(moved_count=3))
    restored = operations_summary("app_service_restore", RecycleResult(restored_count=2))
    purged = operations_summary("app_service_purge", RecycleResult(purged_count=1, errors=["x"]))

    assert moved == "3 moved to the deleted folder."
    assert "deleted" not in restored.lower().replace("deleted folder", "")
    assert "2 restored" in restored
    assert "1 permanently deleted" in purged
    assert "1 errors" in purged
    assert operations_summary("app_service_restore", RecycleResult()) == "Nothing changed."


def test_a_destructive_action_is_refused_while_another_operation_runs(window, qtbot):
    """One dialog, one operation: a queued deletion the user cannot see is a trap."""
    main, wait, root, device = window(count=4)
    helper_import(main, qtbot)
    helper_select(main, [0])
    main.main_window_command("verify")

    statuses = helper_statuses(main)
    main.shell.shell_gallery_action("purge")

    assert not [child for child in main.children() if isinstance(child, ConfirmDialog)]
    assert any("Another operation" in message for message in statuses)
    dialog = main.operation
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_an_unknown_spec_is_ignored_rather_than_submitted(window, qtbot):
    """A confirmation handler is the last gate; it must not trust its input."""
    main, wait, root, device = window(count=1)

    main.main_window_confirmed("not a spec")
    main.main_window_selection_confirmed(None, "not a spec")

    # Whatever housekeeping the shell has in flight, nothing destructive may be.
    assert not helper_pending(main) & {
        "app_service_purge",
        "app_service_move_to_deleted",
        "app_service_reclaim",
        "app_service_commit_marks",
    }


def test_review_lists_report_their_checked_rows_in_display_order():
    """A deletion must act on what the user ticked, in the order they saw it."""
    from iphone_archive.gui.review import ReviewList

    listing = ReviewList("empty")
    listing.review_set_rows([ReviewRow(5, "A"), ReviewRow(3, "B"), ReviewRow(9, "C")])
    listing.list_widget.item(0).setCheckState(Qt.CheckState.Checked)
    listing.list_widget.item(2).setCheckState(Qt.CheckState.Checked)

    assert listing.review_checked_ids() == [5, 9]
    listing.review_set_all(False)
    assert listing.review_checked_ids() == []


def test_the_confirmation_spec_carries_exactly_what_will_be_submitted(window, qtbot):
    """What the dialog described and what the worker runs must be the same thing."""
    main, wait, root, device = window(count=2)
    helper_import(main, qtbot)
    helper_select(main, [0, 1])
    submitted = []
    main.worker.result_ready.connect(lambda reply: submitted.append(reply.operation))

    main.shell.shell_gallery_action("delete")
    dialog = helper_confirm_dialog(main)
    spec = dialog.spec
    dialog.action_button.click()
    helper_finish(main, qtbot)

    assert spec.operation == "app_service_move_to_deleted"
    assert "app_service_move_to_deleted" in submitted


def test_an_empty_review_action_reports_instead_of_acting(window, qtbot):
    """A button that appears to work and does nothing is its own kind of bug."""
    main, wait, root, device = window(count=1)

    statuses = helper_statuses(main)

    main.main_window_phone_review_action("purge", [])
    main.main_window_review_action("marked", "unmark")
    main.main_window_review_action("marked", "commit-purge")
    main.main_window_phone_review_action("nonsense", [1])

    reported = " | ".join(statuses)
    assert "Tick the items" in reported
    assert "Tick the marks" in reported
    assert "Nothing is marked" in reported
    assert "not an action here" in reported


def test_a_spec_is_a_value_not_a_live_object():
    """Worker parameters must be plain data the boundary can copy safely."""
    spec = ConfirmSpec(
        "t", "a", False, operation="app_service_purge", parameters={"asset_ids": [1]}
    )

    assert isinstance(spec.parameters["asset_ids"], list)
    assert spec.parameters["asset_ids"] == [1]
