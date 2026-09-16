"""CLI ↔ GUI parity: no capability may exist only in the terminal.

The archive has two front ends over one service layer. The risk this file exists
to remove is silent drift: a service method or a CLI command gains a feature and
the GUI - the front end most users will ever see - never grows a way to reach
it. Nothing in a type checker or a unit test catches that, because both front
ends remain internally consistent while doing different things.

So these tests read the real Typer app, the real ``AppService`` and the real GUI
source, and compare them against the declaration in ``gui/parity.py``. They fail
when an operation has no surface, when a surface names an operation that no
longer exists, and - the part that keeps the declaration from becoming a comment
- when a declared surface never actually submits its operation.

The second half drives a real window offscreen through a whole user journey,
from an empty folder to imported, marked, recycled and restored photos, using
only what the GUI puts on screen.
"""

from __future__ import annotations

import ast
import inspect
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import io  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from iphone_archive import cli as cli_module  # noqa: E402
from iphone_archive.config import config_resolve_paths  # noqa: E402
from iphone_archive.device.fake_device import FakeDevice  # noqa: E402
from iphone_archive.gui import main_window as main_window_module  # noqa: E402
from iphone_archive.gui.confirm import ConfirmDialog  # noqa: E402
from iphone_archive.gui.dialogs import (  # noqa: E402
    MARK_SCOPE_ASSET,
    MARK_SCOPE_COPY,
    MarkScopeDialog,
)
from iphone_archive.gui.main_window import (  # noqa: E402
    DEFERRED_COMMANDS,
    DEFERRED_SELECTION_ACTIONS,
    MainWindow,
)
from iphone_archive.gui.navigation import (  # noqa: E402
    ALBUM_ACTIONS,
    navigation_album_key,
)
from iphone_archive.gui.parity import (  # noqa: E402
    CLI_SURFACES,
    INDIRECT_SURFACES,
    INTERNAL_OPERATIONS,
    parity_gui_surfaces,
    parity_uncovered_operations,
)
from iphone_archive.service.app_service import AppService  # noqa: E402

GUI_PACKAGE = Path(inspect.getfile(main_window_module)).parent


def helper_service_operations():
    """List every public service operation.

    Returns the set of ``app_service_*`` method names on ``AppService``. Reading
    the class rather than a list keeps a new method from being invisible here.
    """
    return {
        name
        for name, value in vars(AppService).items()
        if name.startswith("app_service_") and callable(value)
    }


def helper_cli_commands():
    """Map every Typer command to the service operations it calls.

    Returns a mapping of command path (``marks add``) to the set of service
    operations that command's callback uses. Names come from the Typer app so a
    renamed command is noticed; the calls come from the source, because the
    callbacks are only executed with a real archive.
    """
    calls = helper_cli_calls_by_function()
    commands = {}

    def collect(typer_app, prefix):
        for info in typer_app.registered_commands:
            callback = info.callback
            assert callback is not None
            name = info.name or callback.__name__
            commands[f"{prefix}{name}"] = calls.get(callback.__name__, set())
        for group in typer_app.registered_groups:
            instance = group.typer_instance
            assert instance is not None and group.name is not None
            collect(instance, f"{prefix}{group.name} ")

    collect(cli_module.app, "")
    return commands


def helper_cli_calls_by_function():
    """Read which service operations each CLI callback names.

    Returns a mapping of function name to the ``app_service_*`` attributes it
    uses anywhere in its body, including inside helpers' arguments.
    """
    tree = ast.parse(Path(inspect.getfile(cli_module)).read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        used = {
            child.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute) and child.attr.startswith("app_service_")
        }
        found[node.name] = used
    return found


def helper_gui_invoked_operations():
    """Read which service operations the GUI actually asks the worker to run.

    Returns the set of operation names the GUI source submits or calls. A name
    that only appears as a set element or a dictionary key is deliberately not
    counted: those are the tables that decide when to refresh a view or how to
    title a result, and they describe operations rather than running them.
    """
    invoked = set()
    for path in sorted(GUI_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declared = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Set):
                declared.update(id(element) for element in node.elts)
            if isinstance(node, ast.Dict):
                declared.update(id(key) for key in node.keys if key is not None)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith("app_service_"):
                    invoked.add(node.func.attr)
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("app_service_")
                and node.value != "app_service_"
                and id(node) not in declared
            ):
                invoked.add(node.value)
    return invoked


def test_every_service_operation_has_a_gui_surface():
    """A capability the GUI cannot reach is a capability most users do not have."""
    uncovered = parity_uncovered_operations(helper_service_operations())

    assert uncovered == [], (
        "These service operations have no GUI surface. Add the verb to the GUI "
        "and declare it in gui/parity.py, or explain the indirect route in "
        f"INDIRECT_SURFACES: {uncovered}"
    )


