"""Review pages: the deleted-on-phone report and the marks queue.

Both surfaces are lists of things the user is about to decide about, not grids
of photos, so they share one checkable list rather than the paged asset model.
The listings are bounded reads of a report the service already produces, and the
rows carry nothing but identifiers and text - no service objects reach a widget.

Neither page deletes anything by itself. Every button here either changes what
is selected, re-runs a read, or hands a described action to the window, which
routes it through the confirmation dialog.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.phone_diff import PhoneDiffResult
from ..service.marks import MarkSummary
from .gallery import gallery_format_size
from .theme import CONTROL_HEIGHT, GROUP_GAP, theme_font

LOGGER = logging.getLogger(__name__)

# A review list is a decision aid, not an export. Beyond this many rows the
# listing stops being readable and the CLI's report is the better tool.
MAX_REVIEW_ROWS = 500


@dataclass(frozen=True)
class ReviewRow:
    """One reviewable row: an identifier and the text describing it."""

    identifier: int
    label: str
    detail: str = ""


def review_phone_rows(result: object) -> list[ReviewRow]:
    """Describe the assets that are archived but gone from the phone.

    result: the worker's returned ``PhoneDiffResult``.
    Returns the rows, bounded to ``MAX_REVIEW_ROWS``. The identifier is the
    asset id, because this report is asset-scoped: the phone knows nothing about
    which archive copies exist.
    """
    if not isinstance(result, PhoneDiffResult):
        return []
    rows = []
    for item in result.items[:MAX_REVIEW_ROWS]:
        seen = item.last_seen_on_phone_at or "never recorded"
        detail = f"{gallery_format_size(item.size)} - last seen on phone {seen}"
        rows.append(ReviewRow(item.asset_id, item.original_name, detail))
    return rows


def review_phone_caption(result: object) -> str:
    """Summarise the deleted-on-phone report above its list.

    result: the worker's returned ``PhoneDiffResult``.
    Returns the caption text.
    """
    if not isinstance(result, PhoneDiffResult):
        return "Run a phone scan to find out what is no longer on the iPhone."
    if result.count == 0:
        return "Everything in the archive was still on the iPhone at the last scan."
    text = (
        f"{result.count} archived items were not on the iPhone at the last scan, "
        f"holding {gallery_format_size(result.total_bytes)}. Nothing happens automatically."
    )
    if result.count > MAX_REVIEW_ROWS:
        text = f"{text} Showing the first {MAX_REVIEW_ROWS}."
    return text


def review_mark_rows(marks: object) -> list[ReviewRow]:
    """Describe the staged deletion marks.

    marks: the worker's returned list of ``MarkSummary``.
    Returns the rows, bounded to ``MAX_REVIEW_ROWS``. The identifier is the mark
    id, so unmarking removes exactly the mark the user pointed at.
    """
    if not isinstance(marks, list):
        return []
    rows = []
    for mark in marks[:MAX_REVIEW_ROWS]:
        if not isinstance(mark, MarkSummary):
            continue
        label = f"{mark.target_type.capitalize()} {mark.target_id}"
        parts = [part for part in (mark.reason, mark.marked_at) if part]
        rows.append(ReviewRow(mark.mark_id, label, " - ".join(parts)))
    return rows


def review_mark_caption(marks: object) -> str:
    """Summarise the marks queue above its list.

    marks: the worker's returned list of ``MarkSummary``.
    Returns the caption text, which always states that nothing has been deleted.
    """
    if not isinstance(marks, list) or not marks:
        return "Nothing is marked. Marking stages a deletion; it never deletes."
    count = len(marks)
    albums = sum(
        1 for mark in marks if isinstance(mark, MarkSummary) and mark.target_type == "album"
    )
    text = f"{count} marked - nothing has been deleted yet."
    if albums:
        text = f"{text} {albums} of them are whole albums."
    return text


class ReviewList(QWidget):
    """A checkable list of identified rows, with a live selection count."""

    review_selection_changed = Signal(int)

    def __init__(self, empty_text: str, parent: QWidget | None = None) -> None:
        """Build an empty list.

        empty_text: what to show when there are no rows.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.empty_text = empty_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("ReviewList")
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemChanged.connect(self.review_item_changed)
        self.empty_label = QLabel(empty_text, self)
        self.empty_label.setObjectName("PlaceholderLabel")
        self.empty_label.setProperty("role", "secondary")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(self.list_widget, 1)
        self.rows: list[ReviewRow] = []
        self.review_set_rows([])

    def review_set_rows(self, rows: Sequence[ReviewRow]) -> None:
        """Replace the listing, dropping any previous check state.

        rows: the rows to display.
        Returns None. Check state is deliberately not carried across a refresh:
        the rows may describe different assets, and silently re-checking a
        replaced row would hand a destructive action a target nobody chose.
        """
        self.rows = list(rows)
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for row in self.rows:
            text = f"{row.label}\n{row.detail}" if row.detail else row.label
            item = QListWidgetItem(text, self.list_widget)
            item.setData(Qt.ItemDataRole.UserRole, row.identifier)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.list_widget.blockSignals(False)
        self.empty_label.setText(self.empty_text)
        self.empty_label.setVisible(not self.rows)
        self.list_widget.setVisible(bool(self.rows))
        self.review_selection_changed.emit(0)

    def review_item_changed(self, item: QListWidgetItem) -> None:
        """Report the new checked count when a row is ticked.

        item: the row whose check state changed.
        Returns None.
        """
        self.review_selection_changed.emit(len(self.review_checked_ids()))

    def review_checked_ids(self) -> list[int]:
        """Return the identifiers of the checked rows, in display order."""
        checked = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                identifier = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(identifier, int):
                    checked.append(identifier)
        return checked

    def review_set_all(self, checked: bool) -> None:
        """Check or clear every row.

        checked: True to select all, False to clear the selection.
        Returns None.
        """
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.list_widget.blockSignals(True)
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item is not None:
                item.setCheckState(state)
        self.list_widget.blockSignals(False)
        self.review_selection_changed.emit(len(self.review_checked_ids()))


