"""Offscreen shell: navigation keys/counts, command availability and live status."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402

from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui.commands import (  # noqa: E402
    COMMANDS,
    COMMANDS_BY_KEY,
    commands_enabled,
    commands_reason,
)
from iphone_archive.gui.icons import GLYPH_NAMES, icons_draw, icons_get, icons_pixmap  # noqa: E402
from iphone_archive.gui.models import ArchiveModels, AssetScope  # noqa: E402
from iphone_archive.gui.navigation import (  # noqa: E402
    LIBRARY_VIEWS,
    NAV_COUNT_ROLE,
    NAV_KEY_ROLE,
    NAV_WIDTH,
    RAIL_WIDTH,
    NavigationPane,
    navigation_album_id,
    navigation_album_key,
    navigation_format_count,
)
from iphone_archive.gui.previews import PreviewLoader  # noqa: E402
from iphone_archive.gui.shell import ArchiveShell  # noqa: E402
from iphone_archive.gui.worker import WorkerController  # noqa: E402


@pytest.fixture
def shell(qapp, qtbot, tmp_path):
    """Build a shell over a real worker and archive, and shut it down afterwards."""
    created = []

    def create(**kwargs):
        worker = WorkerController(**kwargs)
        models = ArchiveModels(worker)
        previews = PreviewLoader()
        instance = ArchiveShell(worker, models, previews)
        qtbot.addWidget(instance)
        replies, failures = {}, {}
        worker.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
        worker.failed.connect(lambda error: failures.update({error.request_id: error}))
        created.append((worker, models, previews, instance))

        def wait(request_id):
            qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=10000)
            return replies.get(request_id) or failures[request_id]

        root = tmp_path / f"archive-{len(created)}"
        return worker, models, instance, wait, root

    yield create
    for worker, models, previews, instance in created:
        worker.worker_shutdown()
        assert worker.worker_wait(5000)
        previews.previews_shutdown()
        qapp.processEvents()
        instance.deleteLater()
        previews.deleteLater()
        models.deleteLater()
        worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def helper_open(shell_tuple, qtbot, *, create=True):
    """Open the archive and wait for the shell's own counter refresh to land."""
    worker, models, instance, wait, root = shell_tuple
    reply = wait(worker.worker_open(root, create=create))
    assert getattr(reply, "message", None) is None, getattr(reply, "message", "")
    qtbot.waitUntil(lambda: instance.counts.get("assets") is not None, timeout=10000)
    return root


def test_every_glyph_draws_something(qapp):
    """A silently blank icon is hard to spot, so unknown glyphs must fail loudly."""
    for glyph in GLYPH_NAMES:
        pixmap = icons_pixmap(glyph, QColor("#FFFFFF"))
        image = pixmap.toImage()
        painted = any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(image.width())
            for y in range(image.height())
        )
        assert painted, glyph
    with pytest.raises(ValueError):
        icons_pixmap("no-such-glyph", QColor("#FFFFFF"))
    for bad in (0, 4, 512, True):
        with pytest.raises(ValueError):
            icons_pixmap("photos", QColor("#FFFFFF"), bad)


