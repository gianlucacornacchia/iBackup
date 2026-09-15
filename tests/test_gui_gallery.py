"""Offscreen gallery: tile painting, paging, selection scope, actions and the viewer."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QStyleOptionViewItem  # noqa: E402

from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui.gallery import (  # noqa: E402
    AssetGallery,
    SelectionBar,
    TileDelegate,
    gallery_elide,
    gallery_format_size,
)
from iphone_archive.gui.models import ArchiveModels, AssetRole, AssetScope  # noqa: E402
from iphone_archive.gui.previews import PreviewLoader, PreviewState  # noqa: E402
from iphone_archive.gui.shell import VIEW_ACTIONS, ArchiveShell  # noqa: E402
from iphone_archive.gui.viewer import ViewerDialog, viewer_metadata_lines  # noqa: E402
from iphone_archive.gui.worker import WorkerController  # noqa: E402


def helper_photo_bytes(number, size=(120, 90)):
    """Encode a small real PNG whose content is unique to this asset.

    number: the asset's index, mixed into the pixels.
    size: the image dimensions.
    Returns the encoded PNG bytes. Identical bytes would be deduplicated into a
    single archived asset, which is exactly what the archive is supposed to do.
    """
    import io

    image = Image.new("RGB", size, (number * 37 % 256, number * 11 % 256, 90))
    image.putpixel((0, 0), (number % 256, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def gallery(qapp, qtbot, tmp_path):
    """Build a shell with a real worker, fake phone and gallery; shut it all down after."""
    created = []

    def create(count=5, page_size=128):
        files = {
            f"/DCIM/IMG_{number:04d}.png": helper_photo_bytes(number) for number in range(count)
        }
        albums = {path: ["Trip"] for index, path in enumerate(files) if index % 2 == 0}

        @contextmanager
        def source_factory(udid):
            yield FakeDevice(files, album_map=albums)

        worker = WorkerController(source_factory=source_factory)
        models = ArchiveModels(worker, page_size=page_size)
        previews = PreviewLoader(size=64, cache_entries=16)
        shell = ArchiveShell(worker, models, previews)
        # MainWindow binds the loader to the open archive; the bare shell used
        # here has no window, so the test does it explicitly.
        worker.result_ready.connect(
            lambda reply: previews.previews_set_archive(worker.archive_root)
        )
        qtbot.addWidget(shell)
        shell.resize(900, 700)
        shell.show()
        replies, failures = {}, {}
        worker.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
        worker.failed.connect(lambda error: failures.update({error.request_id: error}))
        created.append((worker, models, previews, shell))

        def wait(request_id):
            qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=15000)
            assert request_id not in failures, failures.get(request_id)
            return replies[request_id]

        root = tmp_path / f"archive-{len(created)}"
        wait(worker.worker_open(root, create=True))
        wait(worker.worker_submit("app_service_import"))
        qtbot.waitUntil(lambda: shell.counts.get("assets") == count, timeout=15000)
        qtbot.waitUntil(lambda: models.assets.rowCount() > 0, timeout=15000)
        return worker, models, previews, shell, wait

    yield create
    for worker, models, previews, shell in created:
        worker.worker_shutdown()
        assert worker.worker_wait(5000)
        previews.previews_shutdown()
        qapp.processEvents()
        shell.deleteLater()
        previews.deleteLater()
        models.deleteLater()
        worker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_size_formatting_matches_the_sketch():
    """The selection bar's size text must be short and human readable."""
    assert gallery_format_size(0) == "0 B"
    assert gallery_format_size(900) == "900 B"
    assert gallery_format_size(1024) == "1.0 KB"
    assert gallery_format_size(15_300_000) == "14.6 MB"
    with pytest.raises(ValueError):
        gallery_format_size(-1)


def test_captions_are_elided_to_the_tile_width(qapp):
    """A long file name must be shortened rather than painted over its neighbour."""
    from PySide6.QtGui import QFontMetrics

    metrics = QFontMetrics(qapp.font())
    long_name = "IMG_a_very_long_original_file_name_indeed.HEIC"
    assert gallery_elide(long_name, metrics, 60) != long_name
    assert gallery_elide("IMG.HEIC", metrics, 400) == "IMG.HEIC"


def test_the_grid_fills_itself_without_being_scrolled(gallery, qtbot):
    """One page can be shorter than the viewport, so the grid must keep paging."""
    worker, models, previews, shell, wait = gallery(count=6, page_size=2)
    qtbot.waitUntil(lambda: models.assets.rowCount() == 6, timeout=15000)
    assert shell.gallery.stack.currentWidget() is shell.gallery.grid