def test_the_parity_declaration_only_names_real_operations():
    """A surface map that outlives the code it describes is worse than none."""
    operations = helper_service_operations()
    declared = set(parity_gui_surfaces()) | set(INDIRECT_SURFACES) | set(INTERNAL_OPERATIONS)

    assert declared - operations == set(), (
        f"gui/parity.py names operations AppService no longer has: {sorted(declared - operations)}"
    )


def test_every_declared_surface_really_submits_its_operation():
    """The declaration has to be checkable, or it is just a comment that rots."""
    invoked = helper_gui_invoked_operations()
    claimed = set(parity_gui_surfaces())

    assert claimed - invoked == set(), (
        "gui/parity.py claims a surface for operations the GUI never submits: "
        f"{sorted(claimed - invoked)}"
    )


def test_the_gui_runs_no_operation_it_never_declared():
    """An undeclared submission means the parity map no longer describes the GUI."""
    invoked = helper_gui_invoked_operations()
    declared = set(parity_gui_surfaces()) | set(INDIRECT_SURFACES) | set(INTERNAL_OPERATIONS)

    assert invoked - declared == set(), (
        f"The GUI submits operations gui/parity.py does not list: {sorted(invoked - declared)}"
    )


def test_every_cli_command_is_mapped_to_a_gui_surface():
    """Parity is claimed command by command, so a new command must claim one too."""
    commands = helper_cli_commands()

    assert set(commands) == set(CLI_SURFACES), (
        "The CLI and the parity map disagree about which commands exist. "
        f"Missing from gui/parity.py: {sorted(set(commands) - set(CLI_SURFACES))}; "
        f"no longer in the CLI: {sorted(set(CLI_SURFACES) - set(commands))}"
    )


def test_no_cli_command_uses_an_operation_the_gui_cannot_reach():
    """The command names mean nothing if the work behind them is CLI-only."""
    reachable = set(parity_gui_surfaces()) | set(INDIRECT_SURFACES) | set(INTERNAL_OPERATIONS)
    gaps = {
        command: sorted(operations - reachable)
        for command, operations in helper_cli_commands().items()
        if operations - reachable
    }

    assert gaps == {}, f"These CLI commands do work the GUI offers no way to do: {gaps}"


def test_no_verb_is_left_deferred_in_the_gui():
    """Phase 2 finished deferring work; a repopulated table would hide a gap."""
    assert DEFERRED_COMMANDS == {}
    assert DEFERRED_SELECTION_ACTIONS == {}


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
    """Build a real window on a fake phone and shut it down afterwards."""
    created = []

    def create(count=4):
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
        created.append(main)
        root = tmp_path / f"archive-{len(created)}"
        monkeypatch.setattr(main, "main_window_choose_directory", lambda title: str(root))
        main.main_window_command("create")
        qtbot.waitUntil(lambda: main.worker.archive_root == root, timeout=15000)
        return main, root

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
    """Run a full import and wait for the grid to show its result.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns None.
    """
    main.main_window_command("import")
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)


def helper_run_command(main, qtbot, key):
    """Press a command-bar verb and wait for its progress dialog to finish.

    main: the window under test.
    qtbot: the pytest-qt bot.
    key: the command key.
    Returns None.
    """
    main.main_window_command(key)
    dialog = main.operation
    assert dialog is not None
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def helper_idle(main, qtbot):
    """Wait until the worker has nothing left in flight.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns None.
    """
    qtbot.waitUntil(lambda: not main.worker.pending, timeout=15000)


