"""The destructive-action confirmation dialog: the GUI's mirror of ``--confirm``.

This is the only gate between a selection and an irreversible deletion, so it is
written to be hard to pass by accident and impossible to pass by mistake.

Two strengths of confirmation exist, and the difference is deliberate:

* **Permanent** actions - purging from the archive, deleting from the phone,
  committing marks permanently - require the word ``DELETE`` to be typed. The
  CLI demands ``--confirm`` on exactly these, and a GUI that accepted a single
  click where the CLI demands a flag would be the weaker of the two frontends.
* **Reversible** actions - moving copies into ``Deleted/`` - still require an
  explicit confirmation, but asking the user to type a permanence word for
  something that can be restored would teach them to type it without reading.

The reversible alternative is always offered first when one exists, which is why
the specs below carry a tip rather than the dialog inventing one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .gallery import gallery_format_size
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)

# The word the user must type before anything permanent happens. It matches the
# sketch and the CLI's documented phrasing; it is compared case-sensitively so
# that it cannot be satisfied by an absent-minded "delete".
CONFIRM_WORD = "DELETE"
CONFIRM_DIALOG_SIZE = (460, 300)


@dataclass(frozen=True)
class ConfirmSpec:
    """One confirmation: what is about to happen and how strongly to ask."""

    title: str
    action_label: str
    permanent: bool
    body: tuple[str, ...] = ()
    tip: str = ""
    # The service operation and its arguments, carried so the caller submits
    # exactly what was described to the user rather than rebuilding it later.
    operation: str = ""
    parameters: dict[str, object] = field(default_factory=dict)


def confirm_count_text(count: int, noun: str = "item") -> str:
    """Pluralise a count for a dialog heading.

    count: how many things the action affects.
    noun: the singular noun to use.
    Returns text such as "1 item" or "12 items".
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def confirm_size_line(total_bytes: int) -> str:
    """Describe the size an action covers, or nothing when it is unknown.

    total_bytes: the byte total, which may be zero when the caller cannot know it.
    Returns the "Total size" line, or an empty string.
    """
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool) or total_bytes <= 0:
        return ""
    return f"Total size: {gallery_format_size(total_bytes)}"


def confirm_purge_spec(
    count: int, total_bytes: int, parameters: dict[str, object], recycled_only: bool
) -> ConfirmSpec:
    """Build the confirmation for permanent deletion from the archive.

    count: how many assets are selected.
    total_bytes: the bytes those assets occupy, or 0 when unknown.
    parameters: the copy-scoped service arguments to submit on confirmation.
    recycled_only: whether the purge is restricted to recycle-bin copies.
    Returns the ``ConfirmSpec``. This is the archive's one irreversible verb, so
    it always asks for the typed word.
    """
    scope = (
        "Only the copies already in the recycle bin are affected."
        if recycled_only
        else "Every selected copy is removed from the archive."
    )
    body = [
        "This is permanent and cannot be undone.",
        scope,
        confirm_size_line(total_bytes),
    ]
    return ConfirmSpec(
        title=f"Delete {confirm_count_text(count, 'photo')} from the archive?",
        action_label="Delete",
        permanent=True,
        body=tuple(line for line in body if line),
        tip='"Move to Deleted folder" is reversible.' if not recycled_only else "",
        operation="app_service_purge",
        parameters={**parameters, "confirmed": True, "recycled_only": recycled_only},
    )


def confirm_recycle_spec(count: int, parameters: dict[str, object]) -> ConfirmSpec:
    """Build the confirmation for moving copies into the recycle bin.

    count: how many assets are selected.
    parameters: the copy-scoped service arguments to submit on confirmation.
    Returns the ``ConfirmSpec``. No typed word: the operation is reversible, and
    demanding the permanence word here would devalue it where it matters.
    """
    return ConfirmSpec(
        title=f"Move {confirm_count_text(count, 'photo')} to the Deleted folder?",
        action_label="Move to Deleted folder",
        permanent=False,
        body=(
            "The files move into Deleted\\, keeping their album subpath.",
            "Nothing is erased, and they stay in the archive and keep being verified.",
        ),
        tip="You can restore them from the recycle bin at any time.",
        operation="app_service_move_to_deleted",
        parameters=dict(parameters),
    )


def confirm_reclaim_spec(count: int, total_bytes: int, asset_ids: list[int]) -> ConfirmSpec:
    """Build the confirmation for deleting phone-side copies.

    count: how many phone files were selected.
    total_bytes: the phone space they occupy.
    asset_ids: the assets whose phone copies are to be deleted.
    Returns the ``ConfirmSpec``. The archive is untouched, but the phone's copy
    is gone for good, so this asks for the typed word too.
    """
    body = [
        "The phone's copies are deleted. Your archive is not modified.",
        "Only items that are archived and passed a fresh integrity check are included.",
        confirm_size_line(total_bytes),
    ]
    return ConfirmSpec(
        title=f"Delete {confirm_count_text(count)} from the iPhone?",
        action_label="Delete from iPhone",
        permanent=True,
        body=tuple(line for line in body if line),
        tip="The archive keeps every one of these photos.",
        operation="app_service_reclaim",
        parameters={"confirmed": True, "asset_ids": list(asset_ids)},
    )