def test_tiles_are_painted_from_the_preview_loader(gallery, qtbot):
    """Painting must go through the loader and never touch the disk on the GUI thread."""
    worker, models, previews, shell, wait = gallery(count=2)
    delegate = TileDelegate(previews)
    index = models.assets.index(0)
    sha256, entry = delegate.tile_entry(index)
    assert sha256 == index.data(int(AssetRole.SHA256))
    # The grid is on screen, so this render may already have finished; what
    # matters is that asking never blocks and never fails.
    assert entry is not None and entry.state is not PreviewState.FAILED
    qtbot.waitUntil(
        lambda: delegate.tile_entry(index)[1].state is PreviewState.READY, timeout=15000
    )

    pixmap = QPixmap(140, 160)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 140, 160)
    option.palette = shell.palette()
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    assert not pixmap.toImage().isNull()


def test_a_tile_without_a_stored_copy_is_not_previewed(gallery):
    """A row with no paths must paint a stand-in rather than raise while scrolling."""
    worker, models, previews, shell, wait = gallery(count=1)
    row = models.assets.rows[0]
    models.assets.rows[0] = type(row)(**{**row.__dict__, "paths": [], "file_ids": []})
    delegate = TileDelegate(previews)
    sha256, entry = delegate.tile_entry(models.assets.index(0))
    assert entry is None


def test_selection_carries_exact_copy_ids(gallery):
    """A batch action must act on the copies the user saw, not on row numbers."""
    worker, models, previews, shell, wait = gallery(count=4)
    grid = shell.gallery.grid
    grid.grid_select_all()
    selection = grid.grid_selection()
    assert len(selection.asset_ids) == models.assets.rowCount()
    assert selection.file_ids
    assert selection.archive_root == worker.archive_root
    assert selection.scope == models.assets.scope
    parameters = models.assets.asset_model_selection_parameters(selection)
    assert parameters["asset_ids"] == list(selection.asset_ids)


def test_an_empty_selection_is_refused_rather_than_guessed(gallery):
    """Acting on nothing must fail loudly instead of acting on everything."""
    worker, models, previews, shell, wait = gallery(count=2)
    shell.gallery.grid.grid_clear_selection()
    with pytest.raises(ValueError):
        shell.gallery.grid.grid_selection()


def test_the_selection_bar_appears_only_with_a_selection(gallery):
    """The bar slides in for a selection and hides again when it is cleared."""
    worker, models, previews, shell, wait = gallery(count=3)
    bar = shell.gallery.selection_bar
    assert not bar.isVisibleTo(shell.gallery)
    shell.gallery.grid.grid_select_all()
    assert bar.isVisibleTo(shell.gallery)
    assert bar.summary_label.text().startswith(f"{models.assets.rowCount()} selected - ")
    shell.gallery.grid.grid_clear_selection()
    assert not bar.isVisibleTo(shell.gallery)


def test_each_view_offers_only_the_actions_that_make_sense(gallery, qtbot):
    """Restore and purge belong to the recycle bin; recycling something recycled does not."""
    worker, models, previews, shell, wait = gallery(count=2)
    assert shell.shell_view_actions("all") == VIEW_ACTIONS["all"]
    shell.shell_show_view("recycled")
    assert shell.gallery.actions_available == VIEW_ACTIONS["recycled"]
    assert shell.gallery.selection_bar.buttons["restore"].isVisibleTo(shell.gallery.selection_bar)
    assert not shell.gallery.selection_bar.buttons["delete"].isVisibleTo(
        shell.gallery.selection_bar
    )


def test_report_views_show_their_own_listing_not_the_photo_grid(gallery):
    """Views the asset model cannot scope must not show another view's photos."""
    worker, models, previews, shell, wait = gallery(count=2)
    shell.shell_show_view("marked")
    page = shell.pages["marked"]
    # The marks queue is a list of staged decisions, not a grid of photos: the
    # asset model cannot scope it, so it must never host the shared gallery.
    assert page.body_widget is shell.reviews["marked"]
    assert page.body_widget is not shell.gallery
    assert shell.shell_view_actions("marked") is None


