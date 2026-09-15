"""Progress dialog and result summaries for long-running archive operations.

Sketch §2. One dialog serves every long operation, because they all report
through the same ``ProgressHandle`` and all return a plain summary DTO.

Two honesty rules shape this module:

* **Cancellation is only offered where it exists.** Only operations whose
  service method accepts a progress handle can be interrupted at a safe
  checkpoint; the rest run off the GUI thread but cannot be stopped, so they
  show no Cancel button rather than a button that quietly does nothing.
* **Hiding is not finishing.** "Hide" leaves the operation running and reports
  its outcome in the status bar. A run that ends with errors re-opens the
  dialog, because an error summary must never be reduced to one status line
  the user may have already replaced.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import ArchivePaths
from ..core.dedup import DedupResult
from ..core.importer import ImportResult
from ..core.reclaim import ReclaimResult
from ..core.recycle import RecycleResult
from ..core.verifier import VerifyResult
from ..service.app_service import AppService, DeviceInfo
from ..service.progress import ProgressEvent
from ..service.selection import SelectionResult
from .gallery import gallery_format_size
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font
from .worker import SERVICE_OPERATIONS, WorkerController, WorkerFailure, WorkerResult

LOGGER = logging.getLogger(__name__)

OPERATION_DIALOG_SIZE = (520, 240)
# The bar is a percentage so an operation reporting millions of units does not
# overflow Qt's integer range.
PROGRESS_STEPS = 1000
ELAPSED_INTERVAL_MS = 1000
# Long file names must not widen the dialog as the operation walks the library.
MAX_DETAIL_CHARS = 56
# Long error lists are truncated: the dialog reports the failures it can show
# and the log keeps the whole story.
MAX_ERROR_LINES = 6


def operations_cancellable() -> frozenset[str]:
    """Find the service operations that accept a progress handle.

    Returns the operation names that can be interrupted. This is derived from
    the real signatures rather than hand-listed: a hand-written set drifts, and
    the failure mode is a Cancel button that quietly does nothing. Only an
    operation given a ``ProgressHandle`` ever sees the cancellation event.
    """
    cancellable = set()
    for name in SERVICE_OPERATIONS:
        method = getattr(AppService, name, None)
        if method is None:
            continue
        if "progress" in inspect.signature(method).parameters:
            cancellable.add(name)
    return frozenset(cancellable)


CANCELLABLE_OPERATIONS = operations_cancellable()

OPERATION_TITLES = {
    "app_service_import": "Importing from iPhone",
    "app_service_verify": "Verifying the archive",
    "app_service_scan_phone": "Scanning the iPhone",
    "app_service_device_info": "Checking the iPhone",
    "app_service_move_selection": "Moving to album",
    "app_service_move_to_deleted": "Moving to the Deleted folder",
    "app_service_restore": "Restoring from the recycle bin",
    "app_service_purge": "Deleting permanently",
    "app_service_reclaim": "Freeing space on the iPhone",
    "app_service_commit_marks": "Applying the marked deletions",
    "app_service_deleted_on_phone": "Checking what is gone from the phone",
}


def operations_title(operation: str) -> str:
    """Return the dialog heading for an operation.

    operation: the service operation being run.
    Returns a sentence-case title, falling back to the operation name so a new
    operation is never presented as a blank dialog.
    """
    return OPERATION_TITLES.get(operation, operation.replace("app_service_", "").replace("_", " "))


def operations_shorten(text: str, limit: int) -> str:
    """Shorten a progress detail to a fixed character budget.

    text: the detail line, usually a file name or archive-relative path.
    limit: the maximum number of characters to keep.
    Returns the possibly shortened text, elided in the middle so both the
    album folder and the file name stay readable.
    """
    if limit < 5 or len(text) <= limit:
        return text
    head = (limit - 3) // 2
    return f"{text[:head]}...{text[len(text) - (limit - 3 - head) :]}"


def operations_format_duration(seconds: float) -> str:
    """Format a duration as mm:ss, or h:mm:ss once it passes an hour.

    seconds: the duration to format; negative values are treated as zero.
    Returns the formatted text.
    """
    total = max(int(seconds), 0)
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes:02d}:{remainder:02d}"


def operations_remaining(elapsed: float, fraction: float) -> str:
    """Estimate the time left from the completed fraction.

    elapsed: seconds since the operation started.
    fraction: completion between 0.0 and 1.0.
    Returns the estimate text, or an empty string when it would be guesswork.
    """
    if fraction <= 0.0 or fraction >= 1.0 or elapsed <= 0.0:
        return ""
    return f"Remaining ~{operations_format_duration(elapsed / fraction - elapsed)}"


def operations_import_summary(value: object) -> str:
    """Summarise an import run.

    value: the worker's returned ``ImportResult``.
    Returns the summary line.
    """
    if not isinstance(value, ImportResult):
        return "Import finished."
    parts = [
        f"Added {value.added_count}",
        f"skipped {value.skipped_count}",
        f"duplicates {value.duplicate_count}",
        f"errors {value.error_count}",
    ]
    text = ", ".join(parts) + "."
    if value.cancelled:
        # Everything copied before the stop is already committed, so this is a
        # partial success rather than an abandoned run.
        text = f"Import stopped early. {text} What was copied is archived."
    return text


def operations_verify_summary(value: object) -> str:
    """Summarise a verification run.

    value: the worker's returned ``VerifyResult``.
    Returns the summary line.
    """
    if not isinstance(value, VerifyResult):
        return "Verification finished."
    text = (
        f"Checked {value.checked_count}: {value.ok_count} ok, "
        f"{value.mismatch_count} mismatched, {value.missing_count} missing."
    )
    if value.cancelled:
        text = f"Verification stopped early. {text}"
    return text


def operations_dedup_summary(value: object) -> str:
    """Summarise a duplicate report.

    value: the worker's returned ``DedupResult``.
    Returns the summary line.
    """
    if not isinstance(value, DedupResult):
        return "Duplicate report finished."
    return (
        f"{value.asset_count} assets stored as {value.file_count} copies; "
        f"{len(value.multi_copy_groups)} duplicated across albums using "
        f"{gallery_format_size(value.reclaimable_bytes)} extra."
    )


def operations_move_summary(value: object) -> str:
    """Summarise a move-to-album run.

    value: the worker's returned ``SelectionResult``.
    Returns the summary line.
    """
    if not isinstance(value, SelectionResult):
        return "Move finished."
    text = f"Moved {value.affected_count} copies, skipped {value.skipped_count}."
    if value.errors:
        text = f"{text} {len(value.errors)} errors."
    return text


def operations_device_summary(value: object) -> str:
    """Summarise a device probe.

    value: the worker's returned ``DeviceInfo``.
    Returns the summary line.
    """
    if not isinstance(value, DeviceInfo):
        return "Phone check finished."
    return f"iPhone {value.udid or 'unknown'} holds {value.media_count} items."


def operations_stats_summary(value: object) -> str:
    """Summarise the archive counters.

    value: the worker's returned counts mapping.
    Returns the summary line.
    """
    if not isinstance(value, dict):
        return "Counts refreshed."
    return (
        f"{value.get('assets', 0)} assets, {value.get('albums', 0)} albums, "
        f"{value.get('unsorted', 0)} unsorted, {value.get('recycled', 0)} in the recycle bin, "
        f"{value.get('deleted_on_phone', 0)} gone from the phone."
    )


def operations_thumbnails_summary(value: object) -> str:
    """Summarise a preview-cache clear.

    value: the number of cache files removed.
    Returns the summary line.
    """
    count = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return f"Deleted {count} cached previews. They are regenerated on demand."


def operations_open_summary(value: object) -> str:
    """Summarise an archive open or create.

    value: the worker's returned ``ArchivePaths``.
    Returns the summary line.
    """
    if not isinstance(value, ArchivePaths):
        return "Archive opened."
    return f"Opened {value.root}."


def operations_recycle_summary(value: object) -> str:
    """Summarise a recycle-bin move, restore, purge or mark commit.

    value: the worker's returned ``RecycleResult``.
    Returns the summary line naming only the counts that are non-zero, so a
    restore does not report "0 deleted" and a purge does not read like a move.
    """
    if not isinstance(value, RecycleResult):
        return "Finished."
    parts = []
    for count, text in (
        (value.moved_count, "moved to the Deleted folder"),
        (value.restored_count, "restored"),
        (value.purged_count, "permanently deleted"),
    ):
        if count:
            parts.append(f"{count} {text}")
    if not parts:
        parts.append("nothing changed")
    text = f"{'; '.join(parts).capitalize()}."
    if value.skipped_count:
        text = f"{text} {value.skipped_count} skipped."
    if value.errors:
        text = f"{text} {len(value.errors)} errors."
    return text


def operations_reclaim_summary(value: object) -> str:
    """Summarise a reclamation preview or a real phone-side deletion.

    value: the worker's returned ``ReclaimResult``.
    Returns the summary line. A dry run is described as a preview, because a
    line reading "3918 items" after a preview would imply a deletion that did
    not happen.
    """
    if not isinstance(value, ReclaimResult):
        return "Reclaim finished."
    if value.dry_run:
        text = (
            f"{len(value.candidates)} items, {gallery_format_size(value.reclaimable_bytes)}, "
            "can be safely deleted from the phone. Nothing has been deleted."
        )
    else:
        text = f"Deleted {value.deleted_count} items from the iPhone. The archive is unchanged."
    if value.skipped_count:
        text = f"{text} {value.skipped_count} skipped."
    if value.cancelled:
        text = f"{text} Cancelled before finishing."
    if value.errors:
        text = f"{text} {len(value.errors)} errors."
    return text


def operations_marks_summary(value: object) -> str:
    """Summarise the staged marks listing.

    value: the worker's returned list of marks.
    Returns the summary line.
    """
    count = len(value) if isinstance(value, list) else 0
    if not count:
        return "Nothing is marked."
    return f"{count} marked for deletion. Nothing has been deleted."


SUMMARY_BUILDERS: dict[str, Callable[[object], str]] = {
    "app_service_import": operations_import_summary,
    "app_service_verify": operations_verify_summary,
    "app_service_dedup_report": operations_dedup_summary,
    "app_service_move_selection": operations_move_summary,
    "app_service_device_info": operations_device_summary,
    "app_service_stats": operations_stats_summary,
    "app_service_clear_thumbnails": operations_thumbnails_summary,
    "app_service_scan_phone": lambda value: "Phone scan complete.",
    "app_service_move_to_deleted": operations_recycle_summary,
    "app_service_restore": operations_recycle_summary,
    "app_service_purge": operations_recycle_summary,
    "app_service_commit_marks": operations_recycle_summary,
    "app_service_reclaim": operations_reclaim_summary,
    "app_service_list_marks": operations_marks_summary,
    "app_service_mark_many": lambda value: (
        f"Marked {len(value) if isinstance(value, list) else 0} items. Nothing has been deleted."
    ),
    "app_service_unmark": lambda value: "Mark removed. Nothing has been deleted.",
    "app_service_clear_marks": lambda value: (
        f"Cleared {value if isinstance(value, int) else 0} marks. Nothing has been deleted."
    ),
    "open_archive": operations_open_summary,
    "create_archive": operations_open_summary,
    "close_archive": lambda value: "Archive closed.",
}


def operations_summary(operation: str, value: object) -> str:
    """Describe a completed operation in one line.

    operation: the service operation that finished.
    value: the detached result the worker returned.
    Returns the summary text; unknown operations report completion rather than
    raising, because this runs while presenting a result the user is waiting for.
    """
    builder = SUMMARY_BUILDERS.get(operation)
    if builder is None:
        return f"{operations_title(operation)} finished."
    try:
        return builder(value)
    except Exception as error:
        LOGGER.warning("could not summarise %s: %s", operation, error)
        return f"{operations_title(operation)} finished."


def operations_is_problem(operation: str, value: object) -> bool:
    """Report whether a completed run needs the user's attention.

    operation: the service operation that finished.
    value: the detached result the worker returned.
    Returns True when the outcome should re-open a hidden dialog: counted
    errors, or verification findings. A cancelled run is not a problem, because
    the user asked for it.
    """
    if isinstance(value, ImportResult):
        return value.error_count > 0
    if isinstance(value, VerifyResult):
        return not value.passed
    if isinstance(value, SelectionResult):
        return bool(value.errors)
    if isinstance(value, (RecycleResult, ReclaimResult)):
        return bool(value.errors)
    return False


def operations_detail_lines(operation: str, value: object) -> list[str]:
    """Return the individual error lines a result carries.

    operation: the service operation that finished.
    value: the detached result the worker returned.
    Returns the error texts, so a summary count is never the only evidence.
    """
    if isinstance(value, (ImportResult, SelectionResult, RecycleResult, ReclaimResult)):
        return [str(error) for error in value.errors]
    if isinstance(value, VerifyResult):
        return [f"{issue.path}: {issue.status}" for issue in value.issues]
    return []


class OperationDialog(QDialog):
    """Progress, cancellation and the final summary for one accepted request."""

    operation_status = Signal(str, bool)
    operation_completed = Signal(str, object)

    def __init__(
        self,
        worker: WorkerController,
        request_id: int,
        operation: str,
        parent: QWidget | None = None,
    ) -> None:
        """Watch one already accepted worker request.

        worker: the GUI-affine controller the request was submitted to.
        request_id: the accepted request this dialog reports on.
        operation: the service operation being run.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("OperationDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(True)
        self.setWindowTitle("iPhone Archive")
        self.resize(*OPERATION_DIALOG_SIZE)
        self.worker = worker
        self.request_id = request_id
        self.operation = operation
        self.running = True
        self.cancelling = False
        self.started = monotonic()
        self.fraction = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.title_label = QLabel(operations_title(operation), self)
        self.title_label.setFont(theme_font("subtitle"))
        self.detail_label = QLabel("Starting...", self)
        self.detail_label.setFont(theme_font("body"))
        self.bar = QProgressBar(self)
        self.bar.setObjectName("OperationProgress")
        self.bar.setTextVisible(False)
        # Unknown totals are honest about being unknown rather than sitting at
        # zero percent for the whole run.
        self.bar.setRange(0, 0)
        self.count_label = QLabel("", self)
        self.count_label.setFont(theme_font("caption"))
        self.count_label.setProperty("role", "secondary")
        self.timing_label = QLabel("Elapsed 00:00", self)
        self.timing_label.setFont(theme_font("caption"))
        self.timing_label.setProperty("role", "secondary")
        self.errors_label = QLabel("", self)
        self.errors_label.setFont(theme_font("caption"))
        self.errors_label.setWordWrap(True)
        self.errors_label.setVisible(False)
        for widget in (
            self.title_label,
            self.detail_label,
            self.bar,
            self.count_label,
            self.timing_label,
            self.errors_label,
        ):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addLayout(self.operation_build_buttons())

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(ELAPSED_INTERVAL_MS)
        self.elapsed_timer.timeout.connect(self.operation_tick)
        self.elapsed_timer.start()

        worker.progress_changed.connect(self.operation_progress)
        worker.result_ready.connect(self.operation_reply)
        worker.failed.connect(self.operation_reply)
        worker.cancelled.connect(self.operation_reply)

    def operation_build_buttons(self) -> QHBoxLayout:
        """Build the button row, offering Cancel only where it is real.

        Returns the populated layout.
        """
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setMinimumHeight(CONTROL_HEIGHT)
        self.cancel_button.clicked.connect(self.operation_cancel)
        self.cancel_button.setVisible(self.operation in CANCELLABLE_OPERATIONS)
        self.cancel_button.setToolTip("Stop at the next safe point; finished work is kept.")
        self.hide_button = QPushButton("Hide", self)
        self.hide_button.setMinimumHeight(CONTROL_HEIGHT)
        self.hide_button.clicked.connect(self.operation_hide)
        self.hide_button.setToolTip("Keep working while this continues in the background.")
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("Accent")
        self.close_button.setMinimumHeight(CONTROL_HEIGHT)
        self.close_button.clicked.connect(self.operation_close_now)
        self.close_button.setVisible(False)
        self.close_button.setDefault(True)
        for button in (self.cancel_button, self.hide_button, self.close_button):
            row.addWidget(button)
        if self.operation not in CANCELLABLE_OPERATIONS:
            self.count_label.setText("This operation cannot be interrupted once started.")
        return row

    @Slot(int, object)
    def operation_progress(self, request_id: int, event: ProgressEvent) -> None:
        """Render one coalesced progress update for this request.

        request_id: the request the update belongs to.
        event: the latest progress event.
        Returns None. Updates for other requests are ignored, so a housekeeping
        read cannot repaint this dialog.
        """
        if request_id != self.request_id or not self.running:
            return
        if event.total > 0:
            self.fraction = event.fraction
            self.bar.setRange(0, PROGRESS_STEPS)
            self.bar.setValue(int(self.fraction * PROGRESS_STEPS))
            self.count_label.setText(f"{event.current} of {event.total}")
        if event.message:
            self.detail_label.setText(operations_shorten(event.message, MAX_DETAIL_CHARS))
        self.operation_tick()

    @Slot()
    def operation_tick(self) -> None:
        """Refresh the elapsed and estimated-remaining line."""
        if not self.running:
            return
        elapsed = monotonic() - self.started
        remaining = operations_remaining(elapsed, self.fraction)
        text = f"Elapsed {operations_format_duration(elapsed)}"
        self.timing_label.setText(f"{text}      {remaining}" if remaining else text)

    @Slot()
    def operation_cancel(self) -> None:
        """Ask the running operation to stop at its next safe checkpoint.

        Returns None. The request may have completed between the click and this
        slot, which the controller reports by raising; that is a finished run,
        not an error to show the user.
        """
        if not self.running or self.cancelling:
            return
        try:
            self.worker.worker_cancel(self.request_id)
        except ValueError:
            LOGGER.info("cancel arrived after request %s finished", self.request_id)
            return
        self.cancelling = True
        self.cancel_button.setEnabled(False)
        self.detail_label.setText("Stopping at the next safe point...")

    @Slot()
    def operation_hide(self) -> None:
        """Keep the operation running with the dialog out of the way."""
        if not self.running:
            self.operation_close_now()
            return
        self.hide()
        self.operation_status.emit(
            f"{operations_title(self.operation)} continues in the background.", False
        )

    @Slot()
    def operation_close_now(self) -> None:
        """Close and destroy a dialog whose operation has already finished."""
        self.running = False
        self.close()

    def operation_force_close(self) -> None:
        """Close during window shutdown, when the request is being cancelled anyway.

        Returns None. Called by the window so a modal dialog cannot outlive the
        shell it belongs to.
        """
        self.elapsed_timer.stop()
        self.operation_close_now()

    @Slot(object)
    def operation_reply(self, reply: WorkerResult | WorkerFailure) -> None:
        """Present the terminal outcome of this request.

        reply: a worker result, cancellation or failure.
        Returns None. Every accepted request produces exactly one of these, so
        this is the only place the dialog stops running.
        """
        if reply.request_id != self.request_id or not self.running:
            return
        self.running = False
        self.elapsed_timer.stop()
        self.bar.setRange(0, PROGRESS_STEPS)
        self.bar.setValue(PROGRESS_STEPS)
        self.cancel_button.setVisible(False)
        self.hide_button.setVisible(False)
        self.close_button.setVisible(True)
        if isinstance(reply, WorkerFailure):
            self.operation_report(
                f"{operations_title(self.operation)} failed: {reply.message}", [], sticky=True
            )
            return
        value = reply.value
        summary = operations_summary(self.operation, value)
        if reply.cancelled and not isinstance(value, (ImportResult, VerifyResult)):
            summary = f"{operations_title(self.operation)} was cancelled."
        self.operation_report(summary, operations_detail_lines(self.operation, value))
        self.operation_completed.emit(self.operation, value)

    def operation_report(self, summary: str, details: list[str], *, sticky: bool = False) -> None:
        """Show the final summary, re-opening the dialog when it carries problems.

        summary: the one-line outcome.
        details: individual error lines, which may be empty.
        sticky: whether the message must survive the routine status refreshes
            the shell issues after every mutation.
        Returns None. A hidden clean run is reported in the status bar and the
        dialog closes itself; a hidden run with errors comes back, because a
        list of failures must not be reduced to one replaceable status line.

        A hidden run's summary is always held: the status bar is the only place
        it is reported, and the import that produced it makes the shell re-read
        its counters, which would otherwise overwrite the summary immediately.
        """
        self.detail_label.setText(summary)
        self.timing_label.setText(f"Took {operations_format_duration(monotonic() - self.started)}")
        self.count_label.setText("")
        if details:
            shown = details[:MAX_ERROR_LINES]
            extra = len(details) - len(shown)
            text = "\n".join(shown)
            self.errors_label.setText(f"{text}\n...and {extra} more." if extra else text)
            self.errors_label.setVisible(True)
        self.operation_status.emit(summary, sticky or bool(details) or not self.isVisible())
        if self.isVisible():
            return
        if details:
            self.show()
            self.raise_()
        else:
            self.operation_close_now()

    def reject(self) -> None:
        """Treat Esc and the title-bar close as Hide while the operation runs.

        Returns None. ``QDialog.done`` destroys a ``WA_DeleteOnClose`` dialog,
        so a running operation must never reach it: the work would continue with
        nothing left to report it.
        """
        if self.running:
            self.operation_hide()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Refuse to close while the operation is still running; hide instead."""
        if self.running:
            event.ignore()
            self.operation_hide()
            return
        self.elapsed_timer.stop()
        super().closeEvent(event)
