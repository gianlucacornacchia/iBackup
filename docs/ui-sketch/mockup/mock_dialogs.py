"""Dialog mocks: import progress, destructive confirmation, viewer, settings.

MOCK ONLY. Progress is simulated with a QTimer instead of a real QThread and
AppService, but the surfaces, wording and enable/disable rules match
ui-sketch/README.md sections 2, 5, 7 and 7b so they can be reviewed for real.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mock_data import MockAsset, mock_data_format_size
from mock_tokens import OVERLAY_RADIUS, tokens_font

CONFIRM_WORD = "DELETE"


def dialogs_heading(text: str, role: str = "subtitle") -> QLabel:
    """Build a heading label at a type-ramp role.

    text: the heading text in sentence case.
    role: the type-ramp role name.
    Returns the configured QLabel.
    """
    label = QLabel(text)
    label.setFont(tokens_font(role))
    label.setWordWrap(True)
    return label


def dialogs_caption(text: str) -> QLabel:
    """Build a dimmed caption label.

    text: the caption text.
    Returns a QLabel styled as secondary text.
    """
    label = QLabel(text)
    label.setFont(tokens_font("caption"))
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


class ProgressDialog(QDialog):
    """Simulated long-running operation with progress, cancel and hide."""

    hidden_to_status = Signal(str)

    def __init__(self, title: str, verb: str, total: int, parent: QWidget | None = None) -> None:
        """Start a fake operation.

        title: dialog caption.
        verb: present-participle shown per item, e.g. "Copying".
        total: number of items to process.
        parent: owning window.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.verb = verb
        self.total = total
        self.done_count = 0
        self.cancelled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(dialogs_heading(title))

        self.current_label = QLabel()
        self.current_label.setFont(tokens_font("body"))
        layout.addWidget(self.current_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, total)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.counts_label = dialogs_caption("")
        layout.addWidget(self.counts_label)
        self.timing_label = dialogs_caption("")
        layout.addWidget(self.timing_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("Command")
        self.cancel_button.clicked.connect(self.progress_dialog_cancel)
        buttons.addWidget(self.cancel_button)
        self.hide_button = QPushButton("Hide")
        self.hide_button.setObjectName("Command")
        self.hide_button.clicked.connect(self.progress_dialog_hide)
        buttons.addWidget(self.hide_button)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.progress_dialog_tick)
        self.timer.start(45)
        self.progress_dialog_tick()

    def progress_dialog_tick(self) -> None:
        """Advance the simulated operation by one item."""
        if self.done_count >= self.total:
            self.timer.stop()
            self.current_label.setText("Finished")
            self.cancel_button.setText("Close")
            self.hide_button.setEnabled(False)
            return
        self.done_count += 12
        shown = min(self.done_count, self.total)
        self.progress_bar.setValue(shown)
        self.current_label.setText(f"{self.verb} IMG_{4000 + shown}.HEIC")
        skipped = shown // 40
        duplicates = shown // 300
        self.counts_label.setText(
            f"Added {shown - skipped - duplicates}   Skipped {skipped}   "
            f"Duplicates {duplicates}   Errors 0        {shown:,}/{self.total:,}"
        )
        elapsed = shown // 60
        remaining = (self.total - shown) // 60
        self.timing_label.setText(
            f"Elapsed {elapsed // 60:02d}:{elapsed % 60:02d}      "
            f"Remaining ~{remaining // 60:02d}:{remaining % 60:02d}"
        )

    def progress_dialog_cancel(self) -> None:
        """Stop at the next safe checkpoint, leaving a resumable archive."""
        self.timer.stop()
        self.cancelled = True
        self.reject()

    def progress_dialog_hide(self) -> None:
        """Keep the operation running and report it to the status bar."""
        self.timer.stop()
        self.hidden_to_status.emit(f"{self.verb} in background - {self.progress_bar.value()} done")
        self.accept()


