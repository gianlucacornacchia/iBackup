"""Single-asset viewer.

The viewer is deliberately a *preview* rather than an editor: this application
never modifies an archived original, so the dialog shows a large rendered copy
plus the catalog facts the sketch lists - capture date, size, hash, verification
state, phone presence and the archive paths of every stored copy.

The large image is rendered by its own ``PreviewLoader`` at a viewer-sized
bounding box. Reusing the grid's loader would either evict the whole tile cache
when the size changed or force the viewer to display a 256px thumbnail blown up,
so the two run side by side with their own bounded caches.

Navigation walks the same paged model the grid uses. Stepping past the last
loaded row pulls the next page rather than pretending the library ends there.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .gallery import gallery_format_size
from .models import AssetModel, AssetRole
from .previews import PreviewLoader, PreviewState
from .theme import CONTROL_HEIGHT, GROUP_GAP, PAGE_MARGIN, theme_font

LOGGER = logging.getLogger(__name__)

VIEWER_PREVIEW_SIZE = 1024
VIEWER_DEFAULT_SIZE = (960, 720)
VIEWER_MINIMUM_SIZE = (640, 480)
# An asset can have many stored copies; the dialog lists the first few rather
# than growing without bound.
MAX_FACT_LINES = 8
VIEWER_ACTIONS = (
    ("move", "Move to album..."),
    ("mark", "Mark"),
    ("delete", "Delete..."),
    ("restore", "Restore"),
    ("purge", "Purge..."),
)


def viewer_metadata_lines(index_data: dict[str, object]) -> list[str]:
    """Compose the fact lines shown under the image.

    index_data: the asset's role values, keyed by lower-case role name.
    Returns the lines to display, in the sketch's order.
    """
    captured = index_data.get("captured_at") or "unknown date"
    size = index_data.get("size")
    size_text = gallery_format_size(size) if isinstance(size, int) and size >= 0 else "unknown size"
    media = index_data.get("media_type") or "unknown"
    sha256 = str(index_data.get("sha256") or "")
    state = index_data.get("archive_state") or "unknown"
    on_phone = "yes" if index_data.get("present_on_phone") else "no"
    paths = index_data.get("paths")
    lines = [
        f"Captured {captured} - {size_text} - {media}",
        f"SHA-256 {sha256} - state: {state} - on phone: {on_phone}",
    ]
    if isinstance(paths, tuple):
        lines.extend(str(path) for path in paths)
    return lines


class ViewerDialog(QDialog):
    """A large preview of one asset with metadata and prev/next navigation."""

    viewer_action = Signal(str, int)

    def __init__(
        self,
        model: AssetModel,
        previews: PreviewLoader,
        row: int,
        parent: QWidget | None = None,
    ) -> None:
        """Open the viewer on one row of the shared asset model.

        model: the paged asset model the grid is showing.
        previews: a loader rendering at the viewer's bounding-box size.
        row: the row to display first.
        parent: the owning window.
        """
        super().__init__(parent)
        self.setObjectName("ViewerDialog")
        # A closed viewer must not linger: it retains a full-size pixmap and
        # stays connected to the shared model and preview loader, so a ghost
        # dialog would keep scheduling large renders the visible one waits for.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("iPhone Archive")
        self.resize(*VIEWER_DEFAULT_SIZE)
        self.setMinimumSize(*VIEWER_MINIMUM_SIZE)
        self.assets = model
        self.previews = previews
        self.row = -1
        self.advance_pending = False
        self.pixmap: QPixmap | None = None
        self.actions_available: tuple[str, ...] = ()
        self.buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(GROUP_GAP)
        self.title_label = QLabel("", self)
        self.title_label.setFont(theme_font("subtitle"))
        layout.addWidget(self.title_label)

        self.image_label = QLabel("", self)
        self.image_label.setObjectName("ViewerImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setMinimumHeight(240)
        layout.addWidget(self.image_label, 1)

        self.facts = QFrame(self)
        self.facts.setObjectName("Card")
        facts_layout = QVBoxLayout(self.facts)
        facts_layout.setContentsMargins(12, 8, 12, 8)
        facts_layout.setSpacing(2)
        self.facts_layout = facts_layout
        self.fact_labels: list[QLabel] = []
        layout.addWidget(self.facts)

        buttons = QHBoxLayout()
        buttons.setSpacing(GROUP_GAP)
        for key, caption in VIEWER_ACTIONS:
            button = QPushButton(caption, self)
            button.setObjectName("Command")
            button.setFont(theme_font("body"))
            button.setMinimumHeight(CONTROL_HEIGHT)
            button.clicked.connect(
                lambda checked=False, action=key: self.viewer_emit_action(action)
            )
            self.buttons[key] = button
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.previous_button = QPushButton("< Previous", self)
        self.previous_button.setObjectName("Command")
        self.previous_button.clicked.connect(self.viewer_previous)
        self.next_button = QPushButton("Next >", self)
        self.next_button.setObjectName("Command")
        self.next_button.clicked.connect(self.viewer_next)
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        previews.preview_ready.connect(self.viewer_preview_settled)
        previews.preview_failed.connect(self.viewer_preview_settled)
        self.assets.modelReset.connect(self.viewer_model_reset)
        self.assets.page_loaded.connect(self.viewer_page_loaded)
        self.viewer_show_row(row)

    def viewer_set_actions(self, actions: tuple[str, ...]) -> None:
        """Offer only the actions the current view supports.

        actions: the action keys to show.
        Returns None.
        """
        unknown = set(actions) - set(self.buttons)
        if unknown:
            raise ValueError(f"Unknown viewer actions: {sorted(unknown)}")
        self.actions_available = actions
        for key, button in self.buttons.items():
            button.setVisible(key in actions)

    def viewer_row_data(self, row: int) -> dict[str, object] | None:
        """Read one row's role values without touching the disk.

        row: the model row to read.
        Returns the role values keyed by lower-case role name, or None when the
        row does not exist.
        """
        index = self.assets.index(row)
        if not index.isValid():
            return None
        return {role.name.lower(): index.data(int(role)) for role in AssetRole}

    def viewer_show_row(self, row: int) -> None:
        """Display one row, requesting its large preview in the background.

        row: the model row to display.
        Returns None. A row that no longer exists closes the viewer rather than
        showing another asset's data under the previous asset's title.
        """
        data = self.viewer_row_data(row)
        if data is None:
            self.reject()
            return
        self.row = row
        self.pixmap = None
        name = str(data.get("original_name") or "")
        self.title_label.setText(name)
        self.viewer_set_facts(viewer_metadata_lines(data))
        self.viewer_request_preview(data)
        self.viewer_update_navigation()

    def viewer_set_facts(self, lines: list[str]) -> None:
        """Show one selectable label per fact line, reusing the existing labels.

        lines: the fact lines to display. An asset can be stored under several
        album paths, so the number of lines is not fixed.
        Returns None.
        """
        shown = lines[:MAX_FACT_LINES]
        while len(self.fact_labels) < len(shown):
            label = QLabel("", self.facts)
            label.setFont(theme_font("caption"))
            label.setProperty("role", "secondary")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.facts_layout.addWidget(label)
            self.fact_labels.append(label)
        for position, label in enumerate(self.fact_labels):
            label.setText(shown[position] if position < len(shown) else "")
            label.setVisible(position < len(shown))

    def viewer_request_preview(self, data: dict[str, object]) -> None:
        """Ask the loader for this asset's large preview.

        data: the row's role values.
        Returns None. The loader answers from its cache or schedules a render;
        either way this call does not block the GUI thread.
        """
        sha256 = data.get("sha256")
        paths = data.get("paths")
        if not isinstance(sha256, str) or not isinstance(paths, tuple) or not paths:
            self.image_label.setText("This asset has no stored copy to preview.")
            return
        try:
            entry = self.previews.previews_entry(sha256, str(paths[0]))
        except ValueError as error:
            self.image_label.setText(f"Preview unavailable: {error}")
            return
        if entry.state is PreviewState.READY and entry.pixmap is not None:
            self.pixmap = entry.pixmap
            self.viewer_scale_image()
        elif entry.state is PreviewState.FAILED:
            self.image_label.setText(f"Preview unavailable: {entry.error}")
        else:
            self.image_label.setText("Loading preview...")

    def viewer_scale_image(self) -> None:
        """Fit the rendered preview to the dialog without ever enlarging it."""
        if self.pixmap is None:
            return
        area = self.image_label.size()
        if area.width() <= 0 or area.height() <= 0:
            return
        scaled = self.pixmap.scaled(
            area, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)

    def viewer_preview_settled(self, sha256: str, size: int, error: str = "") -> None:
        """Adopt a finished render when it belongs to the asset on screen.

        sha256: the hash that finished rendering.
        size: the bounding-box size it was rendered at.
        error: the failure text, empty for a successful render.
        Returns None.
        """
        data = self.viewer_row_data(self.row)
        if data is None or data.get("sha256") != sha256:
            return
        self.viewer_request_preview(data)

    def viewer_update_navigation(self) -> None:
        """Enable prev/next according to the rows currently loaded."""
        self.previous_button.setEnabled(self.row > 0)
        self.next_button.setEnabled(
            self.row + 1 < self.assets.rowCount() or self.assets.canFetchMore()
        )

    def viewer_previous(self) -> None:
        """Step back one asset, if there is one."""
        if self.row > 0:
            self.viewer_show_row(self.row - 1)

    def viewer_next(self) -> None:
        """Step forward one asset, pulling another page when the view ends.

        Returns None. The model is paged, so the end of the loaded rows is not
        the end of the library.
        """
        if self.row + 1 < self.assets.rowCount():
            self.viewer_show_row(self.row + 1)
        elif self.assets.canFetchMore():
            self.advance_pending = True
            self.assets.fetchMore()

    def viewer_page_loaded(self, count: int) -> None:
        """Complete a Next that had to wait for another page to arrive.

        count: how many rows the page added.
        Returns None.
        """
        advance = self.advance_pending
        self.advance_pending = False
        if advance and self.row + 1 < self.assets.rowCount():
            self.viewer_show_row(self.row + 1)
        else:
            self.viewer_update_navigation()

    def viewer_model_reset(self) -> None:
        """Close the viewer when the rows beneath it are replaced.

        Returns None. After a scope change or a mutation, row numbers mean
        something different, so continuing to show "row 12" would show a
        different asset than the one the user opened.
        """
        self.reject()

    def viewer_emit_action(self, key: str) -> None:
        """Forward an action for the asset on screen.

        key: the action key that was activated.
        Returns None.
        """
        self.viewer_action.emit(key, self.row)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Support arrow-key navigation, as an image viewer is expected to."""
        if event.key() == Qt.Key.Key_Left:
            self.viewer_previous()
            return
        if event.key() == Qt.Key.Key_Right:
            self.viewer_next()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-fit the preview when the dialog is resized."""
        super().resizeEvent(event)
        self.viewer_scale_image()
