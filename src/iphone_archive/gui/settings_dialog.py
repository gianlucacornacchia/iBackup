"""Sketch section 7b: the preferences editor over the existing settings store.

The six panels are a thin editor over ``app_service_get_settings`` /
``app_service_update_settings``; nothing here reads or writes the settings file
itself. The dialog is handed a detached ``Settings`` copy, shows it, and hands a
new copy back to the window, which is the only object allowed to talk to the
worker.

Preferences are *defaults*, never archive semantics. Two of the safety options
are therefore shown ticked and disabled: the typed word for permanent deletions
and the always-dry-run-first rule for phone reclamation are guarantees of the
application, not switches. Showing them makes the guarantee visible without
pretending it can be turned off.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.archive_layout import LINK_MODE_COPY, LINK_MODE_HARDLINK
from ..settings import (
    DELETED_ACTION_PURGE,
    DELETED_ACTION_RECYCLE,
    LOG_LEVEL_CHOICES,
    THEME_CHOICES,
    THUMBNAIL_SIZE_CHOICES,
    Settings,
    SettingsError,
    settings_validate,
)
from .confirm import CONFIRM_WORD
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)

SETTINGS_DIALOG_SIZE = (680, 460)
CATEGORY_WIDTH = 150
RECENT_LIST_HEIGHT = 96
# Every service operation this surface can run. The parity test reads this
# instead of guessing which widget stands for which CLI `config` subcommand.
SETTINGS_OPERATIONS = (
    "app_service_get_settings",
    "app_service_update_settings",
    "app_service_reset_settings",
    "app_service_settings_path",
    "app_service_forget_archive",
    "app_service_clear_thumbnails",
)
PANEL_TITLES = ("Archive", "Import", "Thumbnails", "Safety", "Advanced", "Maintenance")
LINK_MODE_LABELS = (
    (LINK_MODE_COPY, "copy - an independent file per album"),
    (LINK_MODE_HARDLINK, "hardlink - one copy shared per album (falls back to copy)"),
)
DELETED_ACTION_LABELS = (
    (DELETED_ACTION_RECYCLE, "Move to the Deleted folder (recoverable)"),
    (DELETED_ACTION_PURGE, "Delete from the archive (permanent, still confirmed)"),
)
THEME_LABEL_TEXT = {"system": "Follow Windows", "light": "Light", "dark": "Dark"}
# Built from the stored choices, so a theme the settings store accepts can never
# be missing from the only widget that offers them.
THEME_LABELS = tuple((choice, THEME_LABEL_TEXT.get(choice, choice)) for choice in THEME_CHOICES)
RESET_PROMPT = "Reset settings"
RESET_CONFIRM = "Confirm reset"
RESET_CAPTION = "Preferences only. Your archive and its files are never touched."
CLEAR_CACHE_TOOLTIP = "Open an archive first; the preview cache lives inside it."
LOGS_TOOLTIP = "Open an archive first; its log folder lives inside it."


def settings_dialog_open_location(target: Path | None) -> bool:
    """Show a file or folder in the system file manager.

    target: the path to reveal, or None when it is not known yet.
    Returns True when a request was handed to the desktop. A missing path opens
    nothing rather than creating it, because a settings file that has never been
    written is a normal state, not an error to repair.
    """
    if target is None:
        return False
    location = target if target.is_dir() else target.parent
    if not location.is_dir():
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(location))))


def settings_dialog_index(values: Sequence[tuple[str, str]], current: object) -> int:
    """Find the row of a stored value in a labelled choice list.

    values: the ``(value, label)`` pairs offered by a combo box.
    current: the stored value.
    Returns the matching row, or 0 when the stored value is not offered.
    """
    for row, (value, _) in enumerate(values):
        if value == current:
            return row
    return 0


class SettingsDialog(QDialog):
    """The six preference panels, edited as one detached ``Settings`` copy."""

    # (operation, parameters). The dialog never reaches the worker itself: the
    # window owns that boundary, and it is the only place a refusal can be
    # reported consistently with every other operation.
    settings_requested = Signal(str, object)

    def __init__(
        self,
        settings: Settings,
        settings_file: Path | None = None,
        *,
        archive_open: bool = False,
        logs_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog around a detached copy of the stored preferences.

        settings: the preferences the worker read.
        settings_file: the settings file path, when it is already known.
        archive_open: whether an archive session is open; the preview cache and
            the log folder live inside an archive, so their buttons need one.
        logs_dir: the open archive's log folder, when there is one.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Settings")
        self.resize(*SETTINGS_DIALOG_SIZE)
        self.settings = replace(settings, recent_archives=list(settings.recent_archives))
        self.settings_file = settings_file
        self.archive_open = bool(archive_open)
        self.logs_dir = logs_dir
        self.reset_armed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        outer.setSpacing(GROUP_GAP)
        body = QHBoxLayout()
        body.setSpacing(PAGE_MARGIN)
        self.category_list = QListWidget(self)
        self.category_list.setObjectName("CategoryList")
        self.category_list.setFixedWidth(CATEGORY_WIDTH)
        self.category_list.setFrameShape(QFrame.Shape.NoFrame)
        self.category_list.addItems(list(PANEL_TITLES))
        body.addWidget(self.category_list)
        self.panels = QStackedWidget(self)
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

        self.message_label = QLabel("", self)
        self.message_label.setFont(theme_font("caption"))
        self.message_label.setProperty("role", "secondary")
        self.message_label.setWordWrap(True)
        outer.addWidget(self.message_label)
        outer.addLayout(self.settings_dialog_footer())

        self.category_list.currentRowChanged.connect(self.panels.setCurrentIndex)
        self.category_list.setCurrentRow(0)
        self.settings_dialog_show(self.settings)

    def settings_dialog_panel(self, title: str, caption: str = "") -> tuple[QWidget, QVBoxLayout]:
        """Create an empty panel with its heading.

        title: the panel heading.
        caption: an optional dimmed line under the heading.
        Returns the panel widget and the layout to fill.
        """
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        heading = QLabel(title, panel)
        heading.setFont(theme_font("subtitle"))
        layout.addWidget(heading)
        if caption:
            layout.addWidget(self.settings_dialog_caption(caption, panel))
        return panel, layout

    def settings_dialog_caption(self, text: str, parent: QWidget) -> QLabel:
        """Build a dimmed explanatory line.

        text: the caption text.
        parent: the owning widget.
        Returns the label.
        """
        label = QLabel(text, parent)
        label.setFont(theme_font("caption"))
        label.setProperty("role", "secondary")
        label.setWordWrap(True)
        return label

    def settings_dialog_combo(
        self, values: Sequence[tuple[str, str]], parent: QWidget
    ) -> QComboBox:
        """Build a combo box whose rows carry their stored value.

        values: the ``(value, label)`` pairs to offer.
        parent: the owning widget.
        Returns the populated combo box.
        """
        box = QComboBox(parent)
        box.setMinimumHeight(CONTROL_HEIGHT)
        for value, label in values:
            box.addItem(label, value)
        return box

    def settings_dialog_archive_panel(self) -> QWidget:
        """Build the archive panel: default root, reopen-on-startup and recents."""
        panel, layout = self.settings_dialog_panel("Default archive")
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)
        self.archive_edit = QLineEdit(panel)
        self.archive_edit.setMinimumHeight(CONTROL_HEIGHT)
        self.archive_edit.setPlaceholderText("No default archive")
        row.addWidget(self.archive_edit, 1)
        browse_button = QPushButton("Browse", panel)
        browse_button.setMinimumHeight(CONTROL_HEIGHT)
        browse_button.clicked.connect(self.settings_dialog_browse)
        row.addWidget(browse_button)
        layout.addLayout(row)
        self.reopen_box = QCheckBox("Reopen this archive on startup", panel)
        layout.addWidget(self.reopen_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "Only an archive that still exists is reopened; nothing is created.", panel
            )
        )
        layout.addWidget(self.settings_dialog_caption("Recent archives", panel))
        self.recent_list = QListWidget(panel)
        self.recent_list.setObjectName("RecentList")
        self.recent_list.setFixedHeight(RECENT_LIST_HEIGHT)
        self.recent_list.currentRowChanged.connect(self.settings_dialog_recent_changed)
        layout.addWidget(self.recent_list)
        forget_row = QHBoxLayout()
        forget_row.addStretch(1)
        self.forget_button = QPushButton("Forget", panel)
        self.forget_button.setMinimumHeight(CONTROL_HEIGHT)
        self.forget_button.setToolTip("Remove this archive from the list. Its files are kept.")
        self.forget_button.clicked.connect(self.settings_dialog_forget)
        forget_row.addWidget(self.forget_button)
        layout.addLayout(forget_row)
        layout.addStretch(1)
        return panel

    def settings_dialog_import_panel(self) -> QWidget:
        """Build the import panel: album link mode and the post-import phone scan."""
        panel, layout = self.settings_dialog_panel("Import")
        layout.addWidget(QLabel("Album link mode", panel))
        self.link_mode_box = self.settings_dialog_combo(LINK_MODE_LABELS, panel)
        layout.addWidget(self.link_mode_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "How an asset that belongs to several albums is stored. Hardlinks "
                "fall back to copies on file systems that cannot make them.",
                panel,
            )
        )
        self.scan_box = QCheckBox("Scan the phone for deletions after each import", panel)
        layout.addWidget(self.scan_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "The scan only records what is no longer on the phone. It deletes nothing.",
                panel,
            )
        )
        layout.addStretch(1)
        return panel

    def settings_dialog_thumbnail_panel(self) -> QWidget:
        """Build the thumbnails panel: preview size and the cache control."""
        panel, layout = self.settings_dialog_panel("Thumbnails")
        layout.addWidget(QLabel("Preview size", panel))
        self.size_box = self.settings_dialog_combo(
            tuple((str(size), f"{size} px") for size in THUMBNAIL_SIZE_CHOICES), panel
        )
        layout.addWidget(self.size_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "Larger previews are sharper and slower to build. Existing previews "
                "are kept; the new size is generated as tiles are shown.",
                panel,
            )
        )
        self.clear_button = QPushButton("Clear cache", panel)
        self.clear_button.setMinimumHeight(CONTROL_HEIGHT)
        self.clear_button.setEnabled(self.archive_open)
        self.clear_button.setToolTip(
            "Delete the cached previews; they are rebuilt on demand."
            if self.archive_open
            else CLEAR_CACHE_TOOLTIP
        )
        self.clear_button.clicked.connect(self.settings_dialog_clear_cache)
        layout.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(
            self.settings_dialog_caption(
                "Previews are regenerable. Clearing the cache never touches your photos.",
                panel,
            )
        )
        layout.addStretch(1)
        return panel

    def settings_dialog_safety_panel(self) -> QWidget:
        """Build the safety panel; these options may only ever add friction."""
        panel, layout = self.settings_dialog_panel("Safety")
        self.confirm_box = QCheckBox(f"Require typing {CONFIRM_WORD} for permanent deletion", panel)
        self.confirm_box.setChecked(True)
        self.confirm_box.setEnabled(False)
        self.confirm_box.setToolTip("Always on. A preference can add friction, never remove it.")
        layout.addWidget(self.confirm_box)
        self.dry_run_box = QCheckBox("Preview phone clean-up before deleting anything", panel)
        self.dry_run_box.setChecked(True)
        self.dry_run_box.setEnabled(False)
        self.dry_run_box.setToolTip("Always on. Reclamation always runs a dry run first.")
        layout.addWidget(self.dry_run_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "Both guarantees are part of the application and cannot be switched off.",
                panel,
            )
        )
        layout.addWidget(QLabel("Default action for items deleted on the phone", panel))
        self.deleted_action_box = self.settings_dialog_combo(DELETED_ACTION_LABELS, panel)
        layout.addWidget(self.deleted_action_box)
        layout.addWidget(
            self.settings_dialog_caption(
                "This only decides which button the review page suggests. Every "
                f"permanent deletion still asks you to type {CONFIRM_WORD}.",
                panel,
            )
        )
        layout.addStretch(1)
        return panel

    def settings_dialog_advanced_panel(self) -> QWidget:
        """Build the advanced panel: appearance, log level and the log folder."""
        panel, layout = self.settings_dialog_panel("Advanced")
        layout.addWidget(QLabel("Appearance", panel))
        self.theme_box = self.settings_dialog_combo(THEME_LABELS, panel)
        layout.addWidget(self.theme_box)
        layout.addWidget(QLabel("Log level", panel))
        self.log_level_box = self.settings_dialog_combo(
            tuple((level, level) for level in LOG_LEVEL_CHOICES), panel
        )
        layout.addWidget(self.log_level_box)
        self.logs_button = QPushButton("Open logs folder", panel)
        self.logs_button.setMinimumHeight(CONTROL_HEIGHT)
        self.logs_button.setEnabled(self.logs_dir is not None)
        if self.logs_dir is None:
            self.logs_button.setToolTip(LOGS_TOOLTIP)
        self.logs_button.clicked.connect(self.settings_dialog_open_logs)
        layout.addWidget(self.logs_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return panel

    def settings_dialog_maintenance_panel(self) -> QWidget:
        """Build the maintenance panel: the settings file and a reset."""
        panel, layout = self.settings_dialog_panel("Maintenance")
        layout.addWidget(QLabel("Settings file", panel))
        self.path_label = self.settings_dialog_caption("", panel)
        self.path_label.setObjectName("SettingsPath")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.show_button = QPushButton("Show settings file", panel)
        self.show_button.setMinimumHeight(CONTROL_HEIGHT)
        self.show_button.clicked.connect(self.settings_dialog_show_file)
        layout.addWidget(self.show_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.reset_button = QPushButton(RESET_PROMPT, panel)
        self.reset_button.setMinimumHeight(CONTROL_HEIGHT)
        self.reset_button.clicked.connect(self.settings_dialog_reset)
        layout.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.settings_dialog_caption(RESET_CAPTION, panel))
        layout.addStretch(1)
        return panel

    def settings_dialog_footer(self) -> QHBoxLayout:
        """Build the Cancel/Save row.

        Returns the populated layout.
        """
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)
        row.addStretch(1)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.setMinimumHeight(CONTROL_HEIGHT)
        cancel_button.clicked.connect(self.reject)
        row.addWidget(cancel_button)
        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName("Accent")
        self.save_button.setMinimumHeight(CONTROL_HEIGHT)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.settings_dialog_save)
        row.addWidget(self.save_button)
        return row

    def settings_dialog_show(self, settings: Settings, settings_file: Path | None = None) -> None:
        """Display stored preferences, replacing anything currently edited.

        settings: the preferences to show.
        settings_file: the settings file path, when it has just been learnt.
        Returns None. A reset or a forget re-reads from the service rather than
        patching the widgets, so the dialog always shows what is really stored.
        """
        self.settings = replace(settings, recent_archives=list(settings.recent_archives))
        if settings_file is not None:
            self.settings_file = settings_file
        self.archive_edit.setText(settings.default_archive or "")
        self.reopen_box.setChecked(bool(settings.reopen_last_archive))
        self.settings_dialog_show_recent(settings.recent_archives)
        self.link_mode_box.setCurrentIndex(
            settings_dialog_index(LINK_MODE_LABELS, settings.album_link_mode)
        )
        self.scan_box.setChecked(bool(settings.scan_phone_after_import))
        self.size_box.setCurrentIndex(
            settings_dialog_index(
                tuple((str(size), f"{size} px") for size in THUMBNAIL_SIZE_CHOICES),
                str(settings.thumbnail_size),
            )
        )
        self.deleted_action_box.setCurrentIndex(
            settings_dialog_index(DELETED_ACTION_LABELS, settings.default_deleted_action)
        )
        self.theme_box.setCurrentIndex(settings_dialog_index(THEME_LABELS, settings.theme))
        self.log_level_box.setCurrentIndex(
            settings_dialog_index(
                tuple((level, level) for level in LOG_LEVEL_CHOICES),
                str(settings.log_level).upper(),
            )
        )
        self.path_label.setText(
            str(self.settings_file) if self.settings_file else "Not written yet"
        )
        self.settings_dialog_disarm_reset()

    def settings_dialog_show_recent(self, recent: Sequence[str]) -> None:
        """Fill the recent-archive list.

        recent: the stored recent paths, most recent first.
        Returns None.
        """
        self.recent_list.clear()
        for entry in recent:
            QListWidgetItem(entry, self.recent_list)
        self.forget_button.setEnabled(False)

    def settings_dialog_recent_changed(self, row: int) -> None:
        """Enable Forget only while a recent archive is selected.

        row: the selected row, or -1 for none.
        Returns None.
        """
        self.forget_button.setEnabled(row >= 0)

    def settings_dialog_selected_recent(self) -> str | None:
        """Return the selected recent archive path, or None."""
        item = self.recent_list.currentItem()
        return item.text() if item is not None else None

    def settings_dialog_values(self) -> Settings:
        """Collect what the panels currently show as a new ``Settings``.

        Returns the edited preferences. ``recent_archives`` is carried through
        untouched because it is maintained by the service, and
        ``confirm_word_required`` is forced on: no widget here may weaken a
        confirmation, so no widget value is trusted to describe it.
        """
        return Settings(
            default_archive=self.archive_edit.text().strip() or None,
            reopen_last_archive=self.reopen_box.isChecked(),
            recent_archives=list(self.settings.recent_archives),
            album_link_mode=str(self.link_mode_box.currentData()),
            scan_phone_after_import=self.scan_box.isChecked(),
            thumbnail_size=int(str(self.size_box.currentData())),
            confirm_word_required=True,
            default_deleted_action=str(self.deleted_action_box.currentData()),
            log_level=str(self.log_level_box.currentData()),
            theme=str(self.theme_box.currentData()),
        )

    def settings_dialog_message(self, text: str) -> None:
        """Show a line under the panels, where a refusal belongs.

        text: the message, or an empty string to clear it.
        Returns None.
        """
        self.message_label.setText(text)

    def settings_dialog_save(self) -> None:
        """Validate the edited preferences and ask the window to store them.

        Returns None. Validation runs here so an invalid value is reported in
        the dialog that produced it; the service validates again before writing,
        because this dialog is not the only caller it has.
        """
        try:
            edited = self.settings_dialog_values()
            settings_validate(edited)
        except (SettingsError, ValueError) as error:
            self.settings_dialog_message(f"Not saved: {error}")
            return
        self.settings_requested.emit("app_service_update_settings", {"settings": edited})
        self.accept()

    def settings_dialog_browse(self) -> None:
        """Pick the default archive folder.

        Returns None. Choosing a folder here only records a preference; no
        archive is opened or created by it.
        """
        directory = self.settings_dialog_choose_directory("Choose the default archive folder")
        if directory:
            self.archive_edit.setText(directory)

    def settings_dialog_choose_directory(self, title: str) -> str:
        """Ask the user for a folder.

        title: the file dialog's caption.
        Returns the chosen path, or an empty string. Separate so tests can
        answer without a native dialog and its nested event loop.
        """
        return QFileDialog.getExistingDirectory(self, title)

    def settings_dialog_forget(self) -> None:
        """Forget the selected recent archive, keeping its files.

        Returns None.
        """
        entry = self.settings_dialog_selected_recent()
        if not entry:
            return
        self.settings_dialog_message(f"Forgetting {entry}. Its files are untouched.")
        self.settings_requested.emit("app_service_forget_archive", {"archive_root": Path(entry)})

    def settings_dialog_clear_cache(self) -> None:
        """Ask the window to delete the regenerable preview cache.

        Returns None.
        """
        if not self.archive_open:
            self.settings_dialog_message(CLEAR_CACHE_TOOLTIP)
            return
        self.settings_requested.emit("app_service_clear_thumbnails", {})

    def settings_dialog_open_logs(self) -> None:
        """Open the archive's log folder in the file manager.

        Returns None.
        """
        if not settings_dialog_open_location(self.logs_dir):
            self.settings_dialog_message("There is no log folder to open yet.")

    def settings_dialog_show_file(self) -> None:
        """Open the folder holding the settings file.

        Returns None. A settings file that has never been written is normal, so
        this reports it instead of creating one.
        """
        if not settings_dialog_open_location(self.settings_file):
            self.settings_dialog_message("The settings file has not been written yet.")

    def settings_dialog_reset(self) -> None:
        """Restore every preference to its default, after a second press.

        Returns None. The first press only arms the button: a reset discards the
        default archive and the recent list, which is annoying rather than
        dangerous, so it asks once without a modal dialog.
        """
        if not self.reset_armed:
            self.reset_armed = True
            self.reset_button.setText(RESET_CONFIRM)
            self.settings_dialog_message(f"Press {RESET_CONFIRM} again to restore the defaults.")
            return
        self.settings_dialog_disarm_reset()
        self.settings_requested.emit("app_service_reset_settings", {})

    def settings_dialog_disarm_reset(self) -> None:
        """Return the reset button to its unarmed state.

        Returns None.
        """
        self.reset_armed = False
        self.reset_button.setText(RESET_PROMPT)
