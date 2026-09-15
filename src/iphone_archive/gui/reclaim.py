"""Sketch section 4: the reclaim review, shown only after a dry run.

Reclamation is the one operation that deletes something outside the archive, so
the flow is deliberately two-stage. Pressing "Free up space" runs
``app_service_reclaim`` with ``confirmed=False``: a non-destructive pass that
re-verifies each candidate and reports what it would delete. Only that report
opens this dialog, and only this dialog's button can reach the confirmation that
performs a real deletion.

The dialog never decides anything itself. It shows the candidates the service
found, lets the user narrow them, and hands the chosen asset ids back. The
service re-checks them again at execution, because a preview is not an
authorization.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.reclaim import ReclaimResult
from .gallery import gallery_format_size
from .review import MAX_REVIEW_ROWS, ReviewList, ReviewRow
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)

RECLAIM_DIALOG_SIZE = (620, 520)


def reclaim_rows(result: object) -> list[ReviewRow]:
    """Describe the phone files a dry run found safe to delete.

    result: the worker's returned ``ReclaimResult``.
    Returns the rows, bounded to ``MAX_REVIEW_ROWS``. Only candidates appear:
    anything that failed its re-check was already excluded by the service and
    must not be offered here as if it were a choice.
    """
    if not isinstance(result, ReclaimResult):
        return []
    return [
        ReviewRow(
            candidate.asset_id,
            candidate.original_name,
            f"{gallery_format_size(candidate.size)} - {candidate.phone_path}",
        )
        for candidate in result.candidates[:MAX_REVIEW_ROWS]
    ]


def reclaim_caption(result: object) -> str:
    """Summarise what the dry run found.

    result: the worker's returned ``ReclaimResult``.
    Returns the caption text, naming the skipped items rather than hiding them:
    a file that failed its re-check is the most important thing on this screen.
    """
    if not isinstance(result, ReclaimResult):
        return "The reclaim preview could not be read."
    count = len(result.candidates)
    text = (
        f"Safe to delete from the phone: {count} items, "
        f"{gallery_format_size(result.reclaimable_bytes)}."
    )
    if result.skipped_count:
        text = (
            f"{text} {result.skipped_count} were skipped because they are not archived "
            "or did not pass a fresh integrity check."
        )
    if count > MAX_REVIEW_ROWS:
        text = f"{text} Showing the first {MAX_REVIEW_ROWS}."
    return text


def reclaim_selected_bytes(result: object, asset_ids: list[int]) -> int:
    """Total the phone space a subset of candidates occupies.

    result: the dry run's ``ReclaimResult``.
    asset_ids: the assets the user checked.
    Returns the byte total, ignoring ids the report does not contain.
    """
    if not isinstance(result, ReclaimResult):
        return 0
    wanted = set(asset_ids)
    return sum(candidate.size for candidate in result.candidates if candidate.asset_id in wanted)


class ReclaimDialog(QDialog):
    """The dry run's report, and the only route to a real phone-side deletion."""

    reclaim_requested = Signal(object)

    def __init__(self, result: object, parent: QWidget | None = None) -> None:
        """Present a completed dry run.

        result: the worker's returned ``ReclaimResult``.
        parent: the window this dialog belongs to.
        """
        super().__init__(parent)
        self.setObjectName("ReclaimDialog")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Free space on iPhone")
        self.resize(*RECLAIM_DIALOG_SIZE)
        # Not "result": QDialog.result() is the dialog's accepted/rejected code,
        # and shadowing it with the preview would break every caller that asks
        # whether the user confirmed.
        self.preview = result

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        heading = QLabel("Free space on iPhone", self)
        heading.setFont(theme_font("subtitle"))
        layout.addWidget(heading)
        note = QLabel(
            "Only photos that are archived and pass a fresh integrity check are offered "
            "here. Your archive is never modified by this operation.",
            self,
        )
        note.setWordWrap(True)
        note.setProperty("role", "secondary")
        layout.addWidget(note)
        self.caption = QLabel(reclaim_caption(result), self)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

        self.review_list = ReviewList("Nothing on the phone can be safely deleted yet.", self)
        rows = reclaim_rows(result)
        self.review_list.review_set_rows(rows)
        layout.addWidget(self.review_list, 1)

        footer = QHBoxLayout()
        footer.setSpacing(GROUP_GAP)
        self.select_button = QPushButton("Select all", self)
        self.select_button.setFixedHeight(CONTROL_HEIGHT)
        self.select_button.setEnabled(bool(rows))
        self.select_button.clicked.connect(lambda: self.review_list.review_set_all(True))
        footer.addWidget(self.select_button)
        footer.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setFixedHeight(CONTROL_HEIGHT)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.delete_button = QPushButton("Delete from iPhone...", self)
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setFixedHeight(CONTROL_HEIGHT)
        self.delete_button.clicked.connect(self.reclaim_request)
        footer.addWidget(self.delete_button)
        layout.addLayout(footer)
        # Connected only once the footer exists: filling the list emits a
        # selection change, and a slot that touches a button built later would
        # raise inside Qt's event loop on the way to opening the dialog.
        self.review_list.review_selection_changed.connect(self.reclaim_selection_changed)
        self.reclaim_selection_changed(0)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()

    def reclaim_selection_changed(self, count: int) -> None:
        """Re-label the delete button for the current selection.

        count: how many candidates are checked.
        Returns None. The button names the number it would delete, so the count
        the user reads is the count the confirmation will repeat.
        """
        self.delete_button.setEnabled(bool(count))
        if not count:
            self.delete_button.setText("Delete from iPhone...")
            return
        size = gallery_format_size(reclaim_selected_bytes(self.preview, self.review_list_ids()))
        self.delete_button.setText(f"Delete {count} items from iPhone ({size})...")

    def review_list_ids(self) -> list[int]:
        """Return the checked candidate asset ids."""
        return self.review_list.review_checked_ids()

    def reclaim_request(self) -> None:
        """Hand the chosen candidates to the window and close.

        Returns None. Nothing is deleted here; the window still has to pass the
        typed confirmation before a single phone file is touched.
        """
        asset_ids = self.review_list_ids()
        if not asset_ids:
            return
        self.reclaim_requested.emit(asset_ids)
        self.accept()
