"""Thumbnail grid, tile painting and the selection action bar.

This is the page the sketch calls "content-first": the grid *is* the view, and
the chrome around it stays minimal. It is bound directly to the paged
``AssetModel`` rather than to a copied list, so an archive with tens of
thousands of assets never materialises in the GUI - rows arrive one bounded page
at a time as the user scrolls.

Tiles are painted by a delegate rather than built as widgets. A widget per asset
would cost several kilobytes and a layout pass each, whereas the delegate draws
only what is on screen. The delegate never touches the disk: it asks the preview
loader for a tile, which either answers from its cache or schedules a background
render, so painting stays on the GUI thread's budget.

Selection is handed back as the model's exact copy scope - asset **and** file
IDs bound to a model generation - so a later destructive operation acts on the
copies the user actually saw, not on whatever now occupies those row numbers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .models import AssetModel, AssetRole, AssetSelection
from .previews import PreviewEntry, PreviewLoader, PreviewState
from .theme import CONTROL_HEIGHT, CONTROL_RADIUS, GROUP_GAP, theme_font

LOGGER = logging.getLogger(__name__)
ModelIndex = QModelIndex | QPersistentModelIndex

TILE_IMAGE = 120
TILE_CAPTION = 22
TILE_PADDING = 4
TILE_SPACING = 4
CHECK_RADIUS = 8
BADGE_HEIGHT = 16
# Renders are cancelled for tiles this far outside the viewport; a margin keeps
# a small scroll from throwing away work that is about to be needed again.
PREFETCH_MARGIN = 2 * TILE_IMAGE
# Repaints are coalesced: a burst of finished renders must not cause one full
# viewport repaint each.
REPAINT_INTERVAL_MS = 24
# Declared once so the selection bar and the context menu can never drift apart.
SELECTION_ACTIONS = (
    ("open", "Open"),
    ("move", "Move to album..."),
    ("mark", "Mark"),
    ("delete", "Delete..."),
    ("restore", "Restore"),
    ("purge", "Purge..."),
)


def gallery_format_size(total: int) -> str:
    """Render a byte count the way the sketch's selection bar shows it.

    total: a size in bytes.
    Returns a short human-readable string such as "14.6 MB".
    """
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("Size must be a non-negative integer")
    value = float(total)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def gallery_elide(text: str, metrics: QFontMetrics, width: int) -> str:
    """Shorten a caption to the tile width using the font's own measurements.

    text: the caption to shorten.
    metrics: metrics for the font the caption will be drawn with.
    width: the available width in pixels.
    Returns the possibly elided caption.
    """
    return str(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width))


class TileDelegate(QStyledItemDelegate):
    """Paints one asset as a Fluent card with selection and media affordances."""

    def __init__(self, previews: PreviewLoader, parent: QWidget | None = None) -> None:
        """Bind the preview loader the delegate asks for tile images.

        previews: the GUI-affine preview loader.
        parent: the owning view.
        """
        super().__init__(parent)
        self.previews = previews

    def tile_entry(self, index: ModelIndex) -> tuple[str, PreviewEntry | None]:
        """Ask the loader for this row's preview without ever blocking the GUI.

        index: the row being painted.
        Returns the asset hash and its preview entry, or (hash, None) when the
        row has no stored copy to render from.
        """
        sha256 = index.data(int(AssetRole.SHA256))
        paths = index.data(int(AssetRole.PATHS))
        if not isinstance(sha256, str) or not isinstance(paths, tuple) or not paths:
            return (sha256 if isinstance(sha256, str) else ""), None
        try:
            return sha256, self.previews.previews_entry(sha256, paths[0])
        except ValueError as error:
            LOGGER.debug("tile %s cannot be previewed: %s", sha256, error)
            return sha256, PreviewEntry(PreviewState.FAILED, error=str(error))

    def tile_paint_image(
        self, painter: QPainter, rect: QRect, entry: PreviewEntry | None, palette_text: QColor
    ) -> None:
        """Draw the tile's image area: the preview, or its pending/failed stand-in.

        painter: the active painter.
        rect: the square image area.
        entry: the preview entry, or None when there is nothing to render.
        palette_text: the text colour to dim for stand-in glyphs.
        Returns None.
        """
        path = QPainterPath()
        path.addRoundedRect(rect, CONTROL_RADIUS, CONTROL_RADIUS)
        painter.save()
        painter.setClipPath(path)
        backdrop = QColor(palette_text)
        backdrop.setAlpha(18)
        painter.fillRect(rect, backdrop)
        if entry is not None and entry.state is PreviewState.READY and entry.pixmap is not None:
            pixmap: QPixmap = entry.pixmap
            scaled = pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            target = QRect(QPoint(0, 0), scaled.size())
            target.moveCenter(rect.center())
            painter.drawPixmap(target, scaled)
        else:
            faded = QColor(palette_text)
            faded.setAlpha(110)
            painter.setPen(faded)
            painter.setFont(theme_font("caption"))
            failed = entry is not None and entry.state is PreviewState.FAILED
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "no preview" if failed else "...")
        painter.restore()

    def tile_paint_selection(self, painter: QPainter, rect: QRect, accent: QColor) -> None:
        """Draw the accent outline and check circle used for selected tiles.

        painter: the active painter.
        rect: the tile's image area.
        accent: the system accent colour.
        Returns None.
        """
        painter.setPen(QPen(accent, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), CONTROL_RADIUS, CONTROL_RADIUS)
        center = QPoint(rect.right() - 12, rect.top() + 12)
        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, CHECK_RADIUS, CHECK_RADIUS)
        painter.setPen(QPen(QColor("white"), 1.6))
        painter.drawPolyline(
            [
                QPoint(center.x() - 3, center.y()),
                QPoint(center.x() - 1, center.y() + 3),
                QPoint(center.x() + 4, center.y() - 3),
            ]
        )

    def tile_paint_badge(self, painter: QPainter, rect: QRect, label: str) -> None:
        """Draw a dark rounded badge in the tile's bottom-left corner.

        painter: the active painter.
        rect: the tile's image area.
        label: the short badge text.
        Returns None.
        """
        painter.setFont(theme_font("caption"))
        width = painter.fontMetrics().horizontalAdvance(label) + 14
        badge = QRect(rect.left() + 6, rect.bottom() - 22, width, BADGE_HEIGHT)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge, 8, 8)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        """Render one tile: preview, selection state, media badge and caption."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = option.palette
        text_color = palette.color(palette.ColorRole.Text)
        accent = palette.color(palette.ColorRole.Accent)
        rect = option.rect.adjusted(TILE_PADDING, TILE_PADDING, -TILE_PADDING, -TILE_PADDING)
        image_rect = QRect(rect.left(), rect.top(), rect.width(), rect.width())

        sha256, entry = self.tile_entry(index)
        self.tile_paint_image(painter, image_rect, entry, text_color)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            self.tile_paint_selection(painter, image_rect, accent)
        elif hovered:
            stroke = QColor(text_color)
            stroke.setAlpha(80)
            painter.setPen(QPen(stroke, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(image_rect, CONTROL_RADIUS, CONTROL_RADIUS)

        if index.data(int(AssetRole.MEDIA_TYPE)) == "video":
            self.tile_paint_badge(painter, image_rect, "video")

        caption = index.data(int(AssetRole.ORIGINAL_NAME))
        painter.setFont(theme_font("caption"))
        faded = QColor(text_color)
        faded.setAlpha(160)
        painter.setPen(faded)
        caption_rect = QRect(rect.left(), image_rect.bottom() + 4, rect.width(), TILE_CAPTION - 4)
        painter.drawText(
            caption_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            gallery_elide(
                str(caption) if caption is not None else sha256[:12],
                painter.fontMetrics(),
                caption_rect.width(),
            ),
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        """Return a fixed tile footprint so the view can lay out without measuring rows."""
        edge = TILE_IMAGE + 2 * TILE_PADDING
        return QSize(edge, edge + TILE_CAPTION)


class AssetGrid(QListView):
    """Icon-mode grid over the paged asset model, with preview-aware scrolling."""

    grid_selection_changed = Signal(int)
    grid_activated = Signal(int)
    grid_context_requested = Signal(QPoint)

    def __init__(
        self, model: AssetModel, previews: PreviewLoader, parent: QWidget | None = None
    ) -> None:
        """Bind the shared asset model and preview loader to a virtualised grid.

        model: the paged asset model.
        previews: the GUI-affine preview loader.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("AssetGrid")
        self.previews = previews
        self.assets = model
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSpacing(TILE_SPACING)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(TileDelegate(previews, self))
        self.setModel(model)

        # Owned by the grid, not a bare QTimer.singleShot: a deferred pump that
        # outlives its view would call into a destroyed model and worker.
        self.pump_timer = QTimer(self)
        self.pump_timer.setSingleShot(True)
        self.pump_timer.setInterval(0)
        self.pump_timer.timeout.connect(self.grid_pump)
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.setInterval(REPAINT_INTERVAL_MS)
        self.repaint_timer.timeout.connect(self.grid_repaint)
        previews.preview_ready.connect(self.grid_preview_settled)
        previews.preview_failed.connect(self.grid_preview_settled)
        model.page_loaded.connect(self.grid_page_loaded)
        model.modelReset.connect(self.grid_model_reset)
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self.grid_scrolled)
        selection = self.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self.grid_selection_emit)
        self.customContextMenuRequested.connect(self.grid_context_requested.emit)
        self.activated.connect(self.grid_row_activated)
        self.doubleClicked.connect(self.grid_row_activated)

    def grid_repaint(self) -> None:
        """Repaint the visible tiles after a burst of finished renders."""
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def grid_preview_settled(self, sha256: str, size: int, error: str = "") -> None:
        """Schedule a coalesced repaint when any preview finishes.

        sha256: the asset hash that finished rendering.
        size: the bounding-box size it was rendered at.
        error: the failure text, empty for a successful render.
        Returns None. Repainting the whole viewport is bounded by what is on
        screen and is cheaper than mapping hashes back to row numbers.
        """
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()

    def grid_anchor_row(self) -> int | None:
        """Find one row that is certainly on screen, to walk outwards from.

        Returns a visible row number, or None when the viewport shows no tile.
        Probing a few points is O(1); scanning every loaded row would make each
        scroll event cost more as the library grows, which is exactly what the
        paged model exists to avoid.
        """
        viewport = self.viewport()
        if viewport is None:
            return None
        rect = viewport.rect()
        if rect.isEmpty():
            return None
        for fraction_y in (0.5, 0.0, 1.0, 0.25, 0.75):
            for fraction_x in (0.5, 0.0, 1.0, 0.25, 0.75):
                point = QPoint(
                    min(rect.right(), int(rect.width() * fraction_x)),
                    min(rect.bottom(), int(rect.height() * fraction_y)),
                )
                index = self.indexAt(point)
                if index.isValid():
                    return int(index.row())
        return None

    def grid_rows_in_view(self, margin: int = PREFETCH_MARGIN) -> list[int]:
        """List the row numbers inside the viewport plus a prefetch margin.

        margin: extra pixels above and below the viewport to treat as visible.
        Returns the row numbers in ascending order, which may be empty. The walk
        stops as soon as it leaves the area, so its cost follows the number of
        visible tiles rather than the number of loaded rows.
        """
        viewport = self.viewport()
        total = self.assets.rowCount()
        if viewport is None or total == 0:
            return []
        anchor = self.grid_anchor_row()
        if anchor is None:
            return []
        area = viewport.rect().adjusted(0, -margin, 0, margin)
        rows = [anchor]
        for step, limit in ((1, total), (-1, -1)):
            row = anchor + step
            while row != limit:
                index = self.assets.index(row)
                if not index.isValid():
                    break
                tile = self.visualRect(index)
                if not area.intersects(tile):
                    # Tiles are laid out row-major with increasing y, so the
                    # first miss beyond the area ends this direction.
                    if tile.top() > area.bottom() or tile.bottom() < area.top():
                        break
                else:
                    rows.append(row)
                row += step
        return sorted(rows)

    def grid_visible_hashes(self) -> set[str]:
        """Collect the asset hashes currently worth rendering.

        Returns the set of hashes inside the viewport plus its prefetch margin.
        """
        hashes: set[str] = set()
        for row in self.grid_rows_in_view():
            value = self.assets.index(row).data(int(AssetRole.SHA256))
            if isinstance(value, str) and value:
                hashes.add(value)
        return hashes

    def grid_scrolled(self, value: int = 0) -> None:
        """Drop scrolled-past renders and pull the next page when near the end.

        value: the new scrollbar position, unused.
        Returns None. Nothing is cancelled when no tile could be located, since
        a momentarily unlaid-out viewport must not throw away the renders that
        are about to be painted.
        """
        wanted = self.grid_visible_hashes()
        if wanted or self.assets.rowCount() == 0:
            self.previews.previews_cancel_stale(wanted)
        self.grid_pump()

    def grid_pump(self) -> None:
        """Fetch another page while the last tiles are within reach of the viewport.

        Returns None. The model refuses overlapping pages itself, so this is
        safe to call on every scroll event.
        """
        if not self.assets.canFetchMore():
            return
        bar = self.verticalScrollBar()
        viewport = self.viewport()
        if bar is None or viewport is None:
            return
        near_end = bar.maximum() == 0 or bar.value() >= bar.maximum() - viewport.height()
        if near_end:
            self.assets.fetchMore()

    def grid_page_loaded(self, count: int) -> None:
        """Keep paging until the viewport is actually full.

        count: how many rows the page added.
        Returns None. One page can be shorter than the visible area, and Qt only
        asks for more when the user scrolls, so an unfilled grid would stall.
        The pump is deferred so the next request is never submitted from inside
        the model's own page-insertion notification.
        """
        self.pump_timer.start()

    def grid_model_reset(self) -> None:
        """Start filling a newly scoped view and drop renders for the old one."""
        self.previews.previews_cancel_all()
        self.scrollToTop()
        self.pump_timer.start()
        self.grid_selection_emit()

    def grid_row_activated(self, index: ModelIndex) -> None:
        """Report a double-click or Enter on a tile as a row activation."""
        if index.isValid():
            self.grid_activated.emit(index.row())

    def grid_selection_emit(self, *arguments: object) -> None:
        """Announce how many tiles are selected after any selection change."""
        self.grid_selection_changed.emit(len(self.grid_selected_rows()))

    def grid_selected_rows(self) -> list[int]:
        """Return the selected row numbers in view order.

        Returns a sorted list of row numbers, empty when nothing is selected.
        """
        selection = self.selectionModel()
        if selection is None:
            return []
        return sorted(index.row() for index in selection.selectedIndexes() if index.isValid())

    def grid_selected_size(self) -> int:
        """Total the byte size of the selected assets.

        Returns the sum of their sizes, ignoring rows without a usable size.
        """
        total = 0
        for row in self.grid_selected_rows():
            value = self.assets.index(row).data(int(AssetRole.SIZE))
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                total += value
        return total

    def grid_selection(self) -> AssetSelection:
        """Capture the selection as the model's exact copy scope.

        Returns an ``AssetSelection`` bound to the current model generation.
        Raises ``ValueError`` when the selection is empty or no longer valid.
        """
        rows = self.grid_selected_rows()
        if not rows:
            raise ValueError("Nothing is selected")
        return self.assets.asset_model_selection([self.assets.index(row) for row in rows])

    def grid_select_all(self) -> None:
        """Select every loaded row, which is what the user can actually see."""
        self.selectAll()

    def grid_clear_selection(self) -> None:
        """Drop the current selection, for example after a mutation."""
        self.clearSelection()

    def resizeEvent(self, event: QEvent) -> None:
        """Re-evaluate paging and preview relevance when the viewport changes size."""
        super().resizeEvent(event)  # type: ignore[arg-type]
        self.grid_scrolled()


class SelectionBar(QFrame):
    """Batch actions for the current selection; hidden while nothing is selected."""

    selection_action = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the bar with every action; visibility follows the selection."""
        super().__init__(parent)
        self.setObjectName("Card")
        self.setVisible(False)
        self.buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(GROUP_GAP)
        self.summary_label = QLabel("", self)
        self.summary_label.setFont(theme_font("body_strong"))
        row.addWidget(self.summary_label)
        row.addStretch(1)
        for key, label in SELECTION_ACTIONS:
            button = QPushButton(label, self)
            button.setObjectName("Command")
            button.setFont(theme_font("body"))
            button.setMinimumHeight(CONTROL_HEIGHT)
            button.clicked.connect(
                lambda checked=False, action=key: self.selection_action.emit(action)
            )
            self.buttons[key] = button
            row.addWidget(button)

    def selection_bar_update(self, count: int, total_size: int, actions: Sequence[str]) -> None:
        """Show the selection summary and only the actions this view supports.

        count: how many assets are selected.
        total_size: their combined size in bytes.
        actions: the action keys to offer, in the order they were declared.
        Returns None.
        """
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Selection count must be a non-negative integer")
        allowed = set(actions)
        unknown = allowed - set(self.buttons)
        if unknown:
            raise ValueError(f"Unknown selection actions: {sorted(unknown)}")
        for key, button in self.buttons.items():
            button.setVisible(key in allowed)
        self.summary_label.setText(
            f"{count} selected - {gallery_format_size(total_size)}" if count else ""
        )
        self.setVisible(count > 0)


class AssetGallery(QWidget):
    """The grid, its empty states and the selection bar, as one page body."""

    gallery_action = Signal(str)
    gallery_open_requested = Signal(int)
    gallery_status = Signal(str)

    def __init__(
        self, model: AssetModel, previews: PreviewLoader, parent: QWidget | None = None
    ) -> None:
        """Compose the gallery around the shared asset model.

        model: the paged asset model.
        previews: the GUI-affine preview loader.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.assets = model
        self.actions_available: tuple[str, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)

        self.stack_host = QWidget(self)
        self.stack = QStackedLayout(self.stack_host)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.grid = AssetGrid(model, previews, self.stack_host)
        self.message_label = QLabel("No archive open.", self.stack_host)
        self.message_label.setObjectName("PlaceholderLabel")
        self.message_label.setProperty("role", "secondary")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.message_label)
        layout.addWidget(self.stack_host, 1)

        self.selection_bar = SelectionBar(self)
        self.selection_bar.selection_action.connect(self.gallery_selection_action)
        layout.addWidget(self.selection_bar)

        self.grid.grid_selection_changed.connect(self.gallery_selection_changed)
        self.grid.grid_activated.connect(self.gallery_open_requested.emit)
        self.grid.grid_context_requested.connect(self.gallery_context_menu)
        self.assets.loading_changed.connect(self.gallery_state_changed)
        self.assets.error_changed.connect(self.gallery_error_changed)
        self.assets.page_loaded.connect(self.gallery_state_changed)
        self.assets.modelReset.connect(self.gallery_state_changed)

    def gallery_set_actions(self, actions: Iterable[str]) -> None:
        """Declare which batch actions the current view supports.

        actions: the action keys offered for this scope.
        Returns None.
        """
        self.actions_available = tuple(actions)
        self.gallery_selection_changed(len(self.grid.grid_selected_rows()))

    def gallery_selection_changed(self, count: int) -> None:
        """Refresh the selection bar whenever the selection changes.

        count: how many tiles are selected.
        Returns None.
        """
        self.selection_bar.selection_bar_update(
            count, self.grid.grid_selected_size(), self.actions_available
        )

    def gallery_selection_action(self, key: str) -> None:
        """Route a selection-bar action, opening the viewer locally.

        key: the action key that was activated.
        Returns None.
        """
        if key == "open":
            rows = self.grid.grid_selected_rows()
            if rows:
                self.gallery_open_requested.emit(rows[0])
            return
        self.gallery_action.emit(key)

    def gallery_build_menu(self, position: QPoint) -> QMenu | None:
        """Select the clicked tile and build its context menu.

        position: the click position in viewport coordinates.
        Returns the menu to show, or None when there is nothing to act on. The
        menu acts on the selection, so a right-click on an unselected tile
        selects it first rather than acting on something else.
        """
        index = self.grid.indexAt(position)
        if index.isValid() and index.row() not in self.grid.grid_selected_rows():
            self.grid.setCurrentIndex(index)
        if not self.grid.grid_selected_rows():
            return None
        menu = QMenu(self)
        for key, label in SELECTION_ACTIONS:
            if key not in self.actions_available:
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, chosen=key: self.gallery_selection_action(chosen)
            )
        if menu.isEmpty():
            menu.deleteLater()
            return None
        return menu

    def gallery_context_menu(self, position: QPoint) -> None:
        """Show the tile context menu at the click position.

        position: the click position in viewport coordinates.
        Returns None. Building the menu is kept separate so it can be inspected
        without entering Qt's modal exec loop.
        """
        menu = self.gallery_build_menu(position)
        if menu is None:
            return
        viewport = self.grid.viewport()
        origin = viewport if viewport is not None else self.grid
        menu.exec(origin.mapToGlobal(position))

    def gallery_state_changed(self, value: object = None) -> None:
        """Show the grid, or the empty/loading/error message that explains its absence.

        value: the signal payload, unused.
        Returns None.
        """
        message = self.gallery_message()
        if message is None:
            self.stack.setCurrentWidget(self.grid)
        else:
            self.message_label.setText(message)
            self.stack.setCurrentWidget(self.message_label)

    def gallery_error_changed(self, message: object) -> None:
        """Report a paging failure that the grid itself cannot show.

        message: the model's error text, or None when it was cleared.
        Returns None. Once rows are on screen the grid keeps showing them, so a
        failed later page would otherwise be invisible.
        """
        self.gallery_state_changed()
        if isinstance(message, str) and self.assets.rowCount() > 0:
            self.gallery_status.emit(f"More items could not be listed: {message}")

    def gallery_message(self) -> str | None:
        """Decide what to show instead of the grid.

        Returns the message text, or None when the grid itself should be shown.
        """
        if self.assets.rowCount() > 0:
            return None
        if not self.assets.active:
            return "No archive open."
        if self.assets.last_error is not None:
            return f"This view could not be listed: {self.assets.last_error}"
        if self.assets.loading:
            return "Loading..."
        return "Nothing to show in this view."
