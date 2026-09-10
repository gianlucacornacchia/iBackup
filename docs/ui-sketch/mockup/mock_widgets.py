"""Reusable widgets for the clickable mock: icons, navigation, grid, command bar.

MOCK ONLY. Icons are drawn with QPainter so the mock needs no binary assets;
the real GUI would use the MIT-licensed fluentui-system-icons SVG set per
ui-sketch/README.md section 0.5.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from mock_data import MockArchive, MockAsset, mock_data_format_size
from mock_tokens import (
    CONTROL_RADIUS,
    NAV_WIDTH,
    RAIL_WIDTH,
    ROW_HEIGHT,
    TILE_SIZE,
    tokens_accent,
    tokens_color,
    tokens_font,
)

ASSET_ROLE = Qt.ItemDataRole.UserRole + 1
NAV_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
NAV_LABEL_ROLE = Qt.ItemDataRole.UserRole + 3
NAV_COUNT_ROLE = Qt.ItemDataRole.UserRole + 4
NAV_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 5
NAV_HEADER_ROLE = Qt.ItemDataRole.UserRole + 6


def widgets_draw_glyph(painter: QPainter, rect: QRect, glyph: str, color: QColor) -> None:
    """Draw one simple line-art icon.

    painter: an active painter.
    rect: the square area to draw inside.
    glyph: the icon name.
    color: the stroke color, following the current theme.
    """
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    box = rect.adjusted(3, 3, -3, -3)
    left, top, right, bottom = box.left(), box.top(), box.right(), box.bottom()
    middle_x, middle_y = box.center().x(), box.center().y()

    if glyph == "photos":
        painter.drawRoundedRect(box, 2, 2)
        painter.drawEllipse(QPoint(left + 4, top + 4), 1, 1)
        painter.drawPolyline([QPoint(left, bottom - 3), QPoint(middle_x, middle_y), QPoint(right, bottom)])
    elif glyph == "album":
        painter.drawRoundedRect(QRect(left, top + 2, box.width() - 3, box.height() - 2), 2, 2)
        painter.drawLine(left + 3, top, right, top)
    elif glyph == "unsorted":
        painter.drawRoundedRect(box, 2, 2)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "?")
    elif glyph == "phone":
        painter.drawRoundedRect(QRect(left + 2, top, box.width() - 4, box.height()), 2, 2)
        painter.drawLine(middle_x - 2, bottom - 2, middle_x + 2, bottom - 2)
    elif glyph == "recycle":
        painter.drawLine(left, top + 2, right, top + 2)
        painter.drawPolyline(
            [QPoint(left + 2, top + 2), QPoint(left + 3, bottom), QPoint(right - 3, bottom), QPoint(right - 2, top + 2)]
        )
    elif glyph == "mark":
        painter.drawLine(middle_x, top, middle_x, bottom - 4)
        painter.drawEllipse(QPoint(middle_x, bottom - 1), 1, 1)
    elif glyph == "settings":
        painter.drawEllipse(box.center(), 3, 3)
        for offset in (-1, 1):
            painter.drawLine(middle_x + offset * 6, middle_y, middle_x + offset * 4, middle_y)
            painter.drawLine(middle_x, middle_y + offset * 6, middle_x, middle_y + offset * 4)
    elif glyph == "import":
        painter.drawLine(middle_x, top, middle_x, bottom - 3)
        painter.drawPolyline(
            [QPoint(middle_x - 3, bottom - 6), QPoint(middle_x, bottom - 3), QPoint(middle_x + 3, bottom - 6)]
        )
        painter.drawLine(left, bottom, right, bottom)
    elif glyph == "verify":
        painter.drawPolyline([QPoint(left, middle_y), QPoint(middle_x - 1, bottom - 2), QPoint(right, top)])
    elif glyph == "scan":
        painter.drawEllipse(box.adjusted(1, 1, -3, -3))
        painter.drawLine(right - 3, bottom - 3, right, bottom)
    elif glyph == "broom":
        painter.drawLine(right - 1, top, middle_x - 1, middle_y)
        painter.drawPolygon([QPoint(middle_x - 4, middle_y - 2), QPoint(middle_x + 3, middle_y + 4), QPoint(left, bottom)])
    elif glyph == "more":
        for offset in (-5, 0, 5):
            painter.drawEllipse(QPoint(middle_x + offset, middle_y), 1, 1)
    elif glyph == "hamburger":
        for offset in (-4, 0, 4):
            painter.drawLine(left, middle_y + offset, right, middle_y + offset)
    elif glyph == "search":
        painter.drawEllipse(QPoint(middle_x - 1, middle_y - 1), 4, 4)
        painter.drawLine(middle_x + 2, middle_y + 2, right, bottom)


def widgets_icon(glyph: str, color: QColor | None = None, size: int = 16) -> QIcon:
    """Build a themed QIcon for a glyph name.

    glyph: the icon name understood by widgets_draw_glyph.
    color: stroke color; defaults to primary text.
    size: icon edge length in pixels.
    Returns a QIcon holding the drawn pixmap.
    """
    if color is None:
        color = tokens_color("TextFillColorPrimary")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    widgets_draw_glyph(painter, QRect(0, 0, size, size), glyph, color)
    painter.end()
    return QIcon(pixmap)


class TileDelegate(QStyledItemDelegate):
    """Draws grid tiles as Fluent cards with accent outline and check circle."""

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Keep the archive so the delegate can fetch placeholder thumbnails."""
        super().__init__(parent)
        self.archive = archive

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Render one tile, including hover lift and selection affordances."""
        asset: MockAsset = index.data(ASSET_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 4, -4, -4)
        image_rect = QRect(rect.left(), rect.top(), rect.width(), rect.width())
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        path = QPainterPath()
        path.addRoundedRect(image_rect, CONTROL_RADIUS, CONTROL_RADIUS)
        painter.setClipPath(path)
        painter.drawPixmap(image_rect, self.archive.mock_archive_thumbnail(asset))
        painter.setClipping(False)

        if hovered and not selected:
            painter.setPen(QPen(tokens_color("ControlStrokeColorDefault"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(image_rect, CONTROL_RADIUS, CONTROL_RADIUS)

        if selected:
            accent = tokens_accent()
            painter.setPen(QPen(accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(image_rect.adjusted(1, 1, -1, -1), CONTROL_RADIUS, CONTROL_RADIUS)
            check_center = QPoint(image_rect.right() - 12, image_rect.top() + 12)
            painter.setBrush(accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(check_center, 8, 8)
            painter.setPen(QPen(QColor("white"), 1.6))
            painter.drawPolyline(
                [
                    QPoint(check_center.x() - 3, check_center.y()),
                    QPoint(check_center.x() - 1, check_center.y() + 3),
                    QPoint(check_center.x() + 4, check_center.y() - 3),
                ]
            )

        if asset.media_type == "video":
            painter.setBrush(QColor(0, 0, 0, 130))
            painter.setPen(Qt.PenStyle.NoPen)
            badge = QRect(image_rect.left() + 6, image_rect.bottom() - 22, 34, 16)
            painter.drawRoundedRect(badge, 8, 8)
            painter.setPen(QColor("white"))
            painter.setFont(tokens_font("caption"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "video")

        painter.setFont(tokens_font("caption"))
        painter.setPen(tokens_color("TextFillColorSecondary"))
        caption_rect = QRect(rect.left(), image_rect.bottom() + 4, rect.width(), 16)
        name = asset.name if len(asset.name) <= 15 else asset.name[:13] + "..."
        painter.drawText(caption_rect, Qt.AlignmentFlag.AlignLeft, name)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Return a fixed tile footprint including its caption."""
        return QSize(TILE_SIZE, TILE_SIZE + 26)