class ConfirmDialog(QDialog):
    """WinUI ContentDialog mirroring the CLI's --confirm plus typed DELETE."""

    def __init__(
        self,
        title: str,
        body: str,
        total_bytes: int,
        require_word: bool = True,
        tip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Build the destructive-action confirmation.

        title: question shown as the heading.
        body: consequence text.
        total_bytes: size affected, shown to the user.
        require_word: whether the confirmation word must be typed.
        tip: optional reversible-alternative hint.
        parent: owning window.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setObjectName("Dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(dialogs_heading(title))
        layout.addWidget(QLabel(body))
        layout.addWidget(dialogs_caption(f"Total size: {mock_data_format_size(total_bytes)}"))
        if tip:
            layout.addWidget(dialogs_caption(f"Tip: {tip}"))

        self.word_edit: QLineEdit | None = None
        if require_word:
            layout.addSpacing(4)
            layout.addWidget(QLabel(f"Type {CONFIRM_WORD} to confirm:"))
            self.word_edit = QLineEdit()
            self.word_edit.textChanged.connect(self.confirm_dialog_validate)
            layout.addWidget(self.word_edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("Standard")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        self.action_button = QPushButton("Delete")
        self.action_button.setObjectName("Destructive")
        self.action_button.setEnabled(not require_word)
        self.action_button.clicked.connect(self.accept)
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)
        # Cancel holds default focus, per section 5.
        cancel_button.setDefault(True)
        cancel_button.setFocus()

    def confirm_dialog_validate(self, text: str) -> None:
        """Enable the destructive button only on the exact confirmation word.

        text: current contents of the confirmation field.
        """
        self.action_button.setEnabled(text.strip() == CONFIRM_WORD)


class ViewerDialog(QDialog):
    """Single-photo viewer with metadata, provenance and per-asset actions."""

    def __init__(self, archive, assets: list[MockAsset], index: int, parent=None) -> None:
        """Open the viewer.

        archive: the mock archive used for placeholder images.
        assets: the assets available for prev/next navigation.
        index: which asset to show first.
        parent: owning window.
        """
        super().__init__(parent)
        self.archive = archive
        self.assets = assets
        self.index = index
        self.setWindowTitle("Photo")
        self.resize(760, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        self.title_label = dialogs_heading("", "body_strong")
        layout.addWidget(self.title_label)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(360)
        self.image_label.setStyleSheet(
            f"background: rgba(0,0,0,0.25); border-radius: {OVERLAY_RADIUS}px;"
        )
        layout.addWidget(self.image_label, 1)

        self.meta_label = dialogs_caption("")
        layout.addWidget(self.meta_label)
        self.hash_label = dialogs_caption("")
        layout.addWidget(self.hash_label)
        self.path_label = dialogs_caption("")
        layout.addWidget(self.path_label)

        buttons = QHBoxLayout()
        for label in ("Move to album...", "Mark", "Show in Explorer"):
            button = QPushButton(label)
            button.setObjectName("Command")
            buttons.addWidget(button)
        delete_button = QPushButton("Delete...")
        delete_button.setObjectName("Destructive")
        delete_button.clicked.connect(self.viewer_dialog_delete)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        previous_button = QPushButton("< Prev")
        previous_button.setObjectName("Command")
        previous_button.clicked.connect(lambda: self.viewer_dialog_step(-1))
        buttons.addWidget(previous_button)
        next_button = QPushButton("Next >")
        next_button.setObjectName("Command")
        next_button.clicked.connect(lambda: self.viewer_dialog_step(1))
        buttons.addWidget(next_button)
        layout.addLayout(buttons)

        self.viewer_dialog_refresh()

    def viewer_dialog_refresh(self) -> None:
        """Show the asset at the current index."""
        asset = self.assets[self.index]
        self.title_label.setText(asset.name)
        pixmap = self.archive.mock_archive_thumbnail(asset).scaled(
            520,
            520,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(pixmap)
        albums = ", ".join(asset.albums) if asset.albums else "none (_Unsorted)"
        self.meta_label.setText(
            f"Captured {asset.captured_at}  -  {mock_data_format_size(asset.size)}  "
            f"-  Albums: {albums}"
        )
        self.hash_label.setText(
            f"SHA-256 {asset.sha256[:4]}...{asset.sha256[-2:]}  -  "
            f"Verified {asset.verified_at}  -  On phone: {'yes' if asset.on_phone else 'no'}"
        )
        album_folder = asset.albums[0] if asset.albums else "_Unsorted\\2026\\07"
        self.path_label.setText(f"D:\\iphone-archive\\Photos\\{album_folder}\\{asset.name}")

    def viewer_dialog_step(self, delta: int) -> None:
        """Move to the previous or next asset.

        delta: -1 for previous, 1 for next; wraps around.
        """
        self.index = (self.index + delta) % len(self.assets)
        self.viewer_dialog_refresh()

    def viewer_dialog_delete(self) -> None:
        """Route a single-asset delete through the confirmation dialog."""
        asset = self.assets[self.index]
        ConfirmDialog(
            f"Delete {asset.name} from the archive?",
            "This is permanent and cannot be undone.",
            asset.size,
            tip='"Move to Deleted folder" is reversible.',
            parent=self,
        ).exec()


class SettingsDialog(QDialog):
    """Preferences editor over the existing settings store."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the category list and its panels."""
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(660, 430)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 8)
        body.setSpacing(16)

        self.category_list = QListWidget()
        self.category_list.setObjectName("CategoryList")
        self.category_list.setFixedWidth(150)
        self.category_list.setFrameShape(QFrame.Shape.NoFrame)
        self.category_list.addItems(
            ["Archive", "Import", "Thumbnails", "Safety", "Advanced", "Maintenance"]
        )
        body.addWidget(self.category_list)

        self.panels = QStackedWidget()
        for builder in (
            self.settings_dialog_archive_panel,
            self.settings_dialog_import_panel,
            self.settings_dialog_thumbnail_panel,
            self.settings_dialog_safety_panel,
            self.settings_dialog_advanced_panel,
            self.settings_dialog_maintenance_panel,
        ):
            self.panels.addWidget(builder())
        body.addWidget(self.panels, 1)
        outer.addLayout(body, 1)

        self.category_list.currentRowChanged.connect(self.panels.setCurrentIndex)
        self.category_list.setCurrentRow(0)

        footer = QHBoxLayout()
        footer.setContentsMargins(16, 0, 16, 16)
        footer.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("Standard")
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        save_button = QPushButton("Save")
        save_button.setObjectName("Accent")
        save_button.clicked.connect(self.accept)
        footer.addWidget(save_button)
        outer.addLayout(footer)

    def settings_dialog_panel(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        """Create an empty settings panel with a heading.

        title: the panel heading.
        Returns the panel widget and its layout for further population.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(dialogs_heading(title))
        return panel, layout

    def settings_dialog_archive_panel(self) -> QWidget:
        """Build the archive panel: default root, reopen and recent archives."""
        panel, layout = self.settings_dialog_panel("Default archive")
        row = QHBoxLayout()
        row.addWidget(QLineEdit("D:\\iphone-archive"), 1)
        browse_button = QPushButton("Browse")
        browse_button.setObjectName("Standard")
        row.addWidget(browse_button)
        layout.addLayout(row)
        reopen_box = QCheckBox("Reopen this archive on startup")
        reopen_box.setChecked(True)
        layout.addWidget(reopen_box)
        layout.addWidget(dialogs_caption("Recent archives"))
        recent = QListWidget()
        recent.addItems(["D:\\iphone-archive", "E:\\backup-2025"])
        recent.setFixedHeight(80)
        layout.addWidget(recent)
        forget_row = QHBoxLayout()
        forget_row.addStretch(1)
        forget_button = QPushButton("Forget")
        forget_button.setObjectName("Standard")
        forget_row.addWidget(forget_button)
        layout.addLayout(forget_row)
        layout.addStretch(1)
        return panel

    def settings_dialog_import_panel(self) -> QWidget:
        """Build the import panel: album link mode and post-import scan."""
        panel, layout = self.settings_dialog_panel("Import")
        layout.addWidget(QLabel("Album link mode"))
        mode_box = QComboBox()
        mode_box.addItems(["copy", "hardlink (falls back to copy on exFAT)"])
        layout.addWidget(mode_box)
        layout.addWidget(dialogs_caption("How assets that belong to several albums are stored."))
        scan_box = QCheckBox("Scan the phone for deletions after each import")
        scan_box.setChecked(True)
        layout.addWidget(scan_box)
        layout.addStretch(1)
        return panel

    def settings_dialog_thumbnail_panel(self) -> QWidget:
        """Build the thumbnails panel: preview size and cache control."""
        panel, layout = self.settings_dialog_panel("Thumbnails")
        layout.addWidget(QLabel("Preview size"))
        size_box = QComboBox()
        size_box.addItems(["128 px", "256 px", "512 px"])
        size_box.setCurrentIndex(1)
        layout.addWidget(size_box)
        layout.addWidget(dialogs_caption("On-disk cache: 412 MB"))
        clear_button = QPushButton("Clear cache")
        clear_button.setObjectName("Standard")
        layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return panel

    def settings_dialog_safety_panel(self) -> QWidget:
        """Build the safety panel; these options may only add friction."""
        panel, layout = self.settings_dialog_panel("Safety")
        word_box = QCheckBox(f"Require typing {CONFIRM_WORD} for permanent deletion")
        word_box.setChecked(True)
        word_box.setEnabled(False)
        layout.addWidget(word_box)
        layout.addWidget(
            dialogs_caption("Always on. Preferences can add friction, never remove it.")
        )
        default_box = QCheckBox("Default deleted-on-phone action to 'Move to Deleted folder'")
        default_box.setChecked(True)
        layout.addWidget(default_box)
        dry_run_box = QCheckBox("Keep 'Free up space' in dry run until confirmed")
        dry_run_box.setChecked(True)
        layout.addWidget(dry_run_box)
        layout.addStretch(1)
        return panel

    def settings_dialog_advanced_panel(self) -> QWidget:
        """Build the advanced panel: log level and log folder shortcut."""
        panel, layout = self.settings_dialog_panel("Advanced")
        layout.addWidget(QLabel("Log level"))
        level_box = QComboBox()
        level_box.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        level_box.setCurrentIndex(1)
        layout.addWidget(level_box)
        open_button = QPushButton("Open logs folder")
        open_button.setObjectName("Standard")
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return panel

    def settings_dialog_maintenance_panel(self) -> QWidget:
        """Build the maintenance panel: reset and settings-file location."""
        panel, layout = self.settings_dialog_panel("Maintenance")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.addWidget(QLabel("Settings file"), 0, 0)
        grid.addWidget(dialogs_caption("%APPDATA%\\ibackup\\settings.json"), 0, 1)
        layout.addLayout(grid)
        show_button = QPushButton("Show settings file")
        show_button.setObjectName("Standard")
        layout.addWidget(show_button, 0, Qt.AlignmentFlag.AlignLeft)
        reset_button = QPushButton("Reset settings")
        reset_button.setObjectName("Standard")
        layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(
            dialogs_caption("Resets preferences only. Your archive is never touched.")
        )
        layout.addStretch(1)
        return panel
