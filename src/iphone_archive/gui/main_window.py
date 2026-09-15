"""Main window shell.

Holds the window chrome, the page stack and the routing between what the user
asks for and what the service worker runs.

Every command reaches the worker through one of two paths. Long operations get
the sketch's progress dialog, which can be cancelled where cancellation really
exists and hidden where it does not. Short reads run quietly and report a single
summary line, because a modal dialog that appears and vanishes tells the user
less than the status bar does.

Destructive verbs - reclaim, delete, purge, restore, commit marks - are not
routed here. They need the typed confirmation of step 9 and deliberately still
say so rather than silently doing nothing.
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
from ..settings import settings_load
from .commands import COMMANDS_BY_KEY
from .dialogs import MoveToAlbumDialog, ReportDialog, dialogs_dedup_lines
from .models import ArchiveModels, AssetSelection
from .operations import OperationDialog, operations_summary, operations_title
from .previews import MAX_PREVIEW_SIZE, MIN_PREVIEW_SIZE, PreviewLoader
from .shell import ArchiveShell
from .viewer import VIEWER_PREVIEW_SIZE, ViewerDialog
from .worker import WorkerController, WorkerFailure, WorkerResult

LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "iPhone Archive"
WINDOW_DEFAULT_SIZE = (1180, 760)
WINDOW_MINIMUM_SIZE = (900, 560)

# Commands that take long enough, or touch the phone slowly enough, to deserve
# the progress dialog. The only device presence probe enumerates the whole
# library, so "Check phone" belongs here too.
DIALOG_COMMANDS = frozenset({"import", "verify", "scan", "device"})
# Short reads that report one line. A modal dialog for a counter refresh would
# flash open and shut without telling the user anything.
QUIET_COMMANDS = frozenset({"dedup", "stats", "clear-thumbnails", "close"})
# Verbs whose safety gating is step 9 (destructive) or step 10 (settings). They
# say so rather than appearing to work.
DEFERRED_COMMANDS = {
    "reclaim": "Freeing phone space needs its confirmation dialog (step 9).",
    "settings": "Settings get their own dialog (step 10).",
}
OPERATION_BUSY = "Another operation is already running. Wait for it, or cancel it first."
DEFERRED_SELECTION_ACTIONS = {
    "mark": "Marking for deletion arrives with the marks queue (step 9).",
    "delete": "Moving to the recycle bin needs its confirmation dialog (step 9).",
    "restore": "Restoring from the recycle bin arrives in step 9.",
    "purge": "Permanent deletion needs its typed confirmation (step 9).",
}


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
        self.previews = PreviewLoader(self, size=main_window_preview_size())
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

        self.shell = ArchiveShell(self.worker, self.models, self.previews, self)
        self.shell.shell_status_changed.connect(self.main_window_show_state)
        self.shell.shell_command.connect(self.main_window_command)
        self.shell.shell_selection_action.connect(self.main_window_selection_action)
        self.shell.shell_open_asset.connect(self.main_window_open_viewer)
        self.worker.result_ready.connect(self.main_window_quiet_reply)
        self.worker.failed.connect(self.main_window_quiet_reply)
        self.worker.cancelled.connect(self.main_window_quiet_reply)
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
        self.main_window_show_status(f"{key} is not a batch action.")

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
        Returns None. Nothing is opened automatically at startup, so this is the
        only way an archive session begins.
        """
        title = "Choose a folder for the new archive" if create else "Choose an archive folder"
        directory = self.main_window_choose_directory(title)
        if not directory:
            return
        operation = "create_archive" if create else "open_archive"
        try:
            request_id = self.worker.worker_open(Path(directory), create=create)
        except (RuntimeError, ValueError, TypeError) as error:
            self.main_window_refuse(operation, error)
            return
        self.quiet_requests[request_id] = operation
        self.main_window_show_status(f"{'Creating' if create else 'Opening'} {directory}...")

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


def main_window_preview_size() -> int:
    """Read the persisted thumbnail size, falling back to the default.

    Returns a usable bounding-box size. A hand-edited settings file must never
    stop the window from opening, and ``settings_load`` validates as it reads,
    so the read itself is guarded rather than only its result.
    """
    try:
        size = settings_load().thumbnail_size
    except Exception as error:
        LOGGER.warning("using the default thumbnail size: %s", error)
        return DEFAULT_THUMBNAIL_SIZE
    if not isinstance(size, int) or isinstance(size, bool):
        return DEFAULT_THUMBNAIL_SIZE
    return size if MIN_PREVIEW_SIZE <= size <= MAX_PREVIEW_SIZE else DEFAULT_THUMBNAIL_SIZE
