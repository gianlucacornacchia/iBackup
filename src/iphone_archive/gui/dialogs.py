"""Small input and report dialogs used by the safe operations.

These are deliberately non-blocking: they are shown and their ``accepted``
signal is connected, rather than being run with ``exec``. A nested event loop
inside a GUI that already owns a worker thread, a preview pool and a paged model
is an easy way to process a reply in the middle of another operation, and it
hangs a headless test suite.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.dedup import DedupResult
from .gallery import gallery_format_size
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)

MOVE_DIALOG_SIZE = (440, 190)
MARK_SCOPE_DIALOG_SIZE = (460, 190)
# The service's mark target types, named here so the dialog, the window and the
# parity map all spell the copy-scoped and asset-scoped marks the same way.
MARK_SCOPE_COPY = "file"
MARK_SCOPE_ASSET = "asset"
MARK_SCOPE_ALBUM = "album"
REPORT_DIALOG_SIZE = (640, 460)
# A report is a summary, not an export: the biggest groups are what matters and
# the full listing belongs to the CLI's `dedup` command.
MAX_REPORT_GROUPS = 50


def dialogs_dedup_lines(result: object) -> list[str]:
    """Compose the duplicate report's body text.

    result: the worker's returned ``DedupResult``.
    Returns the report lines, largest wasted space first. Nothing here deletes
    anything; the report only explains where multi-album copies are costing
    storage.
    """
    if not isinstance(result, DedupResult):
        return ["The duplicate report could not be read."]
    groups = sorted(result.multi_copy_groups, key=lambda group: group.extra_bytes, reverse=True)
    lines = [
        f"Assets: {result.asset_count}",
        f"Stored copies: {result.file_count}",
        f"Content stored in more than one album: {len(groups)}",
        f"Storage used by the extra copies: {gallery_format_size(result.reclaimable_bytes)}",
        "",
        "Nothing is deleted by this report. Extra copies exist because an asset",
        "belongs to more than one album, which is preserved on purpose.",
        "",
    ]
    for group in groups[:MAX_REPORT_GROUPS]:
        lines.append(
            f"{group.original_name} - {group.copy_count} copies - "
            f"{gallery_format_size(group.extra_bytes)} extra"
        )
        lines.extend(f"    {path}" for path in group.paths)
    if len(groups) > MAX_REPORT_GROUPS:
        lines.append(f"...and {len(groups) - MAX_REPORT_GROUPS} more groups.")
    return lines


class ReportDialog(QDialog):
    """A read-only text report with a single Close button."""

    def __init__(self, title: str, lines: Sequence[str], parent: QWidget | None = None) -> None:
        """Show a report that changes nothing in the archive.

        title: the dialog heading.
        lines: the report body, one entry per line.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("ReportDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("iPhone Archive")
        self.resize(*REPORT_DIALOG_SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        heading = QLabel(title, self)
        heading.setFont(theme_font("subtitle"))
        layout.addWidget(heading)
        self.body = QPlainTextEdit(self)
        self.body.setObjectName("ReportBody")
        self.body.setReadOnly(True)
        self.body.setPlainText("\n".join(lines))
        layout.addWidget(self.body, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close_button = QPushButton("Close", self)
        close_button.setObjectName("Accent")
        close_button.setMinimumHeight(CONTROL_HEIGHT)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        layout.addLayout(row)


class MarkScopeDialog(QDialog):
    """Ask whether a mark covers one album's copy or every copy of the asset."""

    # The chosen scope travels with the signal for the same reason the move
    # dialog carries its album name: the dialog deletes itself on close.
    scope_chosen = Signal(str)

    def __init__(self, album_name: str, parent: QWidget | None = None) -> None:
        """Offer the copy-scoped and asset-scoped marks the CLI also offers.

        album_name: the album being browsed, named so the narrow choice is
            unambiguous about which copy it covers.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("MarkScopeDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("iPhone Archive")
        self.resize(*MARK_SCOPE_DIALOG_SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        heading = QLabel("Mark for delete", self)
        heading.setFont(theme_font("subtitle"))
        layout.addWidget(heading)
        caption = QLabel(
            "This photo or video is stored in more than one place. Marking stages "
            "a decision only; nothing is deleted until you commit the marks.",
            self,
        )
        caption.setFont(theme_font("caption"))
        caption.setProperty("role", "secondary")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        layout.addStretch(1)
        layout.addLayout(self.mark_scope_build_buttons(album_name))

    def mark_scope_build_buttons(self, album_name: str) -> QHBoxLayout:
        """Build the cancel/copy/asset row.

        album_name: the album being browsed.
        Returns the populated layout. The narrower scope is the default button
        because it is the one that leaves the rest of the archive untouched.
        """
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)
        row.addStretch(1)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.setMinimumHeight(CONTROL_HEIGHT)
        cancel_button.clicked.connect(self.reject)
        self.asset_button = QPushButton("Every copy", self)
        self.asset_button.setMinimumHeight(CONTROL_HEIGHT)
        self.asset_button.setToolTip("Mark the asset itself, including copies in other albums.")
        self.asset_button.clicked.connect(lambda: self.mark_scope_choose(MARK_SCOPE_ASSET))
        self.copy_button = QPushButton(f'Only in "{album_name}"', self)
        self.copy_button.setObjectName("Accent")
        self.copy_button.setMinimumHeight(CONTROL_HEIGHT)
        self.copy_button.setDefault(True)
        self.copy_button.setToolTip("Mark only the copy stored in the album you are browsing.")
        self.copy_button.clicked.connect(lambda: self.mark_scope_choose(MARK_SCOPE_COPY))
        row.addWidget(cancel_button)
        row.addWidget(self.asset_button)
        row.addWidget(self.copy_button)
        return row

    def mark_scope_choose(self, scope: str) -> None:
        """Report the chosen scope and close.

        scope: ``file`` for the browsed copy, ``asset`` for every copy.
        Returns None.
        """
        self.scope_chosen.emit(scope)
        self.accept()


class MoveToAlbumDialog(QDialog):
    """Ask for the destination album of a move, offering the existing albums."""

    # The name travels with the signal rather than being read back from the
    # dialog: this dialog deletes itself on close, so a slot that reached back
    # into it would be racing its own destruction.
    move_requested = Signal(str)

    def __init__(
        self,
        count: int,
        albums: Sequence[str],
        scoped: bool,
        parent: QWidget | None = None,
    ) -> None:
        """Build the destination prompt.

        count: how many assets the move applies to.
        albums: existing album names, offered as suggestions.
        scoped: whether the move is restricted to the copies in the album being
            browsed, which is stated explicitly so an album view never silently
            moves every copy of an asset.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("MoveDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("iPhone Archive")
        self.resize(*MOVE_DIALOG_SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        heading = QLabel("Move to album", self)
        heading.setFont(theme_font("subtitle"))
        layout.addWidget(heading)
        noun = "photo or video" if count == 1 else "photos and videos"
        scope_text = (
            "Only the copies stored in the album you are browsing are moved."
            if scoped
            else "Every active copy of the selection is moved."
        )
        self.caption = QLabel(f"Moving {count} {noun}. {scope_text}", self)
        self.caption.setFont(theme_font("caption"))
        self.caption.setProperty("role", "secondary")
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        self.album_box = QComboBox(self)
        self.album_box.setEditable(True)
        self.album_box.setMinimumHeight(CONTROL_HEIGHT)
        self.album_box.addItems(list(albums))
        self.album_box.setCurrentText("")
        self.album_box.setToolTip("Pick an existing album or type a new name.")
        layout.addWidget(self.album_box)
        layout.addStretch(1)
        layout.addLayout(self.move_build_buttons())

    def move_build_buttons(self) -> QHBoxLayout:
        """Build the confirm/cancel row.

        Returns the populated layout.
        """
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)
        row.addStretch(1)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.setMinimumHeight(CONTROL_HEIGHT)
        cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("Move", self)
        self.confirm_button.setObjectName("Accent")
        self.confirm_button.setMinimumHeight(CONTROL_HEIGHT)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.move_confirm)
        row.addWidget(cancel_button)
        row.addWidget(self.confirm_button)
        return row

    def move_album_name(self) -> str:
        """Return the destination album name the user chose.

        Returns the trimmed name, which may be empty.
        """
        return self.album_box.currentText().strip()

    def move_confirm(self) -> None:
        """Accept only once a destination has actually been named.

        Returns None. An empty name would otherwise reach the service as an
        invalid album and fail after the dialog had already closed.
        """
        name = self.move_album_name()
        if not name:
            self.album_box.setToolTip("Enter an album name to move into.")
            self.album_box.setFocus()
            return
        self.move_requested.emit(name)
        self.accept()