class PhotoGrid(QListWidget):
    """Virtualized thumbnail grid with rubber-band and keyboard multi-select."""

    selection_changed = Signal(list)
    asset_activated = Signal(object)

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Configure icon mode, extended selection and the Fluent tile delegate."""
        super().__init__(parent)
        self.archive = archive
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(TileDelegate(archive, self))
        self.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.setMouseTracking(True)
        self.itemSelectionChanged.connect(self.photo_grid_emit_selection)
        self.itemDoubleClicked.connect(
            lambda item: self.asset_activated.emit(item.data(ASSET_ROLE))
        )

    def photo_grid_show(self, assets: list[MockAsset]) -> None:
        """Replace the grid contents.

        assets: the assets to display, in order.
        """
        self.clear()
        for asset in assets:
            item = QListWidgetItem()
            item.setData(ASSET_ROLE, asset)
            item.setSizeHint(QSize(TILE_SIZE, TILE_SIZE + 26))
            self.addItem(item)

    def photo_grid_selected_assets(self) -> list[MockAsset]:
        """Return the currently selected assets."""
        return [item.data(ASSET_ROLE) for item in self.selectedItems()]

    def photo_grid_emit_selection(self) -> None:
        """Notify listeners that the selection changed."""
        self.selection_changed.emit(self.photo_grid_selected_assets())


class NavRowDelegate(QStyledItemDelegate):
    """Draws navigation rows with an accent selection pill and a right count."""

    def __init__(self, pane: NavigationPane) -> None:
        """Keep the pane so the delegate knows whether it is collapsed."""
        super().__init__(pane)
        self.pane = pane

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Render a section header or a navigation row."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(6, 1, -6, -1)

        if index.data(NAV_HEADER_ROLE):
            if not self.pane.collapsed:
                painter.setFont(tokens_font("caption"))
                painter.setPen(tokens_color("TextFillColorSecondary"))
                painter.drawText(
                    rect.adjusted(8, 0, 0, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(index.data(Qt.ItemDataRole.DisplayRole)),
                )
            painter.restore()
            return

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(tokens_color("CardBackgroundFillColorDefault"))
            painter.setPen(QPen(tokens_color("ControlStrokeColorDefault"), 1))
            painter.drawRoundedRect(rect, CONTROL_RADIUS, CONTROL_RADIUS)
            # The Windows 11 selection pill: a short accent bar on the leading edge.
            painter.setBrush(tokens_accent())
            painter.setPen(Qt.PenStyle.NoPen)
            pill = QRect(rect.left() + 1, rect.center().y() - 8, 3, 17)
            painter.drawRoundedRect(pill, 1.5, 1.5)
        elif hovered:
            painter.setBrush(tokens_color("SubtleFillColorSecondary"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, CONTROL_RADIUS, CONTROL_RADIUS)

        text_color = tokens_color("TextFillColorPrimary")
        icon_rect = QRect(rect.left() + 12, rect.center().y() - 8, 16, 16)
        widgets_draw_glyph(painter, icon_rect, str(index.data(NAV_GLYPH_ROLE)), text_color)

        if not self.pane.collapsed:
            painter.setFont(tokens_font("body_strong" if selected else "body"))
            painter.setPen(text_color)
            label_rect = rect.adjusted(40, 0, -52, 0)
            label = painter.fontMetrics().elidedText(
                str(index.data(NAV_LABEL_ROLE)), Qt.TextElideMode.ElideRight, label_rect.width()
            )
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setFont(tokens_font("caption"))
            painter.setPen(tokens_color("TextFillColorSecondary"))
            painter.drawText(
                rect.adjusted(0, 0, -12, 0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{index.data(NAV_COUNT_ROLE):,}".replace(",", " "),
            )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Return the 40px row height, or a shorter band for section headers."""
        if index.data(NAV_HEADER_ROLE):
            return QSize(0, 0 if self.pane.collapsed else 30)
        return QSize(0, ROW_HEIGHT)