def test_the_gallery_moves_between_pages_instead_of_being_duplicated(gallery, qtbot):
    """One asset model means one gallery, re-hosted by whichever page is shown."""
    worker, models, previews, shell, wait = gallery(count=2)
    first = shell.pages["all"]
    assert first.body_widget is shell.gallery
    shell.shell_show_view("unsorted")
    assert first.body_widget is None
    assert shell.pages["unsorted"].body_widget is shell.gallery
    assert shell.gallery.parent() is shell.pages["unsorted"]


def test_a_selection_action_reports_the_exact_copies(gallery, qtbot):
    """The shell captures the selection immediately, on the GUI thread."""
    worker, models, previews, shell, wait = gallery(count=3)
    seen = []
    shell.shell_selection_action.connect(lambda key, selection: seen.append((key, selection)))
    shell.gallery.grid.grid_select_all()
    shell.gallery.selection_bar.selection_action.emit("delete")
    assert len(seen) == 1
    key, selection = seen[0]
    assert key == "delete"
    assert len(selection.asset_ids) == models.assets.rowCount()


def test_a_selection_captured_before_a_reset_is_refused_afterwards(gallery, qtbot):
    """The exact-copy guard, not the empty selection, is what must reject stale work.

    Qt clears the view selection on a model reset, so asking the grid again
    would raise "nothing selected" and prove nothing. This keeps the captured
    AssetSelection and checks the model refuses to build parameters from it.
    """
    worker, models, previews, shell, wait = gallery(count=3)
    shell.gallery.grid.grid_select_all()
    selection = shell.gallery.grid.grid_selection()
    assert models.assets.asset_model_selection_parameters(selection)["asset_ids"]
    models.assets.model_reset(active=True)
    assert selection.revision != models.assets.revision
    with pytest.raises(ValueError):
        models.assets.asset_model_selection_parameters(selection)


def test_a_stale_selection_is_reported_not_submitted(gallery, qtbot):
    """A selection the model rejects must reach the status bar, not the worker."""
    worker, models, previews, shell, wait = gallery(count=3)
    messages = []
    shell.shell_status_changed.connect(messages.append)
    seen = []
    shell.shell_selection_action.connect(lambda key, selection: seen.append(key))
    shell.gallery.grid.grid_select_all()

    def refuse(indexes):
        raise ValueError("Selection is stale; select again in the current archive view")

    models.assets.asset_model_selection = refuse
    shell.shell_gallery_action("delete")
    assert not seen
    assert any("no longer valid" in message for message in messages)


def test_open_is_handled_locally_rather_than_as_a_batch_action(gallery):
    """ "Open" shows the viewer; it is not an archive mutation."""
    worker, models, previews, shell, wait = gallery(count=2)
    batch, opened = [], []
    shell.gallery.gallery_action.connect(batch.append)
    shell.gallery.gallery_open_requested.connect(opened.append)
    shell.gallery.grid.grid_select_all()
    shell.gallery.gallery_selection_action("open")
    assert not batch
    assert opened == [0]


def test_scrolling_cancels_renders_for_tiles_left_behind(gallery, qtbot):
    """Fast scrolling must tell the loader which tiles are still worth rendering."""
    worker, models, previews, shell, wait = gallery(count=6)
    qtbot.waitUntil(lambda: models.assets.rowCount() == 6, timeout=15000)
    asked = []
    previews.previews_cancel_stale = lambda keep: asked.append(set(keep)) or 0
    grid = shell.gallery.grid
    grid.grid_scrolled()
    assert asked == [grid.grid_visible_hashes()]
    assert asked[0] <= {models.assets.index(row).data(int(AssetRole.SHA256)) for row in range(6)}


def test_the_grid_explains_an_empty_view(gallery, qtbot):
    """An empty scope must say so rather than showing a blank rectangle."""
    worker, models, previews, shell, wait = gallery(count=2)
    shell.shell_show_view("recycled")
    qtbot.waitUntil(
        lambda: shell.gallery.stack.currentWidget() is shell.gallery.message_label, timeout=15000
    )
    assert "Nothing to show" in shell.gallery.message_label.text()


def test_a_failed_later_page_is_reported_not_swallowed(gallery, qtbot):
    """Rows already on screen stay, but the failure must still reach the user."""
    worker, models, previews, shell, wait = gallery(count=2)
    messages = []
    shell.shell_status_changed.connect(messages.append)
    models.assets.model_error("database is locked")
    assert shell.gallery.stack.currentWidget() is shell.gallery.grid
    assert any("database is locked" in message for message in messages)