class ReviewPage(QWidget):
    """A page header, a checkable list and a footer of actions."""

    review_action = Signal(str)

    def __init__(
        self,
        title: str,
        empty_text: str,
        actions: Sequence[tuple[str, str, bool]],
        parent: QWidget | None = None,
    ) -> None:
        """Compose the page.

        title: the page heading.
        empty_text: what the list shows when it is empty.
        actions: ``(key, label, needs_selection)`` triples for the footer.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ReviewPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.title_label = QLabel(title, self)
        self.title_label.setFont(theme_font("title"))
        self.caption_label = QLabel("", self)
        self.caption_label.setProperty("role", "secondary")
        self.caption_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.caption_label)
        self.review_list = ReviewList(empty_text, self)
        layout.addWidget(self.review_list, 1)

        self.count_label = QLabel("Nothing selected", self)
        self.count_label.setFont(theme_font("caption"))
        self.count_label.setProperty("role", "secondary")
        layout.addWidget(self.count_label)

        footer = QHBoxLayout()
        footer.setSpacing(GROUP_GAP)
        footer.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        self.needs_selection: dict[str, bool] = {}
        for key, label, needs_selection in actions:
            button = QPushButton(label, self)
            button.setFixedHeight(CONTROL_HEIGHT)
            if key in {"purge", "commit-purge"}:
                button.setObjectName("DangerButton")
            button.clicked.connect(lambda checked=False, name=key: self.review_action.emit(name))
            footer.addWidget(button)
            self.buttons[key] = button
            self.needs_selection[key] = needs_selection
        layout.addLayout(footer)
        # Connected only after the footer exists: a selection change enables and
        # disables those buttons, so a listing filled before they were built
        # would raise inside Qt's event loop.
        self.review_list.review_selection_changed.connect(self.review_selection_changed)
        self.review_selection_changed(0)

    def review_selection_changed(self, count: int) -> None:
        """Re-label the count line and enable only the applicable actions.

        count: how many rows are checked.
        Returns None. An action that needs a selection is disabled without one,
        so no button can be pressed into doing nothing.
        """
        self.count_label.setText("Nothing selected" if not count else f"{count} selected")
        for key, button in self.buttons.items():
            button.setEnabled(bool(count) if self.needs_selection[key] else True)

    def review_set_rows(self, rows: Sequence[ReviewRow], caption: str) -> None:
        """Replace the listing and its caption.

        rows: the rows to display.
        caption: the summary line under the heading.
        Returns None.
        """
        self.caption_label.setText(caption)
        self.review_list.review_set_rows(rows)

    def review_set_default_action(self, key: str) -> None:
        """Suggest one action by making it the page's default button.

        key: the action key to suggest, ignored when this page has no such
            button.
        Returns None. Suggesting is all a preference may do here: the button
        still has to be pressed, and a permanent action still has to be
        confirmed with the typed word afterwards.
        """
        for name, button in self.buttons.items():
            button.setDefault(name == key)

    def review_checked_ids(self) -> list[int]:
        """Return the identifiers of the checked rows."""
        return self.review_list.review_checked_ids()

    def review_set_all(self, checked: bool) -> None:
        """Check or clear every row.

        checked: True to select all, False to clear.
        Returns None.
        """
        self.review_list.review_set_all(checked)


class DeletedPhonePage(ReviewPage):
    """Sketch section 3: what is gone from the phone but safe in the archive."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the deleted-on-phone review page.

        parent: optional parent widget.
        """
        super().__init__(
            "Deleted from phone",
            "Nothing to review. Scan the phone to refresh this list.",
            (
                ("select-all", "Select all", False),
                ("rescan", "Refresh", False),
                ("keep", "Keep in archive", True),
                ("recycle", "Move to Deleted folder", True),
                ("purge", "Delete from archive...", True),
            ),
            parent,
        )


class MarksPage(ReviewPage):
    """Sketch section 6: the staged marks queue, where nothing is deleted yet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the marks queue page.

        parent: optional parent widget.
        """
        super().__init__(
            "Marked",
            "Nothing is marked. Select photos and choose \u201cMark for delete\u201d.",
            (
                ("select-all", "Select all", False),
                ("unmark", "Unmark", True),
                ("clear", "Clear all marks", False),
                ("commit-recycle", "Move to Deleted folder", False),
                ("commit-purge", "Delete permanently...", False),
            ),
            parent,
        )
