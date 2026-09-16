"""Main window shell.

Holds the window chrome, the page stack and the routing between what the user
asks for and what the service worker runs.

Every command reaches the worker through one of two paths. Long operations get
the sketch's progress dialog, which can be cancelled where cancellation really
exists and hidden where it does not. Short reads run quietly and report a single
summary line, because a modal dialog that appears and vanishes tells the user
less than the status bar does.

Destructive verbs go through one more gate. Nothing that deletes anything is
submitted from a button press: the press builds a ``ConfirmSpec`` describing
exactly what would happen, the confirmation dialog demands the typed word for
anything permanent, and only its approval reaches the worker. Reclamation adds a
stage before that - it always runs a non-destructive dry run first, and only its
report can open the dialog that leads to a real phone-side deletion.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMainWindow, QStatusBar, QWidget

from .. import __version__
from ..browse.thumbnails import DEFAULT_THUMBNAIL_SIZE
from ..config import config_is_archive, config_resolve_paths
from ..core.reclaim import ReclaimResult
from ..logging_setup import logging_setup_configure
from ..settings import Settings, settings_load
from .commands import COMMANDS_BY_KEY
from .confirm import (
    ConfirmSpec,
    confirm_marks_spec,
    confirm_purge_spec,
    confirm_reclaim_spec,
    confirm_recycle_spec,
    confirm_show,
)
from .dialogs import (
    MARK_SCOPE_ALBUM,
    MARK_SCOPE_COPY,
    MarkScopeDialog,
    MoveToAlbumDialog,
    ReportDialog,
    dialogs_dedup_lines,
)
from .models import ArchiveModels, AssetSelection
from .operations import OperationDialog, operations_summary, operations_title
from .previews import MAX_PREVIEW_SIZE, MIN_PREVIEW_SIZE, PreviewLoader
from .reclaim import ReclaimDialog, reclaim_selected_bytes
from .settings_dialog import SettingsDialog
from .shell import ArchiveShell
from .theme import ThemeController
from .viewer import VIEWER_PREVIEW_SIZE, ViewerDialog
from .worker import WorkerController, WorkerFailure, WorkerResult

LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "iPhone Archive"
WINDOW_DEFAULT_SIZE = (1180, 760)
WINDOW_MINIMUM_SIZE = (900, 560)

# Commands that take long enough, or touch the phone slowly enough, to deserve
# the progress dialog. The only device presence probe enumerates the whole
# library, so "Check phone" belongs here too.
# "reclaim" runs its dry run here; only that preview can lead to a deletion.
DIALOG_COMMANDS = frozenset({"import", "verify", "scan", "device", "reclaim"})
# Short reads that report one line. A modal dialog for a counter refresh would
# flash open and shut without telling the user anything.
QUIET_COMMANDS = frozenset({"dedup", "stats", "clear-thumbnails", "close"})
# Verbs whose safety gating belongs to a later step. Every verb the command bar
# and the navigation pane offer is now implemented, so this is empty; the
# mechanism stays because a new verb must announce itself rather than appearing
# to work while doing nothing.
DEFERRED_COMMANDS: dict[str, str] = {}
OPERATION_BUSY = "Another operation is already running. Wait for it, or cancel it first."
DEFERRED_SELECTION_ACTIONS: dict[str, str] = {}
NO_SELECTION = "Select at least one photo or video first."
# Unmarking has no bulk service call, and the worker's request queue is bounded,
# so a large selection is refused with a usable alternative rather than being
# turned into hundreds of queued requests that would overflow it.
MAX_BULK_REQUESTS = 16


class MainWindow(QMainWindow):
    """The application's only top-level window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the window shell and its empty page stack.

        parent: optional parent widget, normally None.
        """
        super().__init__(parent)
        self.setObjectName("ArchiveWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)
        self.worker = WorkerController(self)
        self.close_pending = False
        # An error must not be wiped by the next idle status line the shell emits.
        self.status_override: str | None = None
        self.worker.stopped.connect(self.main_window_worker_stopped)
        self.worker.failed.connect(self.main_window_worker_failed)
        self.models = ArchiveModels(self.worker, self)
        self.preferences = main_window_preferences()
        self.previews = PreviewLoader(self, size=main_window_preview_size(self.preferences))
        self.worker.result_ready.connect(self.main_window_sync_previews)
        self.worker.failed.connect(self.main_window_sync_previews)
        self.worker.cancelled.connect(self.main_window_sync_previews)
        self.worker.stopped.connect(self.main_window_sync_previews)

        # The viewer renders at a much larger bounding box than a tile. Sharing
        # the grid's loader would either evict every tile on each open or force
        # the viewer to enlarge a 256px thumbnail, so it gets its own bounded
        # cache instead.
        self.viewer_previews = PreviewLoader(self, size=VIEWER_PREVIEW_SIZE, cache_entries=8)
        self.viewer: ViewerDialog | None = None
        self.viewer_token = 0
        # One progress dialog at a time. The worker serialises work anyway, so a
        # second dialog would only report a request that is queued behind the
        # first while appearing to run.
        self.operation: OperationDialog | None = None
        # Short reads report one line; the entry is removed by the reply, and
        # every accepted request has exactly one terminal outcome.
        self.quiet_requests: dict[int, str] = {}
        # Preference reads and writes are routed separately: they are the only
        # operations that work with no archive open, and their replies drive the
        # settings dialog rather than the status bar alone.
        self.settings_requests: dict[int, str] = {}
        self.settings_dialog: SettingsDialog | None = None
        self.settings_file: Path | None = None

        self.shell = ArchiveShell(self.worker, self.models, self.previews, self)
        self.shell.shell_status_changed.connect(self.main_window_show_state)
        self.shell.shell_command.connect(self.main_window_command)
        self.shell.shell_selection_action.connect(self.main_window_selection_action)
        self.shell.shell_review_action.connect(self.main_window_review_action)
        self.shell.shell_album_action.connect(self.main_window_album_action)
        self.shell.shell_open_asset.connect(self.main_window_open_viewer)
        self.shell.shell_set_deleted_default(self.preferences.default_deleted_action)
        self.worker.result_ready.connect(self.main_window_quiet_reply)
        self.worker.failed.connect(self.main_window_quiet_reply)
        self.worker.cancelled.connect(self.main_window_quiet_reply)
        self.worker.result_ready.connect(self.main_window_settings_reply)
        self.worker.failed.connect(self.main_window_settings_reply)
        self.worker.cancelled.connect(self.main_window_settings_reply)
        # Connected after the shell so its housekeeping reads can be recognised.
        self.worker.result_ready.connect(self.main_window_clear_error)
        self.setCentralWidget(self.shell)

        status_bar = QStatusBar()
        status_bar.setObjectName("ArchiveStatusBar")
        status_bar.showMessage(f"iPhone Archive {__version__} - no archive open")
        self.setStatusBar(status_bar)
        self.shell.shell_apply_state()

    def main_window_show_status(self, message: str) -> None:
        """Show a message in the status bar, replacing any error currently held.

        message: the text to display.
        Returns None.
        """
        self.status_override = None
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message)

    @Slot(str)
    def main_window_show_state(self, message: str) -> None:
        """Show the shell's idle status unless an error is still being reported.

        message: the shell's current state line.
        Returns None. Errors persist until the next successful reply or command,
        so a routine state refresh cannot silently hide a failure.
        """
        status_bar = self.statusBar()
        if status_bar is not None and self.status_override is None:
            status_bar.showMessage(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the window/event loop alive until worker-owned resources have been released."""
        self.previews.previews_cancel_all()
        self.viewer_previews.previews_cancel_all()
        if self.settings_dialog is not None:
            dialog = self.settings_dialog
            self.settings_dialog = None
            dialog.close()
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None
        if self.operation is not None:
            # The worker shutdown below cancels the request this dialog is
            # watching, so it has nothing left to report.
            operation = self.operation
            self.operation = None
            operation.operation_force_close()
        if self.worker.service_thread.isRunning():
            event.ignore()
            self.close_pending = True
            self.main_window_show_status("Stopping archive work safely...")
            self.worker.worker_shutdown()
        else:
            self.worker.worker_shutdown()
            self.previews.previews_shutdown()
            self.viewer_previews.previews_shutdown()
            event.accept()

    @Slot()
    def main_window_worker_stopped(self) -> None:
        """Complete a deferred window close after the worker has been joined."""
        if self.close_pending:
            self.close_pending = False
            self.close()

    def main_window_sync_previews(self, reply: object = None) -> None:
        """Rebind previews when the open archive changes; identical hashes differ per archive."""
        self.previews.previews_set_archive(self.worker.archive_root)
        self.viewer_previews.previews_set_archive(self.worker.archive_root)

    @Slot(int)
    def main_window_open_viewer(self, row: int) -> None:
        """Open the single-asset viewer on a grid row.

        row: the asset model row that was activated.
        Returns None. Only one viewer exists at a time, so activating another
        tile re-targets the open dialog instead of stacking windows.
        """
        if not self.models.assets.index(row).isValid():
            self.main_window_show_status("That asset is no longer in this view.")
            return
        if self.viewer is not None and self.viewer.isVisible():
            self.viewer.viewer_show_row(row)
            self.viewer.raise_()
            return
        viewer = ViewerDialog(self.models.assets, self.viewer_previews, row, self)
        viewer.viewer_set_actions(self.main_window_viewer_actions())
        viewer.viewer_action.connect(self.main_window_viewer_action)
        # Destruction, not `finished`: the dialog deletes itself on close and
        # not every close path emits `finished`. The token is bound now, so a
        # viewer destroyed after being replaced cannot cancel the renders of the
        # one the user is actually looking at.
        self.viewer_token += 1
        viewer.destroyed.connect(partial(self.main_window_viewer_closed, self.viewer_token))
        self.viewer = viewer
        viewer.show()

    def main_window_viewer_actions(self) -> tuple[str, ...]:
        """Return the per-asset actions the current view supports.

        Returns the action keys, without the gallery's own "open" verb.
        """
        actions = self.shell.shell_view_actions(self.shell.navigation.current_key) or ()
        return tuple(key for key in actions if key != "open")

    def main_window_viewer_closed(self, token: int, obj: object = None) -> None:
        """Forget the viewer and stop rendering large previews for it.

        token: identifies the viewer that is dying.
        obj: the dying QObject, which must not be touched.
        Returns None. A viewer destroyed after being replaced must not cancel
        the renders of its successor, which would blank the visible image.
        """
        if token != self.viewer_token:
            return
        self.viewer = None
        self.viewer_previews.previews_cancel_all()

    @Slot(str, int)
    def main_window_viewer_action(self, key: str, row: int) -> None:
        """Apply a viewer action to the asset on screen.

        key: the action key requested.
        row: the model row the viewer is showing.
        Returns None. The row is selected in the grid first so the action runs
        through exactly the same exact-copy selection path as a batch action.
        """
        grid = self.shell.gallery.grid
        index = self.models.assets.index(row)
        if not index.isValid():
            self.main_window_show_status("That asset is no longer in this view.")
            return
        grid.grid_clear_selection()
        grid.setCurrentIndex(index)
        self.shell.shell_gallery_action(key)

    @Slot(str, object)
    def main_window_selection_action(self, key: str, selection: object) -> None:
        """Run a batch action on the copies the user had selected.

        key: the action key requested.
        selection: the captured ``AssetSelection``.
        Returns None. Destructive verbs are deliberately still refused: they
        need the typed confirmation of step 9, and doing them quietly here would
        be exactly the behaviour this archive is designed to prevent.
        """
        deferred = DEFERRED_SELECTION_ACTIONS.get(key)
        if deferred is not None:
            self.main_window_show_status(deferred)
            return
        if key == "move":
            self.main_window_move_selection(selection)
            return
        if key == "mark":
            self.main_window_mark_selection(selection)
            return
        if key in {"delete", "restore", "purge"}:
            self.main_window_confirm_selection(key, selection)
            return
        self.main_window_show_status(f"{key} is not a batch action.")

    def main_window_mark_selection(self, selection: object) -> None:
        """Stage deletion marks for the selected assets.

        selection: the captured ``AssetSelection``.
        Returns None. Marking deletes nothing, so it needs no confirmation. A
        single copy inside an album is the one case the service can mark either
        way, so it is the one case the user is asked about; a multi-selection
        has no bulk copy-scoped mark API and says plainly that every copy of
        those assets is being staged.
        """
        if not isinstance(selection, AssetSelection) or not selection.asset_ids:
            self.main_window_show_status(NO_SELECTION)
            return
        try:
            parameters = self.models.assets.asset_model_selection_parameters(selection)
        except ValueError as error:
            self.main_window_refuse_selection("Marking", error)
            return
        file_ids = parameters["file_ids"]
        if (
            selection.scope.kind == "album"
            and len(selection.asset_ids) == 1
            and isinstance(file_ids, list)
            and len(file_ids) == 1
        ):
            self.main_window_ask_mark_scope(selection)
            return
        request_id = self.main_window_start_quiet(
            "app_service_mark_many", {"asset_ids": parameters["asset_ids"]}
        )
        if request_id is not None and selection.scope.kind == "album":
            self.main_window_show_status(
                f"Marking {len(selection.asset_ids)} assets, including their copies "
                "in other albums. Nothing has been deleted."
            )

    def main_window_ask_mark_scope(self, selection: AssetSelection) -> None:
        """Ask whether one album's copy or the whole asset is being marked.

        selection: the captured single-copy ``AssetSelection``.
        Returns None. The prompt is non-blocking, so the answer re-validates the
        selection instead of trusting the parameters read when it was shown.
        """
        if self.main_window_busy():
            self.main_window_show_status(OPERATION_BUSY)
            return
        name = self.main_window_album_name(selection.scope.album_id)
        dialog = MarkScopeDialog(name, self)
        dialog.scope_chosen.connect(partial(self.main_window_mark_scope_chosen, selection))
        dialog.show()

    def main_window_album_name(self, album_id: int | None) -> str:
        """Name an album for a prompt.

        album_id: the album's catalog id, when one is being browsed.
        Returns the album's display name, or a neutral fallback when the album
        list has not been loaded or the album has since disappeared.
        """
        for identifier, name, _ in self.shell.navigation.albums:
            if identifier == album_id:
                return name
        return "this album"

    def main_window_mark_scope_chosen(self, selection: AssetSelection, scope: object) -> None:
        """Stage the mark the user chose the scope for.

        selection: the captured single-copy ``AssetSelection``.
        scope: ``file`` for the browsed copy, anything else for the asset.
        Returns None.
        """
        try:
            parameters = self.models.assets.asset_model_selection_parameters(selection)
        except ValueError as error:
            self.main_window_refuse_selection("Marking", error)
            return
        file_ids = parameters["file_ids"]
        if scope == MARK_SCOPE_COPY and isinstance(file_ids, list) and len(file_ids) == 1:
            self.main_window_start_quiet(
                "app_service_mark", {"target_type": MARK_SCOPE_COPY, "target_id": file_ids[0]}
            )
            return
        request_id = self.main_window_start_quiet(
            "app_service_mark_many", {"asset_ids": parameters["asset_ids"]}
        )
        if request_id is not None:
            self.main_window_show_status(
                "Marking this asset, including its copies in other albums. "
                "Nothing has been deleted."
            )

    @Slot(int, str)
    def main_window_album_action(self, album_id: int, key: str) -> None:
        """Run an album-wide verb chosen from the navigation pane.

        album_id: the album the user right-clicked.
        key: the action key.
        Returns None. An album mark stages one decision covering every copy in
        that album and deletes nothing, so it runs without a confirmation, the
        same way the gallery's mark does.
        """
        if key != "mark":
            self.main_window_show_status(f"{key} is not an album action.")
            return
        request_id = self.main_window_start_quiet(
            "app_service_mark", {"target_type": MARK_SCOPE_ALBUM, "target_id": album_id}
        )
        if request_id is not None:
            self.main_window_show_status(
                f'Marking the album "{self.main_window_album_name(album_id)}". '
                "Nothing has been deleted."
            )

    def main_window_confirm_selection(self, key: str, selection: object) -> None:
        """Describe a destructive selection action and ask for confirmation.

        key: ``delete``, ``restore`` or ``purge``.
        selection: the captured ``AssetSelection``.
        Returns None. Restoring is not destructive and runs directly; the other
        two reach the worker only through the confirmation dialog.
        """
        if not isinstance(selection, AssetSelection) or not selection.asset_ids:
            self.main_window_show_status(NO_SELECTION)
            return
        if self.main_window_busy():
            self.main_window_show_status(OPERATION_BUSY)
            return
        count = len(selection.asset_ids)
        if key == "restore":
            self.main_window_selection_confirmed(
                selection,
                ConfirmSpec("Restore", "Restore", False, operation="app_service_restore"),
            )
            return
        if key == "delete":
            spec = confirm_recycle_spec(count, {})
        else:
            # A recycle-bin purge must not reach the asset's active copies; the
            # user is looking at the deleted ones and asked about those.
            recycled_only = selection.scope.kind == "recycled"
            spec = confirm_purge_spec(
                count, self.main_window_selection_bytes(selection), {}, recycled_only
            )
        confirm_show(spec, self, partial(self.main_window_selection_confirmed, selection))

    def main_window_selection_bytes(self, selection: AssetSelection) -> int:
        """Total the archive bytes a selection represents, when that is meaningful.

        selection: the captured ``AssetSelection``.
        Returns the byte total, or 0 when it cannot be stated honestly. An album
        view deletes only that album's copies, so quoting the whole asset's size
        would overstate what is about to be freed.
        """
        if selection.scope.kind == "album":
            return 0
        model = self.models.assets
        wanted = set(selection.asset_ids)
        total = 0
        for row in model.rows:
            identifier = getattr(row, "asset_id", None)
            size = getattr(row, "size", 0)
            if identifier in wanted and isinstance(size, int):
                total += size
        return total

    def main_window_selection_confirmed(self, selection: AssetSelection, spec: object) -> None:
        """Submit a confirmed selection action against a re-validated selection.

        selection: the captured ``AssetSelection``.
        spec: the approved ``ConfirmSpec``.
        Returns None. The selection is re-checked here, at confirmation time,
        because the dialog is non-blocking: the archive, the view or the model
        generation may all have changed while it was open.
        """
        if not isinstance(spec, ConfirmSpec):
            return
        try:
            parameters = self.models.assets.asset_model_selection_parameters(selection)
        except ValueError as error:
            self.main_window_refuse_selection(operations_title(spec.operation), error)
            return
        parameters.update(spec.parameters)
        self.main_window_start(spec.operation, parameters)

    def main_window_refuse_selection(self, action: str, error: Exception) -> None:
        """Report that a selection action never started, and hold the message.

        action: the human-readable action name.
        error: why the selection was refused.
        Returns None.
        """
        message = f"{action} was not started: {error}"
        self.main_window_show_status(message)
        self.status_override = message

    def main_window_move_selection(self, selection: object) -> None:
        """Ask for a destination album and move the selected copies into it.

        selection: the captured ``AssetSelection``.
        Returns None. The prompt is non-blocking, so the selection is re-checked
        against the model when the user confirms rather than when it was shown.
        """
        if not isinstance(selection, AssetSelection) or not selection.asset_ids:
            self.main_window_show_status("Select at least one photo or video first.")
            return
        if self.main_window_busy():
            self.main_window_show_status(OPERATION_BUSY)
            return
        names = [name for _, name, _ in self.shell.navigation.albums]
        dialog = MoveToAlbumDialog(
            len(selection.asset_ids), names, selection.scope.kind == "album", self
        )
        dialog.move_requested.connect(
            lambda album: self.main_window_move_confirmed(selection, album)
        )
        dialog.show()

    def main_window_move_confirmed(self, selection: AssetSelection, album: str) -> None:
        """Submit a move once a destination album has been named.

        selection: the captured ``AssetSelection``.
        album: the destination album's display name.
        Returns None. ``asset_model_selection_parameters`` refuses a selection
        whose model, archive or scope has changed since it was captured, so a
        move can never land on assets the user never chose.
        """
        try:
            parameters = self.models.assets.asset_model_selection_parameters(selection)
        except ValueError as error:
            self.main_window_show_status(f"The move was not started: {error}")
            self.status_override = f"The move was not started: {error}"
            return
        parameters["album_name"] = album
        # An album view shows one album's copies, so the move must stay scoped to
        # them rather than silently relocating every copy of those assets.
        if selection.scope.kind == "album":
            parameters["source_album_id"] = selection.scope.album_id
        self.main_window_start("app_service_move_selection", parameters)

    @Slot(str, str)
    def main_window_review_action(self, view: str, key: str) -> None:
        """Run an action from one of the report pages.

        view: the review view the action came from.
        key: the action key.
        Returns None. These pages list decisions rather than photos, so their
        actions are asset-scoped and their destructive verbs go through exactly
        the same confirmation dialog the gallery uses.
        """
        page = self.shell.reviews.get(view)
        if page is None:
            return
        if key == "select-all":
            page.review_set_all(True)
            return
        if key == "keep":
            page.review_set_all(False)
            self.main_window_show_status("Nothing was changed. They stay in the archive.")
            return
        if key == "rescan":
            self.shell.shell_refresh_review(view)
            return
        checked = page.review_checked_ids()
        if view == "marked":
            self.main_window_marks_action(key, checked)
            return
        self.main_window_phone_review_action(key, checked)

    def main_window_phone_review_action(self, key: str, asset_ids: list[int]) -> None:
        """Confirm a decision about assets that are gone from the phone.

        key: ``recycle`` or ``purge``.
        asset_ids: the assets the user checked.
        Returns None. This report is asset-scoped: the phone knows nothing about
        which archive copies exist, so the action covers every copy and the
        dialog says so.
        """
        if not asset_ids:
            self.main_window_show_status("Tick the items you want to act on first.")
            return
        if self.main_window_busy():
            self.main_window_show_status(OPERATION_BUSY)
            return
        parameters: dict[str, object] = {"asset_ids": list(asset_ids)}
        if key == "recycle":
            spec = confirm_recycle_spec(len(asset_ids), parameters)
        elif key == "purge":
            spec = confirm_purge_spec(len(asset_ids), 0, parameters, False)
        else:
            self.main_window_show_status(f"{key} is not an action here.")
            return
        confirm_show(spec, self, self.main_window_confirmed)

    def main_window_marks_action(self, key: str, mark_ids: list[int]) -> None:
        """Run an action from the marks queue.

        key: the action key.
        mark_ids: the marks the user checked, for the per-mark actions.
        Returns None. Committing applies the whole queue, which is what the CLI
        does, so those buttons ignore the checked rows and say so in the dialog.
        """
        staged = len(self.shell.reviews["marked"].review_list.rows)
        if key == "unmark":
            self.main_window_unmark(mark_ids)
            return
        if key == "clear":
            # Clearing marks deletes nothing at all, so it needs no confirmation.
            self.main_window_start_quiet("app_service_clear_marks", {})
            return
        if key in {"commit-recycle", "commit-purge"}:
            if not staged:
                self.main_window_show_status("Nothing is marked.")
                return
            if self.main_window_busy():
                self.main_window_show_status(OPERATION_BUSY)
                return
            spec = confirm_marks_spec(staged, key == "commit-purge")
            confirm_show(spec, self, self.main_window_confirmed)
            return
        self.main_window_show_status(f"{key} is not an action here.")

    def main_window_unmark(self, mark_ids: list[int]) -> None:
        """Remove the checked marks one by one.

        mark_ids: the marks to remove.
        Returns None. There is no bulk unmark call and the worker's queue is
        bounded, so a very large selection is refused with the alternative that
        does the same job in one request.
        """
        if not mark_ids:
            self.main_window_show_status("Tick the marks you want to remove first.")
            return
        if len(mark_ids) > MAX_BULK_REQUESTS:
            self.main_window_show_status(
                f"Removing more than {MAX_BULK_REQUESTS} marks at once is not supported. "
                'Use "Clear all marks" instead.'
            )
            return
        for mark_id in mark_ids:
            if self.main_window_submit("app_service_unmark", {"mark_id": mark_id}) is None:
                return
        self.main_window_show_status(f"Removed {len(mark_ids)} marks. Nothing has been deleted.")

    def main_window_confirmed(self, spec: object) -> None:
        """Submit an approved action that needs no selection re-validation.

        spec: the approved ``ConfirmSpec``.
        Returns None. The ids it carries come from a report the service itself
        produced, and the service re-checks them again before deleting anything.
        """
        if not isinstance(spec, ConfirmSpec):
            return
        self.main_window_start(spec.operation, dict(spec.parameters))

    def main_window_open_reclaim(self, value: object) -> None:
        """Show what a reclamation dry run found, and route its request onward.

        value: the worker's returned ``ReclaimResult``.
        Returns None. A preview with nothing in it opens no dialog: there is
        nothing to decide, and the summary line already says so.
        """
        if not isinstance(value, ReclaimResult) or not value.dry_run:
            return
        if not value.candidates:
            return
        dialog = ReclaimDialog(value, self)
        dialog.reclaim_requested.connect(partial(self.main_window_reclaim_requested, value))
        dialog.show()

    def main_window_reclaim_requested(self, preview: object, asset_ids: object) -> None:
        """Confirm the phone-side deletion the reclaim dialog asked for.

        preview: the dry run the selection was made from.
        asset_ids: the candidate asset ids the user chose.
        Returns None. This is the last step before real phone files are deleted,
        so it still requires the typed word.
        """
        if not isinstance(asset_ids, list) or not asset_ids:
            return
        spec = confirm_reclaim_spec(
            len(asset_ids), reclaim_selected_bytes(preview, asset_ids), asset_ids
        )
        confirm_show(spec, self, self.main_window_confirmed)

    @Slot(object)
    def main_window_worker_failed(self, failure: WorkerFailure) -> None:
        """Surface worker errors in the shell; operation-specific views arrive in later steps."""
        message = f"{failure.operation} failed: {failure.message}"
        self.main_window_show_status(message)
        self.status_override = message

    @Slot(object)
    def main_window_clear_error(self, reply: object = None) -> None:
        """Stop holding an error once a user-initiated operation has succeeded.

        reply: the worker result being delivered.
        Returns None. A failed mutation makes the shell re-read its counters and
        the gallery fetch pages; those reads succeed, so treating them as
        success would wipe the very error that caused them. Only a read the user
        actually asked for clears the message.
        """
        request_id = getattr(reply, "request_id", None)
        if isinstance(request_id, int) and self.main_window_is_automatic(request_id):
            return
        self.status_override = None

    def main_window_is_automatic(self, request_id: int) -> bool:
        """Report whether a request was issued by the GUI itself rather than the user.

        request_id: the worker request being answered.
        Returns True for shell counter refreshes and model page reads.
        """
        return self.shell.shell_is_housekeeping(request_id) or self.models.models_is_page_request(
            request_id
        )

    @Slot(str)
    def main_window_command(self, key: str) -> None:
        """Run a command-bar verb, or explain why it is not available yet.

        key: the command-bar key that was activated.
        Returns None. No verb silently does nothing: a command is either run, or
        it names the step that will gate it safely.
        """
        if key in {"open", "create"}:
            self.main_window_choose_archive(key == "create")
            return
        deferred = DEFERRED_COMMANDS.get(key)
        if deferred is not None:
            self.main_window_show_status(deferred)
            return
        command = COMMANDS_BY_KEY.get(key)
        if key == "settings":
            self.main_window_open_settings()
            return
        if command is None:
            self.main_window_show_status(f"{key} is not a command.")
            return
        if key == "clear-thumbnails":
            self.main_window_clear_previews(command.operation)
        elif key in DIALOG_COMMANDS:
            self.main_window_start(command.operation, {})
        elif key in QUIET_COMMANDS:
            self.main_window_start_quiet(command.operation, {})
        else:
            self.main_window_show_status(f"{command.label} has no surface yet.")

    def main_window_clear_previews(self, operation: str) -> None:
        """Delete the preview cache without fighting the loaders that read it.

        operation: the service operation to run.
        Returns None. The preview pools deliberately bypass the service worker,
        so they would otherwise be reading and writing the very files the worker
        is unlinking. Pending renders are cancelled first, and the decoded cache
        is dropped afterwards so the window cannot keep showing previews whose
        files have just been deleted.
        """
        self.previews.previews_cancel_all()
        self.viewer_previews.previews_cancel_all()
        if self.main_window_start_quiet(operation, {}) is None:
            return
        for loader in (self.previews, self.viewer_previews):
            loader.cache.previews_cache_clear()
            loader.previews_retry()

    def main_window_choose_archive(self, create: bool) -> None:
        """Open or create an archive from a folder the user picks.

        create: True to initialise a new archive in the chosen folder.
        Returns None. Apart from the reopen-on-startup preference, which only
        ever reopens an archive that already exists, this is how a session
        begins.
        """
        title = "Choose a folder for the new archive" if create else "Choose an archive folder"
        directory = self.main_window_choose_directory(title)
        if not directory:
            return
        self.main_window_open_path(Path(directory), create=create)

    def main_window_open_path(self, archive_root: Path, *, create: bool = False) -> int | None:
        """Open or create one archive folder.

        archive_root: the folder to open.
        create: True to initialise a new archive there.
        Returns the accepted request ID, or None when the worker refused it.
        """
        operation = "create_archive" if create else "open_archive"
        try:
            request_id = self.worker.worker_open(Path(archive_root), create=create)
        except (RuntimeError, ValueError, TypeError) as error:
            self.main_window_refuse(operation, error)
            return None
        self.quiet_requests[request_id] = operation
        self.main_window_show_status(f"{'Creating' if create else 'Opening'} {archive_root}...")
        return request_id

    def main_window_restore_session(self) -> int | None:
        """Reopen the last archive when the stored preference asks for it.

        Returns the accepted request ID, or None when nothing was reopened. Only
        a folder that is still an archive is reopened: the preference remembers
        a location, and a removed drive or a deleted folder must not turn
        startup into an error, let alone create an archive nobody asked for.
        """
        if not self.preferences.reopen_last_archive:
            return None
        candidate = self.preferences.default_archive or next(
            iter(self.preferences.recent_archives), None
        )
        if not candidate:
            return None
        root = Path(candidate)
        if not config_is_archive(root):
            LOGGER.info("not reopening %s: it is no longer an archive", root)
            return None
        return self.main_window_open_path(root)

    def main_window_open_settings(self) -> None:
        """Show the preferences editor, filled with what is really stored.

        Returns None. The dialog is opened by the reply, not by the press, so it
        can never show a hand-made default that differs from the settings file.
        Preferences need no archive, so this works before one is open.
        """
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        if self.main_window_settings_submit("app_service_settings_path", {}) is None:
            return
        if self.main_window_settings_submit("app_service_get_settings", {}) is None:
            return
        self.main_window_show_status("Reading settings...")

    def main_window_settings_submit(
        self, operation: str, parameters: dict[str, object]
    ) -> int | None:
        """Submit a preference operation and remember it for its reply.

        operation: the service operation to run.
        parameters: the operation's data-only arguments.
        Returns the accepted request ID, or None when the worker refused it.
        """
        request_id = self.main_window_submit(operation, parameters)
        if request_id is not None:
            self.settings_requests[request_id] = operation
        return request_id

    def main_window_settings_action(self, operation: str, parameters: object) -> None:
        """Route what the settings dialog asked for to the worker.

        operation: the service operation the dialog named.
        parameters: its data-only arguments.
        Returns None. The preview cache keeps its own path because the loaders
        that read those files are not the worker's to synchronise.
        """
        if not isinstance(parameters, dict):
            return
        if operation == "app_service_clear_thumbnails":
            self.main_window_clear_previews(operation)
            return
        self.main_window_settings_submit(operation, dict(parameters))

    @Slot(object)
    def main_window_settings_reply(self, reply: WorkerResult | WorkerFailure) -> None:
        """Apply the outcome of a preference operation.

        reply: a worker result, cancellation or failure.
        Returns None. Failures are already held on screen by the worker-failure
        slot; here they only stop the dialog from acting on a write that never
        happened.
        """
        operation = self.settings_requests.pop(reply.request_id, None)
        if operation is None or isinstance(reply, WorkerFailure) or reply.cancelled:
            return
        value = reply.value
        if operation == "app_service_settings_path":
            self.settings_file = value if isinstance(value, Path) else None
            return
        if operation == "app_service_get_settings":
            self.main_window_show_settings(value)
            return
        self.main_window_show_status(operations_summary(operation, value))
        if operation in {"app_service_update_settings", "app_service_reset_settings"}:
            self.main_window_apply_preferences(value)
        if self.settings_dialog is not None and isinstance(value, Settings):
            self.settings_dialog.settings_dialog_show(value, self.settings_file)

    def main_window_show_settings(self, value: object) -> None:
        """Open the settings dialog around the preferences the worker read.

        value: the worker's returned ``Settings``.
        Returns None.
        """
        if not isinstance(value, Settings) or self.settings_dialog is not None:
            return
        self.preferences = value
        archive_root = self.worker.archive_root
        dialog = SettingsDialog(
            value,
            self.settings_file,
            archive_open=archive_root is not None,
            logs_dir=config_resolve_paths(archive_root).logs_dir
            if archive_root is not None
            else None,
            parent=self,
        )
        dialog.settings_requested.connect(self.main_window_settings_action)
        dialog.destroyed.connect(self.main_window_settings_closed)
        self.settings_dialog = dialog
        dialog.show()

    def main_window_settings_closed(self, obj: object = None) -> None:
        """Forget the settings dialog once Qt has destroyed it.

        obj: the dying QObject, which must not be touched.
        Returns None.
        """
        self.settings_dialog = None

    def main_window_apply_preferences(self, value: object) -> None:
        """Apply stored preferences to the running window.

        value: the ``Settings`` the service just saved.
        Returns None. A preference that only reached the file would leave the
        window disagreeing with its own settings dialog until the next launch.
        """
        if not isinstance(value, Settings):
            return
        self.preferences = value
        self.previews.previews_set_size(main_window_preview_size(value))
        self.shell.shell_set_deleted_default(value.default_deleted_action)
        controller = self.findChild(ThemeController)
        if controller is not None:
            controller.theme_set_preference(value.theme)
        try:
            logging_setup_configure(level=value.log_level)
        except ValueError as error:
            LOGGER.warning("keeping the current log level: %s", error)

    def main_window_choose_directory(self, title: str) -> str:
        """Ask the user for a folder.

        title: the file dialog's caption.
        Returns the chosen path, or an empty string when the user cancelled.
        This is a separate method so tests can answer it without a native file
        dialog and its nested event loop.
        """
        return QFileDialog.getExistingDirectory(self, title)

    def main_window_submit(self, operation: str, parameters: dict[str, object]) -> int | None:
        """Submit one request, reporting a refusal instead of raising into Qt.

        operation: the service operation to run.
        parameters: the operation's data-only arguments.
        Returns the accepted request ID, or None when the worker refused it.
        """
        try:
            return self.worker.worker_submit(operation, parameters)
        except (RuntimeError, ValueError, TypeError) as error:
            self.main_window_refuse(operation, error)
            return None

    def main_window_refuse(self, operation: str, error: Exception) -> None:
        """Report that an operation never started, and keep that message on screen.

        operation: the service operation that was refused.
        error: the controller's refusal.
        Returns None.
        """
        message = f"{operations_title(operation)} could not start: {error}"
        self.main_window_show_status(message)
        self.status_override = message

    def main_window_busy(self) -> bool:
        """Report whether a long operation is still running.

        Returns True only while a dialog is watching unfinished work. A finished
        dialog is destroyed one event-loop turn after it closes, so testing the
        reference alone would refuse the user's next command for no reason.
        """
        return self.operation is not None and self.operation.running

    def main_window_start(self, operation: str, parameters: dict[str, object]) -> int | None:
        """Run a long operation behind the progress dialog.

        operation: the service operation to run.
        parameters: the operation's data-only arguments.
        Returns the accepted request ID, or None when nothing was started.
        """
        if self.main_window_busy():
            self.main_window_show_status(OPERATION_BUSY)
            return None
        request_id = self.main_window_submit(operation, parameters)
        if request_id is None:
            return None
        dialog = OperationDialog(self.worker, request_id, operation, self)
        dialog.operation_status.connect(self.main_window_operation_status)
        dialog.operation_completed.connect(self.main_window_completed)
        # `destroyed`, not `finished`: a self-deleting dialog can be destroyed
        # without ever emitting `finished` - closing a hidden dialog is one such
        # path - and the window would then hold a pointer to a dead object. The
        # request ID is bound now because the dying QObject must not be touched,
        # and because a finished dialog is destroyed one event-loop turn after
        # it closes: by then it may already have been replaced.
        dialog.destroyed.connect(partial(self.main_window_operation_closed, request_id))
        self.operation = dialog
        dialog.show()
        return request_id

    def main_window_start_quiet(self, operation: str, parameters: dict[str, object]) -> int | None:
        """Run a short read and report its outcome in one status line.

        operation: the service operation to run.
        parameters: the operation's data-only arguments.
        Returns the accepted request ID, or None when nothing was started.
        """
        request_id = self.main_window_submit(operation, parameters)
        if request_id is None:
            return None
        self.quiet_requests[request_id] = operation
        self.main_window_show_status(f"{operations_title(operation)}...")
        return request_id

    @Slot(str, bool)
    def main_window_operation_status(self, message: str, sticky: bool) -> None:
        """Show a progress dialog's message, holding it when it reports a problem.

        message: the text to display.
        sticky: whether the message must survive the shell's routine refreshes.
        Returns None.
        """
        self.main_window_show_status(message)
        if sticky:
            self.status_override = message

    def main_window_operation_closed(self, request_id: int, obj: object = None) -> None:
        """Forget the progress dialog the moment it is destroyed.

        request_id: the request the dying dialog was watching.
        obj: the dying QObject, which must not be touched.
        Returns None. Only the current dialog's death clears the reference: a
        dialog destroyed after being replaced must not orphan its successor,
        which would leave a running operation with nothing watching it.
        """
        if self.operation is not None and self.operation.request_id == request_id:
            self.operation = None

    @Slot(object)
    def main_window_quiet_reply(self, reply: WorkerResult | WorkerFailure) -> None:
        """Report the outcome of a short read that had no dialog.

        reply: a worker result, cancellation or failure.
        Returns None. Failures are left to ``main_window_worker_failed``, which
        already holds them on screen.
        """
        operation = self.quiet_requests.pop(reply.request_id, None)
        if operation is None or isinstance(reply, WorkerFailure):
            return
        if reply.cancelled:
            self.main_window_show_status(f"{operations_title(operation)} was cancelled.")
            return
        self.main_window_show_status(operations_summary(operation, reply.value))
        self.main_window_completed(operation, reply.value)

    @Slot(str, object)
    def main_window_completed(self, operation: str, value: object) -> None:
        """Show the report an operation produced, when it produced one.

        operation: the service operation that finished.
        value: the detached result the worker returned.
        Returns None.
        """
        if operation == "app_service_dedup_report":
            ReportDialog("Storage and duplicate report", dialogs_dedup_lines(value), self).show()
        elif operation == "app_service_reclaim":
            self.main_window_open_reclaim(value)


def main_window_preferences() -> Settings:
    """Read the stored preferences, falling back to the defaults.

    Returns the stored ``Settings``. A hand-edited settings file must never stop
    the window from opening, so an invalid one is reported and replaced by the
    defaults here rather than raising into the constructor.
    """
    try:
        return settings_load()
    except Exception as error:
        LOGGER.warning("using default preferences: %s", error)
        return Settings()


def main_window_preview_size(settings: Settings | None = None) -> int:
    """Resolve the thumbnail size the preview loader should use.

    settings: already-loaded preferences, or None to read them now.
    Returns a usable bounding-box size. ``settings_load`` validates as it reads,
    so the read itself is guarded rather than only its result.
    """
    preferences = main_window_preferences() if settings is None else settings
    size = preferences.thumbnail_size
    if not isinstance(size, int) or isinstance(size, bool):
        return DEFAULT_THUMBNAIL_SIZE
    return size if MIN_PREVIEW_SIZE <= size <= MAX_PREVIEW_SIZE else DEFAULT_THUMBNAIL_SIZE
