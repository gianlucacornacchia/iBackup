"""Navigation pane: library sections, albums and their live counts.

The sketch replaces a menu bar with a Windows 11 NavigationView, so this pane is
the app's primary way of moving between views. Rows are painted by a delegate
rather than styled with QSS, because ``::item`` rules double-paint over custom
delegates and the accent selection pill has to follow the live system accent.

The pane holds no archive data of its own: counts and albums are pushed in by
the shell, which reads them through the service worker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .icons import icons_draw, icons_get
from .theme import CONTROL_RADIUS, ROW_HEIGHT, theme_font

NAV_WIDTH = 220
RAIL_WIDTH = 48
NAV_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
NAV_LABEL_ROLE = Qt.ItemDataRole.UserRole + 2
NAV_COUNT_ROLE = Qt.ItemDataRole.UserRole + 3
NAV_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 4
NAV_HEADER_ROLE = Qt.ItemDataRole.UserRole + 5
ALBUM_KEY_PREFIX = "album:"
# Album-wide verbs offered on a right-click. Marking is the only one here: it
# stages a decision and deletes nothing, so it needs no typed confirmation,
# and it is the album equivalent of the CLI's `marks add <id> --album`.
ALBUM_ACTIONS = (("mark", "Mark album for delete"),)
ModelIndex = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class NavigationView:
    """One fixed library row; albums are generated from the catalog instead."""

    key: str
    label: str
    glyph: str
    count_key: str


LIBRARY_VIEWS = (
    NavigationView("all", "All photos", "photos", "assets"),
    NavigationView("unsorted", "Unsorted", "unsorted", "unsorted"),
    NavigationView("deleted-phone", "Deleted from phone", "phone", "deleted_on_phone"),
    NavigationView("recycled", "Recycle bin", "recycle", "recycled"),
    NavigationView("marked", "Marked", "mark", "marked"),
)


def navigation_album_key(album_id: int) -> str:
    """Build the navigation key identifying one album.

    album_id: the catalog album id.
    Returns the key string used by the pane and the page stack.
    """
    if not isinstance(album_id, int) or isinstance(album_id, bool) or album_id <= 0:
        raise ValueError("Album id must be a positive integer")
    return f"{ALBUM_KEY_PREFIX}{album_id}"


def navigation_album_id(key: str) -> int | None:
    """Extract the album id from a navigation key.

    key: a navigation key.
    Returns the album id, or None when the key is not an album row.
    """
    if not isinstance(key, str) or not key.startswith(ALBUM_KEY_PREFIX):
        return None
    suffix = key[len(ALBUM_KEY_PREFIX) :]
    return int(suffix) if suffix.isdigit() else None


def navigation_format_count(count: int | None) -> str:
    """Format a row count with thin thousands separators.

    count: the number of assets, or None when it is not known yet.
    Returns the text drawn at the trailing edge of a row.
    """
    if count is None:
        return ""
    return f"{count:,}".replace(",", "\u2009")


class NavigationRowDelegate(QStyledItemDelegate):
    """Paints section headers and rows with an accent pill and a trailing count."""

    def __init__(self, pane: NavigationPane) -> None:
        """Keep the pane so the delegate knows whether it is collapsed."""
        super().__init__(pane)
        self.pane = pane

    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        """Give headers a shorter row so sections read as groups, not entries."""
        height = 24 if index.data(NAV_HEADER_ROLE) else ROW_HEIGHT
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        """Render one section header or navigation row."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(6, 1, -6, -1)
        palette = option.palette
        primary = palette.color(palette.ColorRole.WindowText)
        secondary = QColor(primary)
        secondary.setAlpha(150)

        if index.data(NAV_HEADER_ROLE):
            if not self.pane.collapsed:
                painter.setFont(theme_font("caption"))
                painter.setPen(secondary)
                painter.drawText(
                    rect.adjusted(8, 0, 0, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(index.data(Qt.ItemDataRole.DisplayRole)),
                )
            painter.restore()
            return

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        subtle = QColor(primary)
        subtle.setAlpha(20)
        if selected:
            painter.setBrush(subtle)
            painter.setPen(QPen(secondary, 1))
            painter.drawRoundedRect(rect, CONTROL_RADIUS, CONTROL_RADIUS)
            # The Windows 11 selection pill: a short accent bar on the leading edge.
            painter.setBrush(palette.color(palette.ColorRole.Highlight))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRect(rect.left() + 1, rect.center().y() - 8, 3, 17), 1.5, 1.5)
        elif hovered:
            subtle.setAlpha(12)
            painter.setBrush(subtle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, CONTROL_RADIUS, CONTROL_RADIUS)

        icon_rect = QRect(rect.left() + 12, rect.center().y() - 8, 16, 16)
        icons_draw(painter, icon_rect, str(index.data(NAV_GLYPH_ROLE)), primary)

        if not self.pane.collapsed:
            painter.setFont(theme_font("body_strong" if selected else "body"))
            painter.setPen(primary)
            label_rect = rect.adjusted(40, 0, -52, 0)
            label = painter.fontMetrics().elidedText(
                str(index.data(NAV_LABEL_ROLE)), Qt.TextElideMode.ElideRight, label_rect.width()
            )
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setFont(theme_font("caption"))
            painter.setPen(secondary)
            painter.drawText(
                rect.adjusted(0, 0, -12, 0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                navigation_format_count(index.data(NAV_COUNT_ROLE)),
            )
        painter.restore()


class NavigationPane(QFrame):
    """Collapsible library/album navigation with live counts; GUI-thread-only."""

    navigation_selected = Signal(str)
    navigation_settings = Signal()
    navigation_album_action = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty pane whose counts are unknown until the shell pushes them."""
        super().__init__(parent)
        self.setObjectName("NavPane")
        self.collapsed = False
        self.counts: dict[str, int] = {}
        self.albums: tuple[tuple[int, str, int], ...] = ()
        self.current_key = LIBRARY_VIEWS[0].key
        self.setFixedWidth(NAV_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        self.toggle_button = QPushButton(self)
        self.toggle_button.setObjectName("Command")
        self.toggle_button.setFixedSize(40, 36)
        self.toggle_button.setToolTip("Collapse navigation")
        self.toggle_button.clicked.connect(self.navigation_toggle)
        layout.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("NavList")
        self.list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self.list_widget.setMouseTracking(True)
        self.list_widget.setUniformItemSizes(False)
        self.list_widget.setItemDelegate(NavigationRowDelegate(self))
        self.list_widget.currentItemChanged.connect(self.navigation_current_changed)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.navigation_context_menu)
        layout.addWidget(self.list_widget, 1)

        self.settings_button = QPushButton("  Settings", self)
        self.settings_button.setObjectName("Command")
        self.settings_button.setFixedHeight(ROW_HEIGHT)
        self.settings_button.clicked.connect(self.navigation_settings.emit)
        layout.addWidget(self.settings_button)

        self.navigation_refresh_icons()
        self.navigation_populate()

    def navigation_refresh_icons(self) -> None:
        """Re-draw button icons in the current palette colour after a theme change."""
        color = self.palette().color(self.palette().ColorRole.WindowText)
        self.toggle_button.setIcon(icons_get("hamburger", color))
        self.settings_button.setIcon(icons_get("settings", color))

    def changeEvent(self, event: QEvent) -> None:
        """Follow live theme changes, since icons are drawn rather than loaded."""
        super().changeEvent(event)
        if event.type() == event.Type.PaletteChange:
            self.navigation_refresh_icons()

    def navigation_set_counts(self, counts: dict[str, int]) -> None:
        """Replace the library counts shown at the trailing edge of each row.

        counts: a mapping of ``app_service_stats`` keys to values; unknown keys
            are ignored and missing keys simply render no count.
        Returns None.
        """
        if not isinstance(counts, dict):
            raise TypeError("Navigation counts must be a mapping")
        self.counts = {key: int(value) for key, value in counts.items() if isinstance(value, int)}
        self.navigation_populate()

    def navigation_set_albums(self, albums: Sequence[tuple[int, str, int]]) -> None:
        """Replace the album rows.

        albums: ``(album_id, name, asset_count)`` triples in display order.
        Returns None.
        """
        rows: list[tuple[int, str, int]] = []
        for album_id, name, count in albums:
            navigation_album_key(album_id)
            rows.append((album_id, str(name), int(count)))
        self.albums = tuple(rows)
        self.navigation_populate()

    def navigation_populate(self) -> None:
        """Rebuild every row, preserving the selected key across refreshes."""
        wanted = self.current_key
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.navigation_add_header("Library")
        for view in LIBRARY_VIEWS:
            self.navigation_add_row(
                view.key, view.label, view.glyph, self.counts.get(view.count_key)
            )
        if self.albums:
            self.navigation_add_header("Albums")
            for album_id, name, count in self.albums:
                self.navigation_add_row(navigation_album_key(album_id), name, "album", count)
        self.list_widget.blockSignals(False)
        if not self.navigation_select(wanted):
            # The selected album disappeared, so this really is a view change
            # and listeners must follow it or the page stack would diverge.
            self.navigation_select(LIBRARY_VIEWS[0].key)
            self.navigation_selected.emit(self.current_key)

    def navigation_add_header(self, text: str) -> None:
        """Append a non-selectable section header row.

        text: the section caption.
        Returns None.
        """
        item = QListWidgetItem(text)
        item.setData(NAV_HEADER_ROLE, True)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list_widget.addItem(item)

    def navigation_add_row(self, key: str, label: str, glyph: str, count: int | None) -> None:
        """Append one selectable navigation row.

        key: the navigation key emitted on selection.
        label: the visible caption.
        glyph: an icon name.
        count: the trailing count, or None when it is not known yet.
        Returns None.
        """
        item = QListWidgetItem(label)
        item.setData(NAV_KEY_ROLE, key)
        item.setData(NAV_LABEL_ROLE, label)
        item.setData(NAV_GLYPH_ROLE, glyph)
        item.setData(NAV_COUNT_ROLE, count)
        item.setData(NAV_HEADER_ROLE, False)
        if self.collapsed:
            item.setToolTip(label)
        self.list_widget.addItem(item)

    def navigation_select(self, key: str) -> bool:
        """Select a row by key programmatically, without reporting a user navigation.

        key: the navigation key to select.
        Returns True when a matching row exists. The signal is deliberately not
        emitted: callers that move the selection themselves already know where
        they are going, and re-entering their own handler would reset the page.
        """
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item is not None and item.data(NAV_KEY_ROLE) == key:
                self.current_key = key
                self.list_widget.blockSignals(True)
                self.list_widget.setCurrentItem(item)
                self.list_widget.blockSignals(False)
                return True
        return False

    def navigation_current_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        """Emit the selected key when the user moves to another row."""
        if current is None:
            return
        key = current.data(NAV_KEY_ROLE)
        if not isinstance(key, str) or key == self.current_key:
            return
        self.current_key = key
        self.navigation_selected.emit(key)

    def navigation_context_menu(self, position: QPoint) -> None:
        """Offer the album-wide verbs for the row under the cursor.

        position: the click position in the list widget's viewport.
        Returns None. Only album rows have album-wide verbs; the library views
        are not catalog objects, so a right-click on them offers nothing.
        """
        item = self.list_widget.itemAt(position)
        if item is None:
            return
        key = item.data(NAV_KEY_ROLE)
        album_id = navigation_album_id(key) if isinstance(key, str) else None
        if album_id is None:
            return
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        for action_key, label in ALBUM_ACTIONS:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, chosen=action_key: self.navigation_album_action.emit(
                    album_id, chosen
                )
            )
        menu.popup(self.list_widget.viewport().mapToGlobal(position))

    def navigation_toggle(self) -> None:
        """Collapse the pane to an icon rail, or expand it again."""
        self.collapsed = not self.collapsed
        self.setFixedWidth(RAIL_WIDTH if self.collapsed else NAV_WIDTH)
        self.settings_button.setText("" if self.collapsed else "  Settings")
        self.toggle_button.setToolTip(
            "Expand navigation" if self.collapsed else "Collapse navigation"
        )
        self.navigation_populate()

    def navigation_apply_width(self, available_width: int) -> None:
        """Auto-collapse on narrow windows, as the sketch requires.

        available_width: the window width in pixels.
        Returns None.
        """
        should_collapse = available_width < 900
        if should_collapse != self.collapsed:
            self.navigation_toggle()