def test_icons_take_the_callers_colour(qapp):
    """Drawn icons follow light, dark and high-contrast themes without a second asset set."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    icons_draw(painter, QRect(0, 0, 16, 16), "verify", QColor("#FF0000"))
    painter.end()
    image = pixmap.toImage()
    colours = {
        image.pixelColor(x, y).rgb()
        for x in range(16)
        for y in range(16)
        if image.pixelColor(x, y).alpha() > 200
    }
    assert colours and all(QColor(rgb).red() > QColor(rgb).blue() for rgb in colours)
    assert isinstance(icons_get("photos", QColor("#FFFFFF")).availableSizes(), list)


def test_album_navigation_keys_round_trip():
    """Album rows and library rows must never be confused by the page stack."""
    assert navigation_album_id(navigation_album_key(7)) == 7
    assert navigation_album_id("all") is None
    assert navigation_album_id("album:x") is None
    for bad in (0, -1, True, "3"):
        with pytest.raises(ValueError):
            navigation_album_key(bad)
    assert navigation_format_count(None) == ""
    assert navigation_format_count(1297).replace("\u2009", ",") == "1,297"


def test_navigation_lists_library_rows_and_albums(qtbot):
    """The pane shows every library view plus catalog albums with their counts."""
    pane = NavigationPane()
    qtbot.addWidget(pane)
    keys = [
        pane.list_widget.item(row).data(NAV_KEY_ROLE)
        for row in range(pane.list_widget.count())
        if pane.list_widget.item(row).data(NAV_KEY_ROLE)
    ]
    assert keys == [view.key for view in LIBRARY_VIEWS]
    pane.navigation_set_counts({"assets": 1297, "unsorted": 312, "unknown_key": 5})
    pane.navigation_set_albums([(3, "Trip 2024", 420)])
    rows = {
        pane.list_widget.item(row).data(NAV_KEY_ROLE): pane.list_widget.item(row).data(
            NAV_COUNT_ROLE
        )
        for row in range(pane.list_widget.count())
    }
    assert rows["all"] == 1297
    assert rows["album:3"] == 420
    assert rows["recycled"] is None
    with pytest.raises(TypeError):
        pane.navigation_set_counts([("all", 1)])


def test_navigation_keeps_the_selected_row_across_refreshes(qtbot):
    """A count refresh must not throw the user back to the first view."""
    pane = NavigationPane()
    qtbot.addWidget(pane)
    emitted = []
    pane.navigation_selected.connect(emitted.append)
    pane.navigation_set_albums([(3, "Trip", 4)])
    assert pane.navigation_select("album:3")
    pane.navigation_set_counts({"assets": 9})
    assert pane.current_key == "album:3"
    # Rebuilding rows must not look like a user navigation.
    assert emitted == []
    pane.navigation_set_albums([])
    assert pane.current_key == LIBRARY_VIEWS[0].key


def test_navigation_collapses_to_a_rail(qtbot):
    """The pane collapses by hamburger and auto-collapses on narrow windows."""
    pane = NavigationPane()
    qtbot.addWidget(pane)
    assert pane.width() == NAV_WIDTH
    pane.navigation_toggle()
    assert pane.collapsed and pane.width() == RAIL_WIDTH
    assert pane.settings_button.text() == ""
    pane.navigation_apply_width(1200)
    assert not pane.collapsed
    pane.navigation_apply_width(700)
    assert pane.collapsed


def test_every_command_names_a_real_operation():
    """The command bar is the only menu, so each verb must map to a service call."""
    from iphone_archive.gui.worker import LIFECYCLE_OPERATIONS, SERVICE_OPERATIONS

    known = LIFECYCLE_OPERATIONS | SERVICE_OPERATIONS
    for command in COMMANDS:
        assert command.operation in known, command.key
    assert len({command.key for command in COMMANDS}) == len(COMMANDS)


def test_command_availability_explains_itself():
    """A disabled button must say why, rather than looking broken."""
    import_command = COMMANDS_BY_KEY["import"]
    assert not commands_enabled(import_command, False, "connected")
    assert "Open an archive first" in commands_reason(import_command, False, "connected")
    assert not commands_enabled(import_command, True, "disconnected")
    assert "Connect the iPhone" in commands_reason(import_command, True, "disconnected")
    # Unknown phone state must not block the user; there is no cheap presence probe.
    assert commands_enabled(import_command, True, "unknown")
    verify = COMMANDS_BY_KEY["verify"]
    assert commands_enabled(verify, True, "disconnected")
    open_command = COMMANDS_BY_KEY["open"]
    assert commands_enabled(open_command, False, "unknown")
    assert not commands_enabled(open_command, True, "unknown")


def test_shell_starts_closed_and_disables_archive_commands(shell, qtbot):
    """Nothing may imply an archive is loaded before one is opened."""
    _, _, instance, _, _ = shell()
    assert not instance.archive_open
    assert "no archive open" in instance.shell_status_text()
    assert not instance.command_bar.buttons["import"].isEnabled()
    assert instance.command_bar.buttons["open"].isEnabled()
    with pytest.raises(ValueError):
        instance.command_bar.commands_set_state(True, "charging")


def test_opening_an_archive_refreshes_counts_and_commands(shell, qtbot):
    """Counters and albums come from the worker, never from the GUI thread."""
    parts = shell()
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    assert instance.archive_open
    assert instance.counts["assets"] == 0
    assert instance.command_bar.buttons["verify"].isEnabled()
    assert "0 assets" in instance.shell_status_text()


def test_import_populates_navigation_albums_and_counts(shell, qtbot):
    """Album rows and live counts follow a real import through the worker."""

    @contextmanager
    def source_factory(udid):
        yield FakeDevice(
            {"/DCIM/a.jpg": b"a", "/DCIM/b.jpg": b"b"},
            album_map={"/DCIM/a.jpg": ["Trip"]},
        )

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_import"))
    qtbot.waitUntil(lambda: instance.counts.get("assets") == 2, timeout=10000)
    qtbot.waitUntil(lambda: bool(instance.navigation.albums), timeout=10000)
    names = {name for _, name, _ in instance.navigation.albums}
    assert "Trip" in names
    assert instance.phone == "connected"
    assert "iPhone connected" in instance.shell_status_text()


def test_device_failure_marks_the_phone_disconnected(shell, qtbot):
    """A failed device operation is the only honest presence signal available."""

    @contextmanager
    def source_factory(udid):
        raise OSError("no device")
        yield

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_device_info"))
    assert instance.phone == "disconnected"
    assert "No iPhone detected" in instance.shell_status_text()
    assert not instance.command_bar.buttons["import"].isEnabled()
    assert instance.command_bar.buttons["verify"].isEnabled()


def test_selecting_a_view_switches_the_page_and_the_model_scope(shell, qtbot):
    """Navigation drives the shared asset model rather than a private query."""
    parts = shell()
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    instance.navigation.navigation_select("recycled")
    instance.shell_view_selected("recycled")
    assert models.assets.pending_scope == AssetScope("recycled") or models.assets.scope == (
        AssetScope("recycled")
    )
    assert instance.stack.currentWidget() is instance.pages["recycled"]
    assert instance.stack.currentWidget().title_label.text() == "Recycle bin"


def test_selecting_an_album_scopes_to_that_album(shell, qtbot):
    """Album pages must scope to the album's own copies, not every copy of an asset."""

    @contextmanager
    def source_factory(udid):
        yield FakeDevice({"/DCIM/a.jpg": b"a"}, album_map={"/DCIM/a.jpg": ["Trip"]})

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_import"))
    qtbot.waitUntil(lambda: bool(instance.navigation.albums), timeout=10000)
    album_id = next(
        identifier for identifier, name, _ in instance.navigation.albums if name == "Trip"
    )
    key = navigation_album_key(album_id)
    instance.navigation.navigation_select(key)
    instance.shell_view_selected(key)
    scope = models.assets.pending_scope or models.assets.scope
    assert scope == AssetScope("album", album_id)
    assert instance.stack.currentWidget().title_label.text() == "Trip"


