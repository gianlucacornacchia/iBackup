"""Command bar: the primary verbs, replacing a menu bar.

The sketch has no menu bar, so this bar is the only place the GUI offers the
CLI's verbs. Each command therefore names the service operation it will run, so
the parity test in a later step can prove that no CLI capability is missing from
the GUI rather than relying on a hand-maintained list.

Commands that need a phone are disabled with an explanatory tooltip when the
phone is known to be absent. There is no cheap presence probe over AFC - the
only device call available enumerates the whole library - so the phone state is
"unknown" until a device operation reports one way or the other, and unknown is
treated as available rather than blocking the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QPushButton, QWidget

from .icons import icons_get
from .theme import CONTROL_HEIGHT, theme_font

PhoneState = Literal["unknown", "connected", "disconnected"]
PHONE_TOOLTIP = 'Connect the iPhone over USB, then use "Check phone".'
ARCHIVE_TOOLTIP = "Open an archive first."


@dataclass(frozen=True)
class CommandSpec:
    """One command-bar verb and the service operation behind it."""

    key: str
    label: str
    glyph: str
    operation: str
    tooltip: str
    requires_archive: bool = True
    requires_phone: bool = False
    overflow: bool = False


COMMANDS = (
    CommandSpec(
        "open", "Open archive", "folder", "open_archive", "Open an existing archive.", False
    ),
    CommandSpec(
        "import",
        "Import",
        "import",
        "app_service_import",
        "Copy new photos and videos from the iPhone into the archive.",
        requires_phone=True,
    ),
    CommandSpec("verify", "Verify", "verify", "app_service_verify", "Re-hash archived files."),
    CommandSpec(
        "scan",
        "Scan phone",
        "scan",
        "app_service_scan_phone",
        "Record which archived assets are still on the phone.",
        requires_phone=True,
    ),
    CommandSpec(
        "reclaim",
        "Free up space",
        "broom",
        "app_service_reclaim",
        "Delete phone-side copies that are archived and verified.",
        requires_phone=True,
    ),
    CommandSpec(
        "create",
        "New archive",
        "folder",
        "create_archive",
        "Create and open a new archive.",
        False,
        overflow=True,
    ),
    CommandSpec(
        "close", "Close archive", "close", "close_archive", "Close the archive.", overflow=True
    ),
    CommandSpec(
        # Deliberately not requires_phone: this is the only command that can
        # prove the phone is back, so disabling it when the phone last failed
        # would make "disconnected" an unrecoverable state.
        "device",
        "Check phone",
        "phone",
        "app_service_device_info",
        "Read the connected phone's identifier and media count.",
        overflow=True,
    ),
    CommandSpec(
        "dedup",
        "Duplicate report",
        "photos",
        "app_service_dedup_report",
        "Show duplicate and hash statistics.",
        overflow=True,
    ),
    CommandSpec(
        "stats",
        "Refresh counts",
        "verify",
        "app_service_stats",
        "Re-read the archive counters.",
        overflow=True,
    ),
    CommandSpec(
        "clear-thumbnails",
        "Clear previews",
        "recycle",
        "app_service_clear_thumbnails",
        "Delete the regenerable preview cache.",
        overflow=True,
    ),
)
COMMANDS_BY_KEY = {command.key: command for command in COMMANDS}


def commands_enabled(command: CommandSpec, archive_open: bool, phone: PhoneState) -> bool:
    """Decide whether a command can run right now.

    command: the command to evaluate.
    archive_open: whether an archive session is open.
    phone: the last known phone state.
    Returns True when the command is available.
    """
    if command.requires_archive and not archive_open:
        return False
    if command.key == "open" and archive_open:
        return False
    return not (command.requires_phone and phone == "disconnected")


def commands_reason(command: CommandSpec, archive_open: bool, phone: PhoneState) -> str:
    """Explain why a command is unavailable, for its tooltip.

    command: the command to evaluate.
    archive_open: whether an archive session is open.
    phone: the last known phone state.
    Returns the tooltip text to display.
    """
    if command.requires_archive and not archive_open:
        return f"{command.tooltip} {ARCHIVE_TOOLTIP}"
    if command.key == "open" and archive_open:
        return f"{command.tooltip} {'Close the current archive first.'}"
    if command.requires_phone and phone == "disconnected":
        return f"{command.tooltip} {PHONE_TOOLTIP}"
    return command.tooltip


class CommandBar(QFrame):
    """Card surface holding the primary verbs plus an overflow menu."""

    command_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build every command button; state is applied by the shell."""
        super().__init__(parent)
        self.setObjectName("Card")
        self.archive_open = False
        self.phone: PhoneState = "unknown"
        self.buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(4)
        color = self.palette().color(self.palette().ColorRole.WindowText)
        for command in COMMANDS:
            if command.overflow:
                continue
            button = QPushButton(f" {command.label}", self)
            button.setObjectName("Command")
            button.setIcon(icons_get(command.glyph, color))
            button.setFont(theme_font("body"))
            button.setMinimumHeight(CONTROL_HEIGHT)
            button.clicked.connect(
                lambda checked=False, key=command.key: self.command_triggered.emit(key)
            )
            self.buttons[command.key] = button
            row.addWidget(button)
        row.addStretch(1)

        self.overflow_menu = QMenu(self)
        self.overflow_button = QPushButton(self)
        self.overflow_button.setObjectName("Command")
        self.overflow_button.setIcon(icons_get("more", color))
        self.overflow_button.setFixedHeight(CONTROL_HEIGHT)
        self.overflow_button.setToolTip("More commands")
        self.overflow_button.setMenu(self.overflow_menu)
        self.actions_by_key = {}
        for command in COMMANDS:
            if not command.overflow:
                continue
            action = self.overflow_menu.addAction(command.label)
            action.setIcon(icons_get(command.glyph, color))
            action.triggered.connect(
                lambda checked=False, key=command.key: self.command_triggered.emit(key)
            )
            self.actions_by_key[command.key] = action
        row.addWidget(self.overflow_button)
        self.commands_set_state(False, "unknown")

    def commands_set_state(self, archive_open: bool, phone: PhoneState) -> None:
        """Enable, disable and re-explain every command.

        archive_open: whether an archive session is open.
        phone: the last known phone state.
        Returns None.
        """
        if phone not in {"unknown", "connected", "disconnected"}:
            raise ValueError(f"Unknown phone state: {phone}")
        self.archive_open = bool(archive_open)
        self.phone = phone
        for command in COMMANDS:
            target = self.buttons.get(command.key) or self.actions_by_key.get(command.key)
            if target is None:
                continue
            enabled = commands_enabled(command, self.archive_open, phone)
            target.setEnabled(enabled)
            target.setToolTip(commands_reason(command, self.archive_open, phone))

    def commands_refresh_icons(self) -> None:
        """Re-draw command icons after a theme change, since they are painted."""
        color = self.palette().color(self.palette().ColorRole.WindowText)
        for key, button in self.buttons.items():
            button.setIcon(icons_get(COMMANDS_BY_KEY[key].glyph, color))
        for key, action in self.actions_by_key.items():
            action.setIcon(icons_get(COMMANDS_BY_KEY[key].glyph, color))
        self.overflow_button.setIcon(icons_get("more", color))

    def changeEvent(self, event: QEvent) -> None:
        """Follow live theme changes for the drawn icons."""
        super().changeEvent(event)
        if event.type() == event.Type.PaletteChange:
            self.commands_refresh_icons()