def confirm_marks_spec(count: int, purge: bool) -> ConfirmSpec:
    """Build the confirmation for committing the marks queue.

    count: how many marks are staged.
    purge: True to delete permanently, False to move into the recycle bin.
    Returns the ``ConfirmSpec``. Only the permanent form asks for the word; the
    reversible commit gets an ordinary confirmation, matching its CLI.
    """
    if purge:
        return ConfirmSpec(
            title=f"Permanently delete {confirm_count_text(count, 'marked item')}?",
            action_label="Delete permanently",
            permanent=True,
            body=(
                "This is permanent and cannot be undone.",
                "Album marks delete only that album's copies, not every copy of the asset.",
            ),
            tip='"Move to Deleted folder" is reversible.',
            operation="app_service_commit_marks",
            parameters={"confirmed": True, "purge": True},
        )
    return ConfirmSpec(
        title=f"Move {confirm_count_text(count, 'marked item')} to the Deleted folder?",
        action_label="Move to Deleted folder",
        permanent=False,
        body=(
            "The marked copies move into Deleted\\ and the marks are cleared.",
            "Nothing is erased.",
        ),
        tip="You can restore them from the recycle bin at any time.",
        operation="app_service_commit_marks",
        parameters={"confirmed": True, "purge": False},
    )


class ConfirmDialog(QDialog):
    """A WinUI-style content dialog standing between a selection and a deletion."""

    confirmed = Signal(object)

    def __init__(self, spec: ConfirmSpec, parent: QWidget | None = None) -> None:
        """Present one confirmation.

        spec: what is about to happen and how strongly to ask.
        parent: the window this dialog belongs to.
        """
        super().__init__(parent)
        self.setObjectName("ConfirmDialog")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(spec.title)
        self.spec = spec
        self.resize(*CONFIRM_DIALOG_SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.heading = QLabel(spec.title, self)
        self.heading.setFont(theme_font("subtitle"))
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        for line in spec.body:
            label = QLabel(line, self)
            label.setWordWrap(True)
            layout.addWidget(label)
        if spec.tip:
            tip = QLabel(f"Tip: {spec.tip}", self)
            tip.setWordWrap(True)
            tip.setProperty("role", "secondary")
            layout.addWidget(tip)

        self.entry: QLineEdit | None = None
        if spec.permanent:
            prompt = QLabel(f"Type {CONFIRM_WORD} to confirm:", self)
            layout.addWidget(prompt)
            self.entry = QLineEdit(self)
            self.entry.setObjectName("ConfirmEntry")
            self.entry.setFixedHeight(CONTROL_HEIGHT)
            layout.addWidget(self.entry)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(GROUP_GAP)
        footer.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setFixedHeight(CONTROL_HEIGHT)
        self.cancel_button.clicked.connect(self.reject)
        self.action_button = QPushButton(spec.action_label, self)
        self.action_button.setObjectName("DangerButton")
        self.action_button.setFixedHeight(CONTROL_HEIGHT)
        self.action_button.clicked.connect(self.confirm_accept)
        # Disabled until the word is typed. A reversible action needs no word,
        # so its button is live immediately - the click itself is the consent.
        self.action_button.setEnabled(not spec.permanent)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.action_button)
        layout.addLayout(footer)
        # Connected only now: the slot enables the destructive button, so wiring
        # it before the footer exists would raise inside Qt's event loop.
        if self.entry is not None:
            self.entry.textChanged.connect(self.confirm_text_changed)
        # Cancel holds default focus, so Enter and Space dismiss the dialog
        # rather than confirming it.
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()

    def confirm_text_changed(self, text: str) -> None:
        """Enable the destructive button only for an exact match.

        text: what the user has typed so far.
        Returns None. Surrounding whitespace is tolerated because it is easy to
        paste, but the word itself is compared exactly.
        """
        self.action_button.setEnabled(text.strip() == CONFIRM_WORD)

    def confirm_accept(self) -> None:
        """Emit the confirmed spec, refusing if the typed word is not there.

        Returns None. The check is repeated here rather than trusting the
        button's enabled state: a programmatic click, a stuck shortcut or a
        future change to the enabling rule must not be able to bypass the word.
        """
        if self.spec.permanent:
            entry = self.entry
            if entry is None or entry.text().strip() != CONFIRM_WORD:
                LOGGER.warning("refused a permanent action without the confirmation word")
                return
        self.confirmed.emit(self.spec)
        self.accept()


def confirm_show(spec: ConfirmSpec, parent: QWidget | None, handler: object) -> ConfirmDialog:
    """Show a confirmation and route its approval to a handler.

    spec: the action being confirmed.
    parent: the window the dialog belongs to.
    handler: the slot invoked with the approved ``ConfirmSpec``.
    Returns the dialog, which deletes itself when closed. It is shown rather
    than executed: a nested modal loop inside a window that owns a worker
    thread can process a worker reply mid-confirmation.
    """
    dialog = ConfirmDialog(spec, parent)
    dialog.confirmed.connect(handler)
    dialog.show()
    return dialog