def test_closing_an_archive_clears_counts_and_albums(shell, qtbot):
    """Stale counters from a closed archive would misreport what is stored."""

    @contextmanager
    def source_factory(udid):
        yield FakeDevice({"/DCIM/a.jpg": b"a"}, album_map={"/DCIM/a.jpg": ["Trip"]})

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_import"))
    qtbot.waitUntil(lambda: bool(instance.navigation.albums), timeout=10000)
    wait(worker.worker_submit("close_archive"))
    assert instance.counts == {}
    assert instance.navigation.albums == ()
    assert instance.navigation.current_key == LIBRARY_VIEWS[0].key
    assert "no archive open" in instance.shell_status_text()
    assert not instance.command_bar.buttons["import"].isEnabled()


def test_shutdown_returns_the_shell_to_the_closed_presentation(shell, qtbot):
    """Worker shutdown must not leave the window claiming an archive is open."""
    parts = shell()
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    worker.worker_shutdown()
    assert worker.worker_wait(5000)
    QCoreApplication.processEvents()
    assert instance.counts == {}
    assert "no archive open" in instance.shell_status_text()


def test_main_window_hosts_the_shell_and_reports_commands(qtbot):
    """The window shows the shell, and no command may silently do nothing."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.centralWidget() is window.shell
    assert window.menuBar().isVisible() is False
    # A verb that is gated behind a later step must say so rather than appear
    # to work; this one needs no worker, so the window starts no archive session.
    window.shell.command_bar.command_triggered.emit("reclaim")
    assert "step 9" in window.statusBar().currentMessage()
    window.shell.shell_status_changed.emit("hello")
    assert window.statusBar().currentMessage() == "hello"
    assert window.worker.service_thread.isRunning() is False


def test_errors_are_not_wiped_by_the_next_status_refresh(qtbot):
    """A routine state line must never silently hide a failure the user needs to see."""
    from iphone_archive.gui.main_window import MainWindow
    from iphone_archive.gui.worker import WorkerFailure

    window = MainWindow()
    qtbot.addWidget(window)
    window.main_window_worker_failed(WorkerFailure(1, "open_archive", "OSError", "boom", ""))
    assert "boom" in window.statusBar().currentMessage()
    window.shell.shell_status_changed.emit("iPhone not checked - no archive open")
    assert "boom" in window.statusBar().currentMessage()
    window.main_window_clear_error()
    window.shell.shell_status_changed.emit("iPhone not checked - no archive open")
    assert "no archive open" in window.statusBar().currentMessage()


def test_cancelled_import_still_refreshes_counts(shell, qtbot):
    """A cancelled import has already committed what it copied, so counts are stale."""

    @contextmanager
    def source_factory(udid):
        yield FakeDevice({f"/DCIM/{index}.jpg": bytes([index]) for index in range(40)})

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    submitted = []
    worker.request_submitted.connect(lambda request_id, name: submitted.append(name))
    cancelled = []
    worker.cancelled.connect(cancelled.append)
    request_id = worker.worker_submit("app_service_import")
    worker.worker_cancel(request_id)
    qtbot.waitUntil(lambda: bool(cancelled), timeout=10000)
    # The refresh must be triggered by the cancellation itself, not by a later
    # unrelated operation, or the pane keeps pre-import counts and album rows.
    after_cancel = submitted[submitted.index("app_service_import") + 1 :]
    qtbot.waitUntil(lambda: "app_service_stats" in submitted, timeout=10000)
    after_cancel = submitted[submitted.index("app_service_import") + 1 :]
    assert "app_service_stats" in after_cancel


def test_closing_an_archive_moves_the_visible_page_back(shell, qtbot):
    """The page stack must never show an album from an archive that is gone."""

    @contextmanager
    def source_factory(udid):
        yield FakeDevice({"/DCIM/a.jpg": b"a"}, album_map={"/DCIM/a.jpg": ["Trip"]})

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_import"))
    qtbot.waitUntil(lambda: bool(instance.navigation.albums), timeout=10000)
    album_id = instance.navigation.albums[0][0]
    key = navigation_album_key(album_id)
    instance.navigation.navigation_select(key)
    instance.shell_view_selected(key)
    assert instance.stack.currentWidget() is instance.pages[key]
    wait(worker.worker_submit("close_archive"))
    assert instance.navigation.current_key == LIBRARY_VIEWS[0].key
    assert instance.stack.currentWidget() is instance.pages[LIBRARY_VIEWS[0].key]
    assert instance.stack.currentWidget().body_label.text() == "No archive open."


def test_a_vanished_album_moves_the_page_and_the_scope(shell, qtbot):
    """If the displayed album disappears, the pane, page and model scope move together."""
    pane = NavigationPane()
    qtbot.addWidget(pane)
    seen = []
    pane.navigation_selected.connect(seen.append)
    pane.navigation_set_albums([(3, "Trip", 1)])
    pane.navigation_select("album:3")
    pane.navigation_set_albums([])
    assert pane.current_key == LIBRARY_VIEWS[0].key
    assert seen == [LIBRARY_VIEWS[0].key]


def test_a_failed_device_operation_can_be_recovered(shell, qtbot):
    """ "Disconnected" must not be a dead end: the probe stays available to re-check."""
    devices = {"present": False}

    @contextmanager
    def source_factory(udid):
        if not devices["present"]:
            raise OSError("no device")
        yield FakeDevice({"/DCIM/a.jpg": b"a"})

    parts = shell(source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_device_info"))
    assert instance.phone == "disconnected"
    assert not instance.command_bar.buttons["import"].isEnabled()
    # The probe itself must stay enabled or the phone can never come back.
    assert instance.command_bar.actions_by_key["device"].isEnabled()
    devices["present"] = True
    wait(worker.worker_submit("app_service_device_info"))
    assert instance.phone == "connected"
    assert instance.command_bar.buttons["import"].isEnabled()


def test_an_archive_side_import_failure_does_not_blame_the_phone(shell, qtbot):
    """An import can fail for archive reasons; latching "no phone" would be wrong."""
    from iphone_archive.service.app_service import AppService

    class BrokenImport(AppService):
        def app_service_import(self, progress=None, source=None, **kwargs):
            raise OSError("archive volume is full")

    @contextmanager
    def source_factory(udid):
        yield FakeDevice({"/DCIM/a.jpg": b"a"})

    parts = shell(service_factory=BrokenImport, source_factory=source_factory)
    worker, models, instance, wait, _ = parts
    helper_open(parts, qtbot)
    wait(worker.worker_submit("app_service_device_info"))
    assert instance.phone == "connected"
    wait(worker.worker_submit("app_service_import"))
    assert instance.phone == "connected"
    assert instance.command_bar.buttons["import"].isEnabled()


def test_a_failed_mutation_keeps_its_error_visible(shell, qtbot, tmp_path):
    """The shell's own refresh after a failure must not erase the failure message."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    worker = window.worker
    done = []
    worker.result_ready.connect(lambda reply: done.append(reply.operation))
    failures = []
    worker.failed.connect(lambda reply: failures.append(reply.request_id))
    try:
        root = tmp_path / "window-archive"
        worker.worker_open(root, create=True)
        qtbot.waitUntil(lambda: done.count("app_service_stats") == 1, timeout=10000)
        failing = worker.worker_submit(
            "app_service_move_to_deleted", {"asset_ids": [4242], "file_ids": []}
        )
        qtbot.waitUntil(lambda: failing in failures, timeout=10000)
        # Wait for the refresh the failure itself triggered to finish; it is exactly
        # that housekeeping which used to overwrite the message.
        qtbot.waitUntil(lambda: done.count("app_service_stats") == 2, timeout=10000)
        qtbot.waitUntil(lambda: "app_service_list_albums" in done, timeout=10000)
        assert "Unknown asset" in window.statusBar().currentMessage()
        assert window.status_override is not None
    finally:
        # A failing assertion must still join the worker; a QThread destroyed
        # while running aborts the whole process.
        worker.worker_shutdown()
        assert worker.worker_wait(5000)
