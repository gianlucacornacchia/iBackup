"""Review pages: the deleted-on-phone report and the marks queue.

Both surfaces are bounded reads of a report the service already produces - at
most a few hundred rows - so they use a plain ``QStandardItemModel`` rather
than the gallery's paged asset model. The tile rendering itself is not
reinvented: rows are painted by the same ``gallery.TileDelegate`` the photo
grid uses, through the same ``AssetRole`` data roles, so a thumbnail here
looks and crops exactly like it does everywhere else in the app, and
"checked" is the view's own click-to-select rather than a separate checkbox.

Neither page deletes anything by itself. Every button here either changes what
is selected, re-runs a read, or hands a described action to the window, which
routes it through the confirmation dialog.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.phone_diff import PhoneDiffResult
from ..service.marks import MarkSummary
from .gallery import REPAINT_INTERVAL_MS, TILE_SPACING, TileDelegate, gallery_format_size
from .models import AssetRole
from .previews import PreviewLoader
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
    sha256: str | None = None
    relative_path: str | None = None


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
        path = item.paths[0] if item.paths else None
        rows.append(ReviewRow(item.asset_id, item.original_name, detail, item.sha256, path))
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
        rows.append(
            ReviewRow(
                mark.mark_id, label, " - ".join(parts), mark.sha256, mark.relative_path
            )
        )
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
    """A selectable list of identified rows, with a live selection count.

    This reuses the photo gallery's own tile delegate and grid layout rather
    than a parallel look: rows are laid out in a ``QListView`` icon grid, and
    each tile is painted by ``gallery.TileDelegate`` from the same
    ``AssetRole`` data roles the gallery uses, so a thumbnail here is the same
    size, has the same rounded corners and crops the same way as everywhere
    else in the app. "Checked" is the view's own multi-selection (click, or
    ctrl/shift-click to extend) rather than a separate checkbox, matching how
    the gallery itself marks a tile as selected.
    """

    review_selection_changed = Signal(int)

    def __init__(
        self,
        empty_text: str,
        previews: PreviewLoader | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build an empty list.

        empty_text: what to show when there are no rows.
        previews: the shared preview loader, or None to show rows without
            thumbnails (e.g. in a test harness that has no archive open).
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.empty_text = empty_text
        self.previews = previews
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.list_view = QListView(self)
        self.list_view.setObjectName("ReviewList")
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setFlow(QListView.Flow.LeftToRight)
        self.list_view.setWrapping(True)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSpacing(TILE_SPACING)
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model = QStandardItemModel(self)
        self.list_view.setModel(self.model)
        if previews is not None:
            self.list_view.setItemDelegate(TileDelegate(previews, self.list_view))
            previews.preview_ready.connect(self.review_preview_settled)
            previews.preview_failed.connect(self.review_preview_settled)
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.setInterval(REPAINT_INTERVAL_MS)
        self.repaint_timer.timeout.connect(self.review_repaint)
        selection_model = self.list_view.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self.review_selection_emit)
        self.empty_label = QLabel(empty_text, self)
        self.empty_label.setObjectName("PlaceholderLabel")
        self.empty_label.setProperty("role", "secondary")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The empty state has to keep claiming the list's share of the page
        # even though a short label has a tiny sizeHint on its own - otherwise
        # an empty review (the common first-run state) collapses to a sliver
        # and the surplus space gets handed to the header labels instead.
        self.empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(self.list_view, 1)
        self.rows: list[ReviewRow] = []
        self.review_set_rows([])

    def review_set_rows(self, rows: Sequence[ReviewRow]) -> None:
        """Replace the listing, dropping any previous selection.

        rows: the rows to display.
        Returns None. Selection is deliberately not carried across a refresh:
        the rows may describe different assets, and silently re-selecting a
        replaced row would hand a destructive action a target nobody chose.
        """
        self.rows = list(rows)
        self.model.clear()
        for row in self.rows:
            item = QStandardItem()
            item.setData(row.identifier, int(AssetRole.ASSET_ID))
            item.setData(row.label, int(AssetRole.ORIGINAL_NAME))
            item.setData(row.label, Qt.ItemDataRole.DisplayRole)
            item.setData(row.sha256 or "", int(AssetRole.SHA256))
            item.setData((row.relative_path,) if row.relative_path else (), int(AssetRole.PATHS))
            item.setToolTip(f"{row.label}\n{row.detail}" if row.detail else row.label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.model.appendRow(item)
        self.empty_label.setText(self.empty_text)
        self.empty_label.setVisible(not self.rows)
        self.list_view.setVisible(bool(self.rows))
        self.review_selection_changed.emit(0)

    def review_preview_settled(self, sha256: str, size: int, error: str = "") -> None:
        """Schedule a coalesced repaint when any thumbnail finishes.

        sha256: unused; repainting the whole viewport is cheaper than mapping
            the hash back to a row for a bounded, on-screen list.
        size: unused; both `preview_ready` and `preview_failed` carry it.
        error: unused; present so one slot can serve both signals.
        Returns None.
        """
        del sha256, size, error
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()

    def review_repaint(self) -> None:
        """Repaint the visible tiles after a burst of finished renders."""
        viewport = self.list_view.viewport()
        if viewport is not None:
            viewport.update()

    def review_selection_emit(self, *_args: object) -> None:
        """Report the new selected count after the view's selection changes."""
        self.review_selection_changed.emit(len(self.review_checked_ids()))

    def review_checked_ids(self) -> list[int]:
        """Return the identifiers of the selected rows, in display order."""
        selection_model = self.list_view.selectionModel()
        if selection_model is None:
            return []
        checked = []
        for index in sorted(selection_model.selectedIndexes(), key=lambda index: index.row()):
            identifier = index.data(int(AssetRole.ASSET_ID))
            if isinstance(identifier, int):
                checked.append(identifier)
        return checked

    def review_set_all(self, checked: bool) -> None:
        """Select or clear every row.

        checked: True to select all, False to clear the selection.
        Returns None.
        """
        selection_model = self.list_view.selectionModel()
        if selection_model is None:
            return
        if checked:
            self.list_view.selectAll()
        else:
            selection_model.clearSelection()
        self.review_selection_emit()


class ReviewPage(QWidget):
    """A page header, a checkable list and a footer of actions."""

    review_action = Signal(str)

    def __init__(
        self,
        title: str,
        empty_text: str,
        actions: Sequence[tuple[str, str, bool]],
        previews: PreviewLoader | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Compose the page.

        title: the page heading.
        empty_text: what the list shows when it is empty.
        actions: ``(key, label, needs_selection)`` triples for the footer.
        previews: the shared preview loader, or None to show rows without
            thumbnails.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ReviewPage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self.review_list = ReviewList(empty_text, previews, self)
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

    def __init__(
        self, previews: PreviewLoader | None = None, parent: QWidget | None = None
    ) -> None:
        """Build the deleted-on-phone review page.

        previews: the shared preview loader, or None to show rows without
            thumbnails.
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
            previews,
            parent,
        )


class MarksPage(ReviewPage):
    """Sketch section 6: the staged marks queue, where nothing is deleted yet."""

    def __init__(
        self, previews: PreviewLoader | None = None, parent: QWidget | None = None
    ) -> None:
        """Build the marks queue page.

        previews: the shared preview loader, or None to show rows without
            thumbnails.
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
            previews,
            parent,
        )