def test_an_empty_view_that_fails_explains_itself_in_place(gallery, qtbot):
    """With no rows to show, the grid area itself must carry the error."""
    worker, models, previews, shell, wait = gallery(count=2)
    shell.shell_show_view("recycled")
    qtbot.waitUntil(lambda: models.assets.rowCount() == 0, timeout=15000)
    models.assets.model_error("database is locked")
    assert shell.gallery.stack.currentWidget() is shell.gallery.message_label
    assert "database is locked" in shell.gallery.message_label.text()


def test_the_selection_bar_refuses_unknown_actions():
    """A typo in a view's action list must fail a test, not silently show nothing."""
    bar = SelectionBar()
    with pytest.raises(ValueError):
        bar.selection_bar_update(1, 10, ("delete", "explode"))
    with pytest.raises(ValueError):
        bar.selection_bar_update(-1, 10, ("delete",))


def test_the_viewer_shows_the_catalog_facts(gallery, qtbot):
    """The viewer is a preview plus the facts, never an editor."""
    worker, models, previews, shell, wait = gallery(count=2)
    viewer_previews = PreviewLoader(size=128)
    viewer_previews.previews_set_archive(worker.archive_root)
    dialog = ViewerDialog(models.assets, viewer_previews, 0)
    qtbot.addWidget(dialog)
    try:
        row = models.assets.rows[0]
        assert dialog.title_label.text() == row.original_name
        facts = " ".join(label.text() for label in dialog.fact_labels)
        assert row.sha256 in facts
        assert row.paths[0] in facts
        qtbot.waitUntil(lambda: dialog.pixmap is not None, timeout=15000)
    finally:
        dialog.close()
        viewer_previews.previews_shutdown()


def test_the_viewer_walks_the_paged_model(gallery, qtbot):
    """Next must pull another page rather than pretending the library ends there."""
    worker, models, previews, shell, wait = gallery(count=4, page_size=2)
    qtbot.waitUntil(lambda: models.assets.rowCount() == 4, timeout=15000)
    viewer_previews = PreviewLoader(size=128)
    viewer_previews.previews_set_archive(worker.archive_root)
    dialog = ViewerDialog(models.assets, viewer_previews, 0)
    qtbot.addWidget(dialog)
    try:
        assert not dialog.previous_button.isEnabled()
        dialog.viewer_next()
        assert dialog.row == 1
        dialog.viewer_previous()
        assert dialog.row == 0
    finally:
        dialog.close()
        viewer_previews.previews_shutdown()


def test_the_viewer_closes_when_its_rows_are_replaced(gallery, qtbot):
    """Row 12 means a different asset after a reset, so the dialog must not linger."""
    worker, models, previews, shell, wait = gallery(count=3)
    viewer_previews = PreviewLoader(size=128)
    viewer_previews.previews_set_archive(worker.archive_root)
    dialog = ViewerDialog(models.assets, viewer_previews, 0)
    qtbot.addWidget(dialog)
    dialog.show()
    try:
        assert dialog.isVisible()
        models.assets.asset_model_set_scope(AssetScope("recycled"))
        assert not dialog.isVisible()
    finally:
        dialog.close()
        viewer_previews.previews_shutdown()


def test_viewer_metadata_survives_missing_fields():
    """A partially populated row must still render readable facts."""
    lines = viewer_metadata_lines({"sha256": "abc", "size": 2048, "paths": ("Photos/Trip/a.png",)})
    assert "2.0 KB" in lines[0]
    assert "unknown date" in lines[0]
    assert "on phone: no" in lines[1]
    assert lines[-1] == "Photos/Trip/a.png"


def test_the_context_menu_acts_on_the_clicked_tile(gallery, qtbot):
    """Right-clicking an unselected tile must select it, not act on something else."""
    worker, models, previews, shell, wait = gallery(count=3)
    grid = shell.gallery.grid
    grid.grid_clear_selection()
    index = models.assets.index(1)
    position = grid.visualRect(index).center()
    shell.gallery.gallery_set_actions(("open",))
    menu = shell.gallery.gallery_build_menu(position)
    assert menu is not None
    assert [action.text() for action in menu.actions()] == ["Open"]
    assert grid.grid_selected_rows() == [1]


def test_a_new_archive_drops_the_previous_selection(gallery, qtbot):
    """A selection from a closed archive must never survive into the next one."""
    worker, models, previews, shell, wait = gallery(count=3)
    shell.gallery.grid.grid_select_all()
    assert shell.gallery.grid.grid_selected_rows()
    wait(worker.worker_submit("close_archive"))
    qtbot.waitUntil(lambda: not shell.gallery.grid.grid_selected_rows(), timeout=15000)
    assert not shell.gallery.selection_bar.isVisible()


