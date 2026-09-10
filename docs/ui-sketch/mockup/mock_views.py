"""Page mocks: deleted-on-phone review, reclaim phone space, marks queue.

MOCK ONLY. These correspond to ui-sketch/README.md sections 3, 4 and 6. They
present the same choices and safety wording the real views must offer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mock_data import MockArchive, mock_data_format_size
from mock_dialogs import ConfirmDialog, dialogs_caption, dialogs_heading
from mock_tokens import tokens_font
from mock_widgets import PhotoGrid


class DeletedOnPhoneView(QWidget):
    """Review assets that are gone from the phone but still in the archive."""

    action_taken = Signal(str)

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Build the review page with its three per-item choices."""
        super().__init__(parent)
        self.archive = archive

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        count = len(archive.deleted_on_phone_ids)
        layout.addWidget(
            dialogs_heading(f"Deleted on phone - {count} photos still safe in your archive", "title")
        )
        layout.addWidget(
            dialogs_caption(
                "These are in your archive but no longer on the iPhone. "
                "Nothing happens automatically."
            )
        )

        top_row = QHBoxLayout()
        top_row.addWidget(dialogs_caption("Last seen on phone: 2026-08-14"))
        top_row.addStretch(1)
        for label in ("Select all", "Rescan phone"):
            button = QPushButton(label)
            button.setObjectName("Command")
            top_row.addWidget(button)
            if label == "Select all":
                button.clicked.connect(lambda: self.grid.selectAll())
        layout.addLayout(top_row)

        self.grid = PhotoGrid(archive)
        self.grid.photo_grid_show(archive.mock_archive_assets_for("deleted-phone"))
        self.grid.selection_changed.connect(self.deleted_on_phone_view_update)
        layout.addWidget(self.grid, 1)

        self.action_bar = QFrame()
        self.action_bar.setObjectName("Card")
        bar = QHBoxLayout(self.action_bar)
        bar.setContentsMargins(12, 8, 12, 8)
        self.summary_label = QLabel("Nothing selected")
        self.summary_label.setFont(tokens_font("body_strong"))
        bar.addWidget(self.summary_label)
        bar.addStretch(1)

        self.keep_button = QPushButton("Keep in archive")
        self.keep_button.setObjectName("Command")
        self.keep_button.clicked.connect(lambda: self.deleted_on_phone_view_keep())
        bar.addWidget(self.keep_button)

        self.move_button = QPushButton("Move to Deleted folder")
        self.move_button.setObjectName("Accent")
        self.move_button.clicked.connect(self.deleted_on_phone_view_move)
        bar.addWidget(self.move_button)

        self.purge_button = QPushButton("Delete from archive...")
        self.purge_button.setObjectName("Destructive")
        self.purge_button.clicked.connect(self.deleted_on_phone_view_purge)
        bar.addWidget(self.purge_button)

        layout.addWidget(self.action_bar)
        self.deleted_on_phone_view_update([])

    def deleted_on_phone_view_update(self, assets: list) -> None:
        """Enable the actions only when something is selected.

        assets: currently selected assets.
        """
        has_selection = bool(assets)
        total = sum(asset.size for asset in assets)
        self.summary_label.setText(
            f"{len(assets)} selected - {mock_data_format_size(total)}"
            if has_selection
            else "Nothing selected"
        )
        for button in (self.keep_button, self.move_button, self.purge_button):
            button.setEnabled(has_selection)

    def deleted_on_phone_view_keep(self) -> None:
        """Dismiss the selection without changing anything."""
        self.grid.clearSelection()
        self.action_taken.emit("Kept in archive - nothing changed")

    def deleted_on_phone_view_move(self) -> None:
        """Move the selection to the reversible Deleted folder."""
        count = len(self.grid.photo_grid_selected_assets())
        self.action_taken.emit(f"Moved {count} item(s) to the Deleted folder (reversible)")

    def deleted_on_phone_view_purge(self) -> None:
        """Permanently delete the selection, behind the confirmation dialog."""
        assets = self.grid.photo_grid_selected_assets()
        dialog = ConfirmDialog(
            f"Delete {len(assets)} photos from the archive?",
            "This is permanent and cannot be undone.",
            sum(asset.size for asset in assets),
            tip='"Move to Deleted folder" is reversible.',
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.action_taken.emit(f"Permanently deleted {len(assets)} item(s) from the archive")


class MarksView(QWidget):
    """Queue of items marked for deletion; nothing is deleted until committed."""

    action_taken = Signal(str)

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Build the marks list and its commit actions."""
        super().__init__(parent)
        self.archive = archive

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        marks = archive.mock_archive_assets_for("marked")
        layout.addWidget(
            dialogs_heading(
                f"Marked for delete - {len(marks)} items (nothing has been deleted yet)", "title"
            )
        )

        self.table = QTableWidget(len(marks) + 1, 4)
        self.table.setHorizontalHeaderLabels(["Item", "Album", "Reason", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 90)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)

        for row, asset in enumerate(marks):
            album = asset.albums[0] if asset.albums else "_Unsorted"
            self.table.setItem(row, 0, QTableWidgetItem(asset.name))
            self.table.setItem(row, 1, QTableWidgetItem(album))
            self.table.setItem(row, 2, QTableWidgetItem(asset.marked_reason))
            self.marks_view_add_unmark(row)
        # A whole marked album, showing that marks are not only per asset.
        last = len(marks)
        self.table.setItem(last, 0, QTableWidgetItem('Album "Screenshots" (174 items)'))
        self.table.setItem(last, 1, QTableWidgetItem("-"))
        self.table.setItem(last, 2, QTableWidgetItem("whole album"))
        self.marks_view_add_unmark(last)
        layout.addWidget(self.table, 1)

        bar = QFrame()
        bar.setObjectName("Card")
        row_layout = QHBoxLayout(bar)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.addWidget(dialogs_caption("Marks are reversible until you commit them."))
        row_layout.addStretch(1)
        clear_button = QPushButton("Clear all marks")
        clear_button.setObjectName("Command")
        clear_button.clicked.connect(lambda: self.action_taken.emit("Cleared all marks"))
        row_layout.addWidget(clear_button)
        move_button = QPushButton("Move to Deleted folder")
        move_button.setObjectName("Accent")
        move_button.clicked.connect(self.marks_view_move)
        row_layout.addWidget(move_button)
        delete_button = QPushButton("Delete permanently...")
        delete_button.setObjectName("Destructive")
        delete_button.clicked.connect(self.marks_view_commit)
        row_layout.addWidget(delete_button)
        layout.addWidget(bar)

    def marks_view_add_unmark(self, row: int) -> None:
        """Add an Unmark button to a table row.

        row: the row index to attach the button to.
        """
        button = QPushButton("Unmark")
        button.setObjectName("Command")
        button.clicked.connect(lambda: self.action_taken.emit("Unmarked 1 item"))
        self.table.setCellWidget(row, 3, button)

    def marks_view_move(self) -> None:
        """Commit the marks reversibly into the Deleted folder."""
        self.action_taken.emit("Moved marked items to the Deleted folder (reversible)")

    def marks_view_commit(self) -> None:
        """Commit the marks permanently, behind the confirmation dialog."""
        marks = self.archive.mock_archive_assets_for("marked")
        dialog = ConfirmDialog(
            f"Delete {len(marks)} marked items permanently?",
            "This is permanent and cannot be undone.",
            sum(asset.size for asset in marks),
            tip='"Move to Deleted folder" is reversible.',
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.action_taken.emit(f"Permanently deleted {len(marks)} marked item(s)")


class ReclaimWindow(QDialog):
    """Free space on the phone; opens in dry run and never modifies the archive."""

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Build the reclaim candidate list with its safety framing."""
        super().__init__(parent)
        self.archive = archive
        self.setWindowTitle("Free space on iPhone")
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(dialogs_heading("Free space on iPhone", "title"))
        layout.addWidget(
            dialogs_caption(
                "Only photos that are archived AND pass a fresh integrity check are offered "
                "here. Your archive is never modified by this operation."
            )
        )

        candidates = [a for a in archive.assets.values() if a.on_phone][:60]
        safe = candidates[:-3]
        unsafe = candidates[-3:]
        summary = QFrame()
        summary.setObjectName("Card")
        summary_row = QHBoxLayout(summary)
        summary_row.setContentsMargins(12, 10, 12, 10)
        safe_label = QLabel(
            f"Safe to delete from phone: {len(safe)} items - "
            f"{mock_data_format_size(sum(a.size for a in safe))}"
        )
        safe_label.setFont(tokens_font("body_strong"))
        summary_row.addWidget(safe_label)
        summary_row.addStretch(1)
        unsafe_label = QLabel(f"Not safe (failed re-check): {len(unsafe)}")
        unsafe_label.setProperty("role", "critical")
        summary_row.addWidget(unsafe_label)
        layout.addWidget(summary)

        self.table = QTableWidget(len(candidates), 4)
        self.table.setHorizontalHeaderLabels(["", "File", "Size", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 34)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        for row, asset in enumerate(candidates):
            is_safe = asset in safe
            box = QCheckBox()
            box.setChecked(is_safe)
            box.setEnabled(is_safe)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(10, 0, 0, 0)
            holder_layout.addWidget(box)
            self.table.setCellWidget(row, 0, holder)
            self.table.setItem(row, 1, QTableWidgetItem(asset.name))
            self.table.setItem(row, 2, QTableWidgetItem(mock_data_format_size(asset.size)))
            status = QTableWidgetItem(
                f"verified {asset.verified_at}" if is_safe else "NOT VERIFIED - will be skipped"
            )
            if not is_safe:
                status.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 3, status)
        layout.addWidget(self.table, 1)

        self.notice_label = dialogs_caption(
            "Dry run. Nothing has been deleted from the phone yet."
        )
        layout.addWidget(self.notice_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("Command")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        self.delete_button = QPushButton(f"Delete {len(safe)} items from iPhone...")
        self.delete_button.setObjectName("Destructive")
        self.delete_button.clicked.connect(lambda: self.reclaim_window_confirm(safe))
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

    def reclaim_window_confirm(self, safe: list) -> None:
        """Route the phone deletion through the confirmation dialog.

        safe: the freshly verified candidates offered for deletion.
        """
        dialog = ConfirmDialog(
            f"Delete {len(safe)} items from the iPhone?",
            "The archived copies are kept. Only the phone's copies are removed.",
            sum(asset.size for asset in safe),
            tip="Your archive is not modified by this operation.",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Mirrors current real behaviour: deletion is refused by the device layer.
            self.notice_label.setText(
                "Blocked: deleting from a real iPhone is disabled pending validation. "
                "Nothing was removed from the phone."
            )
            self.notice_label.setProperty("role", "critical")
            self.notice_label.style().polish(self.notice_label)