def helper_select_rows(main, rows):
    """Select grid rows so the shell captures a selection.

    main: the window under test.
    rows: the model rows to select.
    Returns None.
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


def helper_marks(main, qtbot):
    """Read the staged marks straight from the archive.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns the pending ``MarkSummary`` list. The window's own worker owns the
    connection, so the query is asked of it rather than opening a second one.
    """
    helper_idle(main, qtbot)
    replies = {}
    main.worker.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
    request_id = main.worker.worker_submit("app_service_list_marks")
    qtbot.waitUntil(lambda: request_id in replies, timeout=15000)
    return replies[request_id].value


def helper_album_view(main, qtbot):
    """Switch to the imported album's view and wait for its page.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns the album id being browsed.
    """
    qtbot.waitUntil(lambda: bool(main.shell.navigation.albums), timeout=15000)
    album_id = main.shell.navigation.albums[0][0]
    main.shell.shell_view_selected(navigation_album_key(album_id))
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    return album_id


def helper_dialog(main, kind):
    """Return the single open dialog of a given type.

    main: the window under test.
    kind: the dialog class.
    Returns the dialog instance.
    """
    dialogs = [child for child in main.children() if isinstance(child, kind)]
    assert len(dialogs) == 1, dialogs
    return dialogs[0]


def test_a_photo_can_be_imported_verified_and_browsed_without_the_cli(window, qtbot):
    """The first journey a user makes must work with no terminal at all."""
    main, root = window()

    helper_import(main, qtbot)
    helper_run_command(main, qtbot, "verify")
    helper_idle(main, qtbot)

    paths = config_resolve_paths(root)
    assert main.models.assets.rowCount() == 4
    assert paths.catalog_path.exists()
    assert len(list(paths.photos_dir.rglob("*.png"))) == 4
    assert main.shell.navigation.albums, "the imported album never reached the navigation pane"


def test_an_album_can_be_marked_for_delete_from_the_navigation_pane(window, qtbot):
    """`marks add --album` is a real capability, so the GUI has to offer it too."""
    main, _ = window()
    helper_import(main, qtbot)
    album_id = helper_album_view(main, qtbot)

    main.main_window_album_action(album_id, ALBUM_ACTIONS[0][0])
    marks = helper_marks(main, qtbot)

    assert [(mark.target_type, mark.target_id) for mark in marks] == [("album", album_id)]


def test_marking_one_copy_in_an_album_stages_only_that_copy(window, qtbot):
    """An album view must be able to mark the copy on screen, not every copy."""
    main, _ = window()
    helper_import(main, qtbot)
    helper_album_view(main, qtbot)
    helper_select_rows(main, [0])
    file_id = main.models.assets.rows[0].file_ids[0]

    main.shell.shell_gallery_action("mark")
    dialog = helper_dialog(main, MarkScopeDialog)
    dialog.mark_scope_choose(MARK_SCOPE_COPY)
    marks = helper_marks(main, qtbot)

    assert [(mark.target_type, mark.target_id) for mark in marks] == [("file", file_id)]


def test_the_same_prompt_can_still_mark_every_copy_of_the_asset(window, qtbot):
    """The narrow scope is the default, not the only choice the CLI offers."""
    main, _ = window()
    helper_import(main, qtbot)
    helper_album_view(main, qtbot)
    helper_select_rows(main, [0])
    asset_id = main.models.assets.rows[0].asset_id

    main.shell.shell_gallery_action("mark")
    dialog = helper_dialog(main, MarkScopeDialog)
    dialog.mark_scope_choose(MARK_SCOPE_ASSET)
    marks = helper_marks(main, qtbot)

    assert [(mark.target_type, mark.target_id) for mark in marks] == [("asset", asset_id)]


def test_nothing_is_staged_when_the_scope_prompt_is_dismissed(window, qtbot):
    """Closing a prompt is an answer, and the answer is "do nothing"."""
    main, _ = window()
    helper_import(main, qtbot)
    helper_album_view(main, qtbot)
    helper_select_rows(main, [0])

    main.shell.shell_gallery_action("mark")
    helper_dialog(main, MarkScopeDialog).reject()

    assert helper_marks(main, qtbot) == []


def helper_finish(main, qtbot):
    """Wait for the progress dialog a confirmation started.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns None.
    """
    qtbot.waitUntil(lambda: main.operation is not None, timeout=5000)
    dialog = main.operation
    qtbot.waitUntil(lambda: not dialog.running, timeout=20000)


def test_a_whole_deletion_journey_runs_from_the_gui_alone(window, qtbot):
    """Import, mark, commit and restore is the journey the CLI documents; so must the GUI."""
    main, root = window(count=2)
    paths = config_resolve_paths(root)
    helper_import(main, qtbot)
    before = sorted(path.name for path in paths.photos_dir.rglob("*.png"))

    helper_select_rows(main, [0])
    main.shell.shell_gallery_action("mark")
    qtbot.waitUntil(lambda: main.shell.counts.get("marked", 0) > 0, timeout=15000)
    # Staging a mark is a note about the future: the files must still be there.
    assert sorted(path.name for path in paths.photos_dir.rglob("*.png")) == before

    main.shell.shell_show_view("marked")
    qtbot.waitUntil(lambda: bool(main.shell.reviews["marked"].review_list.rows), timeout=15000)
    main.main_window_review_action("marked", "commit-recycle")
    helper_dialog(main, ConfirmDialog).action_button.click()
    helper_finish(main, qtbot)
    assert list(paths.deleted_dir.rglob("*.png"))

    main.shell.shell_show_view("recycled")
    qtbot.waitUntil(lambda: main.models.assets.rowCount() > 0, timeout=15000)
    helper_select_rows(main, [0])
    main.shell.shell_gallery_action("restore")
    helper_finish(main, qtbot)

    assert list(paths.deleted_dir.rglob("*.png")) == []
    assert sorted(path.name for path in paths.photos_dir.rglob("*.png")) == before