class NavigationPane(QWidget):
    """NavigationView-style left pane with a selection pill and pinned settings."""

    view_selected = Signal(str)
    settings_requested = Signal()

    def __init__(self, archive: MockArchive, parent: QWidget | None = None) -> None:
        """Build the collapsible navigation rows from the fake archive."""
        super().__init__(parent)
        self.archive = archive
        self.collapsed = False
        self.setObjectName("NavPane")
        self.setFixedWidth(NAV_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("Command")
        self.toggle_button.setIcon(widgets_icon("hamburger"))
        self.toggle_button.setFixedSize(40, 36)
        self.toggle_button.setToolTip("Collapse navigation")
        self.toggle_button.clicked.connect(self.navigation_pane_toggle)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(6, 0, 6, 4)
        top_row.addWidget(self.toggle_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.search_row = QPushButton("  Search")
        self.search_row.setObjectName("Command")
        self.search_row.setIcon(widgets_icon("search"))
        self.search_row.setFixedHeight(ROW_HEIGHT - 4)
        self.search_row.setToolTip("Search is a planned presentation feature")
        layout.addWidget(self.search_row)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("NavList")
        self.list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self.list_widget.setFont(tokens_font("body"))
        self.list_widget.setMouseTracking(True)
        self.list_widget.setItemDelegate(NavRowDelegate(self))
        self.list_widget.currentItemChanged.connect(self.navigation_pane_changed)
        layout.addWidget(self.list_widget, 1)

        self.settings_button = QPushButton("  Settings")
        self.settings_button.setObjectName("Command")
        self.settings_button.setIcon(widgets_icon("settings"))
        self.settings_button.setFixedHeight(ROW_HEIGHT)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_button)

        self.navigation_pane_populate()

    def navigation_pane_populate(self) -> None:
        """Fill the pane with library sections, albums and their counts."""
        self.list_widget.clear()
        self.navigation_pane_add_header("Library")
        counts = {
            "all": len(self.archive.assets),
            "unsorted": len(self.archive.unsorted_ids),
            "deleted-phone": len(self.archive.deleted_on_phone_ids),
            "recycled": len(self.archive.recycled_ids),
            "marked": len(self.archive.marked_ids),
        }
        rows = [
            ("all", "All photos", "photos"),
            ("unsorted", "Unsorted", "unsorted"),
            ("deleted-phone", "Deleted from phone", "phone"),
            ("recycled", "Recycle bin", "recycle"),
            ("marked", "Marked", "mark"),
        ]
        for key, label, glyph in rows:
            self.navigation_pane_add_row(key, label, glyph, counts[key])
        self.navigation_pane_add_header("Albums")
        for album in self.archive.albums:
            self.navigation_pane_add_row(
                f"album:{album.name}", album.name, "album", len(album.asset_ids)
            )
        self.list_widget.setCurrentRow(1)

    def navigation_pane_add_header(self, text: str) -> None:
        """Add a non-selectable section header.

        text: the header caption.
        """
        item = QListWidgetItem(text.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(NAV_HEADER_ROLE, True)
        self.list_widget.addItem(item)

    def navigation_pane_add_row(self, key: str, label: str, glyph: str, count: int) -> None:
        """Add one navigation row.

        key: the view key emitted on selection.
        label: the visible row text.
        glyph: icon name.
        count: right-aligned item count.
        """
        item = QListWidgetItem()
        item.setData(NAV_KEY_ROLE, key)
        item.setData(NAV_LABEL_ROLE, label)
        item.setData(NAV_GLYPH_ROLE, glyph)
        item.setData(NAV_COUNT_ROLE, count)
        item.setData(NAV_HEADER_ROLE, False)
        item.setData(Qt.ItemDataRole.ToolTipRole, f"{label} - {count} items")
        self.list_widget.addItem(item)

    def navigation_pane_select(self, key: str) -> None:
        """Move the selection pill to a view key without re-emitting churn.

        key: the view key to select.
        """
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(NAV_KEY_ROLE) == key:
                self.list_widget.setCurrentItem(item)
                return

    def navigation_pane_changed(self, current: QListWidgetItem | None) -> None:
        """Emit the selected view key.

        current: the newly selected row, if any.
        """
        if current is not None:
            key = current.data(NAV_KEY_ROLE)
            if key:
                self.view_selected.emit(key)

    def navigation_pane_toggle(self) -> None:
        """Collapse to an icon rail, or expand back to the full pane."""
        self.collapsed = not self.collapsed
        self.setFixedWidth(RAIL_WIDTH + 16 if self.collapsed else NAV_WIDTH)
        self.search_row.setText("" if self.collapsed else "  Search")
        self.settings_button.setText("" if self.collapsed else "  Settings")
        self.toggle_button.setToolTip(
            "Expand navigation" if self.collapsed else "Collapse navigation"
        )
        # The delegate reads self.collapsed, so only the row heights need updating.
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(NAV_HEADER_ROLE):
                item.setSizeHint(QSize(0, 0 if self.collapsed else 30))
            else:
                item.setSizeHint(QSize(0, ROW_HEIGHT))
        self.list_widget.viewport().update()


class CommandBar(QFrame):
    """Top command bar holding the primary verbs plus an overflow menu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the card surface that hosts command buttons."""
        super().__init__(parent)
        self.setObjectName("CommandBar")
        self.layout_row = QHBoxLayout(self)
        self.layout_row.setContentsMargins(8, 6, 8, 6)
        self.layout_row.setSpacing(4)
        self.layout_row.addStretch(1)

    def command_bar_add(
        self, label: str, glyph: str, handler: Callable[[], None], tooltip: str = ""
    ) -> QPushButton:
        """Add a command button before the trailing stretch.

        label: button caption in sentence case.
        glyph: icon name.
        handler: click callback.
        tooltip: optional explanatory tooltip.
        Returns the created button so callers can enable/disable it.
        """
        button = QPushButton(f" {label}")
        button.setObjectName("Command")
        button.setIcon(widgets_icon(glyph))
        button.setFont(tokens_font("body"))
        button.setMinimumHeight(30)
        button.clicked.connect(handler)
        if tooltip:
            button.setToolTip(tooltip)
        self.layout_row.insertWidget(self.layout_row.count() - 1, button)
        return button


class SelectionBar(QFrame):
    """Slide-in bar showing selection count, size and batch actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the hidden-by-default selection action bar."""
        super().__init__(parent)
        self.setObjectName("Card")
        self.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.summary_label = QLabel()
        self.summary_label.setFont(tokens_font("body_strong"))
        row.addWidget(self.summary_label)
        row.addStretch(1)
        self.button_row = row

    def selection_bar_update(self, assets: list[MockAsset]) -> None:
        """Show or hide the bar based on the current selection.

        assets: the currently selected assets.
        """
        self.setVisible(bool(assets))
        total = sum(asset.size for asset in assets)
        self.summary_label.setText(
            f"{len(assets)} selected - {mock_data_format_size(total)}"
        )

    def selection_bar_add(
        self, label: str, handler: Callable[[], None], style: str = "Command"
    ) -> QPushButton:
        """Add a batch-action button.

        label: button caption.
        handler: click callback.
        style: object name selecting the QSS treatment.
        Returns the created button.
        """
        button = QPushButton(label)
        button.setObjectName(style)
        button.setFont(tokens_font("body"))
        button.setMinimumHeight(30)
        button.clicked.connect(handler)
        self.button_row.addWidget(button)
        return button