def test_a_deferred_page_pump_cannot_outlive_its_grid(gallery, qtbot):
    """A bare singleShot would call into a destroyed model and worker after teardown."""
    worker, models, previews, shell, wait = gallery(count=2)
    grid = shell.gallery.grid
    assert grid.pump_timer.parent() is grid


def test_scrolling_does_not_erase_an_error_message(gallery, qtbot):
    """Automatic page reads succeed; they must not clear the error the user needs to see."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        assert window.main_window_is_automatic(-1) is False
        window.models.assets.model_remember_page(4242)
        assert window.main_window_is_automatic(4242) is True
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)


def test_grid_rows_in_view_does_not_scan_the_whole_model(gallery, qtbot):
    """Scroll cost must follow the visible tiles, not the number of loaded rows.

    Scanning every loaded row makes each scroll event more expensive as the
    library grows, which defeats the paged model. The walk therefore starts from
    a probed anchor and stops when it leaves the viewport.
    """
    worker, models, previews, shell, wait = gallery(count=24)
    qtbot.waitUntil(lambda: models.assets.rowCount() == 24, timeout=30000)
    shell.resize(360, 240)
    qtbot.waitUntil(lambda: shell.gallery.grid.viewport().height() > 60, timeout=5000)
    qtbot.wait(50)

    visited = []
    original = models.assets.index
    models.assets.index = lambda row, *args, **kwargs: (
        visited.append(row) or original(row, *args, **kwargs)
    )
    try:
        rows = shell.gallery.grid.grid_rows_in_view()
    finally:
        models.assets.index = original

    assert rows == sorted(rows)
    assert set(rows) <= set(range(24))
    assert rows, "the viewport should show at least one tile"
    assert len(set(visited)) < 24, f"scanned {len(set(visited))} of 24 rows"


def test_visible_hashes_come_from_the_visible_rows(gallery, qtbot):
    """The loader is told exactly which tiles are still worth rendering."""
    worker, models, previews, shell, wait = gallery(count=6)
    qtbot.waitUntil(lambda: models.assets.rowCount() == 6, timeout=15000)
    grid = shell.gallery.grid
    expected = {
        models.assets.index(row).data(int(AssetRole.SHA256)) for row in grid.grid_rows_in_view()
    }
    assert grid.grid_visible_hashes() == expected


def test_the_gallery_is_reachable_from_the_window(qtbot):
    """The window must actually show the gallery, not the old placeholder page."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        assert isinstance(window.shell.gallery, AssetGallery)
        assert window.shell.pages["all"].body_widget is window.shell.gallery
        assert window.viewer_previews is not window.previews
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)


def test_the_window_refuses_a_viewer_for_a_row_that_is_gone(qtbot):
    """Opening row 0 of an empty view must explain itself, not show a blank dialog."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        window.main_window_open_viewer(0)
        assert window.viewer is None
        assert "no longer in this view" in window.statusBar().currentMessage()
    finally:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)


def test_the_window_opens_one_viewer_at_a_time(gallery, qtbot, tmp_path):
    """Activating another tile re-targets the open viewer instead of stacking windows."""
    worker, models, previews, shell, wait = gallery(count=3)
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        window.worker.worker_shutdown()
        assert window.worker.worker_wait(5000)
        # Drive the window's viewer against the fixture's populated model.
        window.models = models
        window.shell.models = models
        window.main_window_open_viewer(0)
        first = window.viewer
        assert first is not None and first.isVisible()
        assert first.row == 0
        window.main_window_open_viewer(2)
        assert window.viewer is first
        assert first.row == 2
        destroyed = []
        first.destroyed.connect(lambda *_: destroyed.append(True))
        first.close()
        qtbot.waitUntil(lambda: window.viewer is None, timeout=5000)
        # A closed viewer must actually be destroyed: it retains a full-size
        # pixmap and stays connected to the shared model and preview loader.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert destroyed
    finally:
        if window.viewer is not None:
            window.viewer.close()
        window.models = window.shell.models = ArchiveModels(window.worker, window)


def test_a_view_without_actions_shows_no_context_menu(gallery, qtbot):
    """An empty menu must not be popped up as a stray empty rectangle."""
    worker, models, previews, shell, wait = gallery(count=2)
    shell.gallery.grid.grid_select_all()
    shell.gallery.gallery_set_actions(())
    assert shell.gallery.gallery_build_menu(QPoint(0, 0)) is None
