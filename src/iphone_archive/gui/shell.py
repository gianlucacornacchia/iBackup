"""Application shell: navigation, pages, command bar and live counters.

This is the frame the sketch describes: a navigation pane on the left, a page
header, the command bar that replaces the menu bar, and a page stack. It owns no
archive data - every number it shows comes from the service worker, and every
command it offers names a service operation, so the GUI cannot drift away from
the CLI's capabilities.

Counts are refreshed on demand rather than polled. Album rows are pumped out of
the existing paged album model instead of a second query, so the shell inherits
its mutation barriers: after an import or a purge, the counts are re-read rather
than being left stale.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .commands import CommandBar, PhoneState
from .gallery import AssetGallery
from .models import MODEL_MUTATIONS, ArchiveModels, AssetScope, AssetSelection
from .navigation import LIBRARY_VIEWS, NavigationPane, navigation_album_id
from .previews import PreviewLoader
from .theme import GROUP_GAP, PAGE_MARGIN, theme_font
from .worker import WorkerController, WorkerFailure, WorkerResult

LOGGER = logging.getLogger(__name__)
ScopeKind = Literal["all", "album", "unsorted", "recycled"]
HOUSEKEEPING_HISTORY = 64

# Views backed by the paged asset model; the rest get their own listings in the
# destructive-operations and marks steps.
VIEW_SCOPES: dict[str, ScopeKind] = {
    "all": "all",
    "unsorted": "unsorted",
    "recycled": "recycled",
}
DEVICE_OPERATIONS = frozenset(
    {
        "app_service_device_info",
        "app_service_import",
        "app_service_scan_phone",
        "app_service_reclaim",
    }
)
# Only the dedicated probe may report the phone as absent. An import can fail
# for archive-side reasons - a full disk, a hash mismatch - and latching
# "disconnected" on those would disable the phone commands for no reason.
PHONE_PROBE_OPERATION = "app_service_device_info"

# Which batch actions each view offers. The recycle bin is the only place where
# restoring or permanently purging makes sense, and recycling something that is
# already recycled does not.
VIEW_ACTIONS: dict[str, tuple[str, ...]] = {
    "all": ("open", "move", "mark", "delete"),
    "unsorted": ("open", "move", "mark", "delete"),
    "recycled": ("open", "restore", "purge"),
    "album": ("open", "move", "mark", "delete"),
}


class ShellPage(QWidget):
    """One content page: a Settings-style header above a body placeholder."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Build a page whose body is filled in by later steps.

        title: the page heading.
        parent: optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ShellPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GROUP_GAP)
        self.title_label = QLabel(title, self)
        self.title_label.setFont(theme_font("title"))
        self.subtitle_label = QLabel("", self)
        self.subtitle_label.setFont(theme_font("caption"))
        self.subtitle_label.setProperty("role", "secondary")
        self.body_label = QLabel("No archive open.", self)
        self.body_label.setObjectName("PlaceholderLabel")
        self.body_label.setProperty("role", "secondary")
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.body_label, 1)
        self.body_layout = layout
        self.body_widget: QWidget | None = None

    def shell_page_take_body(self, widget: QWidget | None) -> None:
        """Host the shared gallery, or fall back to this page's placeholder text.

        widget: the widget to show, or None to show the placeholder again.
        Returns None. There is a single asset model, so there is a single
        gallery; it moves between pages rather than being duplicated per view.
        """
        if self.body_widget is not None and self.body_widget is not widget:
            self.body_layout.removeWidget(self.body_widget)
            self.body_widget.setParent(None)
        self.body_widget = widget
        if widget is None:
            self.body_label.setVisible(True)
            return
        self.body_label.setVisible(False)
        if widget.parent() is not self:
            widget.setParent(self)
            self.body_layout.addWidget(widget, 1)
        widget.setVisible(True)

    def shell_page_set_header(self, title: str, subtitle: str) -> None:
        """Update the page heading and its caption.

        title: the page heading.
        subtitle: the dimmed caption under it.
        Returns None.
        """
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def shell_page_set_body(self, message: str) -> None:
        """Replace the placeholder text shown until a real view exists.

        message: the text to display.
        Returns None.
        """
        self.body_label.setText(message)


class ArchiveShell(QWidget):
    """Navigation, pages and commands bound to one worker and its models."""

    shell_status_changed = Signal(str)
    shell_command = Signal(str)
    shell_selection_action = Signal(str, object)
    shell_open_asset = Signal(int)

    def __init__(
        self,
        worker: WorkerController,
        models: ArchiveModels,
        previews: PreviewLoader,
        parent: QWidget | None = None,
    ) -> None:
        """Compose the shell; no query runs until an archive is opened.

        worker: the GUI-affine service worker controller.
        models: the shared asset/album models.
        previews: the GUI-affine preview loader the tiles render through.
        parent: optional parent widget.
        """
        super().__init__(parent)
        worker.worker_check_thread()
        self.worker = worker
        self.models = models
        self.phone: PhoneState = "unknown"
        self.counts: dict[str, int] = {}
        self.requests: dict[int, str] = {}
        # Housekeeping IDs are remembered separately from `requests`, which is
        # consumed while routing a reply: whether the window has already seen
        # that reply depends on signal connection order, and the status bar must
        # not depend on it.
        self.housekeeping: OrderedDict[int, None] = OrderedDict()
        self.pages: dict[str, ShellPage] = {}

        self.navigation = NavigationPane(self)
        self.navigation.navigation_selected.connect(self.shell_view_selected)
        self.navigation.navigation_settings.connect(lambda: self.shell_command.emit("settings"))
        self.command_bar = CommandBar(self)
        self.command_bar.command_triggered.connect(self.shell_command.emit)
        # One model means one gallery; it is re-hosted by the page being shown
        # rather than being duplicated per view.
        self.gallery = AssetGallery(models.assets, previews, self)
        self.gallery.gallery_action.connect(self.shell_gallery_action)
        self.gallery.gallery_status.connect(self.shell_status_changed.emit)
        self.gallery.gallery_open_requested.connect(self.shell_open_asset.emit)
        self.stack = QStackedWidget(self)
        self.stack.setObjectName("ContentLayer")

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_layout.setSpacing(GROUP_GAP)
        content_layout.addWidget(self.command_bar)
        content_layout.addWidget(self.stack, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.navigation)
        layout.addWidget(content, 1)

        for view in LIBRARY_VIEWS:
            self.shell_page(view.key, view.label)
        self.stack.setCurrentWidget(self.pages[LIBRARY_VIEWS[0].key])

        worker.result_ready.connect(self.shell_reply)
        worker.failed.connect(self.shell_reply)
        # A cancelled import has already committed the assets it copied, so the
        # counters are just as stale as after a completed one.
        worker.cancelled.connect(self.shell_reply)
        worker.stopped.connect(self.shell_worker_stopped)
        self.models.albums.page_loaded.connect(self.shell_albums_page)
        self.models.albums.error_changed.connect(self.shell_albums_error)
        self.shell_apply_state()

    @property
    def archive_open(self) -> bool:
        """Return whether an archive session is currently open."""
        return self.worker.archive_root is not None and self.worker.state == "running"

    def shell_page(self, key: str, title: str) -> ShellPage:
        """Return the page for a navigation key, creating it on first use.

        key: the navigation key.
        title: the page heading.
        Returns the page widget.
        """
        page = self.pages.get(key)
        if page is None:
            page = ShellPage(title, self)
            self.pages[key] = page
            self.stack.addWidget(page)
        return page

    def shell_show_view(self, key: str) -> None:
        """Move to a view programmatically, keeping pane, page and scope in step.

        key: the navigation key to display.
        Returns None.
        """
        self.navigation.navigation_select(key)
        self.shell_view_selected(key)

    def shell_view_selected(self, key: str) -> None:
        """Show the page for a navigation key and point the asset model at it.

        key: the selected navigation key.
        Returns None.
        """
        self.worker.worker_check_thread()
        album_id = navigation_album_id(key)
        label = key
        if album_id is not None:
            label = next(
                (name for identifier, name, _ in self.navigation.albums if identifier == album_id),
                key,
            )
        else:
            label = next((view.label for view in LIBRARY_VIEWS if view.key == key), key)
        page = self.shell_page(key, label)
        self.stack.setCurrentWidget(page)
        if album_id is not None:
            self.models.assets.asset_model_set_scope(AssetScope("album", album_id))
        elif key in VIEW_SCOPES:
            self.models.assets.asset_model_set_scope(AssetScope(VIEW_SCOPES[key]))
        self.shell_apply_state()

    def shell_apply_state(self) -> None:
        """Re-apply command availability, page headers, the gallery host and status."""
        self.worker.worker_check_thread()
        self.command_bar.commands_set_state(self.archive_open, self.phone)
        key = self.navigation.current_key
        page = self.pages.get(key)
        if page is not None and self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
        if page is not None:
            page.shell_page_set_header(page.title_label.text(), self.shell_subtitle(key))
            actions = self.shell_view_actions(key)
            if actions is None:
                page.shell_page_take_body(None)
                page.shell_page_set_body(
                    "No archive open."
                    if not self.archive_open
                    else "This view gets its own listing in a later step."
                )
            else:
                for other in self.pages.values():
                    if other is not page and other.body_widget is self.gallery:
                        other.shell_page_take_body(None)
                page.shell_page_take_body(self.gallery)
                self.gallery.gallery_set_actions(actions)
        self.shell_status_changed.emit(self.shell_status_text())

    def shell_view_actions(self, key: str) -> tuple[str, ...] | None:
        """Return the batch actions a view offers, or None when it has no gallery.

        key: the navigation key being displayed.
        Returns the action keys, or None for views not backed by the asset model.
        """
        if navigation_album_id(key) is not None:
            return VIEW_ACTIONS["album"]
        scope = VIEW_SCOPES.get(key)
        return None if scope is None else VIEW_ACTIONS[scope]

    def shell_gallery_action(self, key: str) -> None:
        """Forward a batch action together with the exact copies it applies to.

        key: the action key the gallery requested.
        Returns None. The selection is captured here, on the GUI thread and
        immediately, so it still refers to the rows the user actually saw.
        """
        self.worker.worker_check_thread()
        try:
            selection: AssetSelection | None = self.gallery.grid.grid_selection()
        except ValueError as error:
            self.shell_status_changed.emit(f"Selection is no longer valid: {error}")
            return
        self.shell_selection_action.emit(key, selection)

    def shell_subtitle(self, key: str) -> str:
        """Build a page caption from the latest counts.

        key: the navigation key being displayed.
        Returns the caption text, empty when no count is known.
        """
        album_id = navigation_album_id(key)
        if album_id is not None:
            count = next(
                (
                    value
                    for identifier, _, value in self.navigation.albums
                    if identifier == album_id
                ),
                None,
            )
        else:
            count_key = next(
                (view.count_key for view in LIBRARY_VIEWS if view.key == key), "assets"
            )
            count = self.counts.get(count_key)
        if count is None:
            return ""
        return f"{count} item" if count == 1 else f"{count} items"

    def shell_status_text(self) -> str:
        """Compose the status-bar line from the phone state and archive counters.

        Returns the status text.
        """
        phone_text = {
            "connected": "iPhone connected",
            "disconnected": "No iPhone detected",
            "unknown": "iPhone not checked",
        }[self.phone]
        if not self.archive_open:
            return f"{phone_text} - no archive open"
        parts = [phone_text, str(self.worker.archive_root)]
        if self.counts:
            parts.append(f"{self.counts.get('assets', 0)} assets")
            parts.append(f"{self.counts.get('albums', 0)} albums")
            parts.append(f"{self.counts.get('deleted_on_phone', 0)} gone from phone")
        return " - ".join(parts)

    def shell_refresh(self) -> None:
        """Re-read the counters and album rows for the open archive.

        Returns None. Does nothing while no archive is open or while the models
        are held back by an accepted mutation.
        """
        self.worker.worker_check_thread()
        if not self.archive_open or self.models.barriers:
            return
        self.shell_track(self.worker.worker_submit("app_service_stats"), "stats")
        self.shell_track(self.worker.worker_submit("app_service_list_marks"), "marks")
        self.shell_pump_albums()

    def shell_track(self, request_id: int, kind: str) -> None:
        """Remember one of the shell's own reads.

        request_id: the accepted worker request.
        kind: which read it is, for reply routing.
        Returns None.
        """
        self.requests[request_id] = kind
        self.housekeeping[request_id] = None
        while len(self.housekeeping) > HOUSEKEEPING_HISTORY:
            self.housekeeping.popitem(last=False)

    def shell_is_housekeeping(self, request_id: int) -> bool:
        """Report whether a request was the shell's own counter or album read.

        request_id: the worker request being answered.
        Returns True for reads the shell issued itself. The window uses this so
        an automatic refresh cannot erase the error of the operation that
        triggered it.
        """
        return request_id in self.housekeeping

    def shell_pump_albums(self) -> None:
        """Fetch one more album page so the navigation pane can list them all.

        Returns None. Albums number in the tens, so the pane lists every album,
        but the pages still come from the bounded model rather than one
        unbounded query.
        """
        albums = self.models.albums
        if albums.canFetchMore():
            albums.fetchMore()
            if albums.pending_request is not None:
                self.shell_track(albums.pending_request, "albums")
        else:
            self.navigation.navigation_set_albums(
                [(row.album_id, row.name, row.asset_count) for row in albums.rows]
            )
            self.shell_apply_state()

    def shell_albums_page(self, count: int) -> None:
        """Continue pumping album pages as each one arrives.

        count: how many rows the page added.
        Returns None.
        """
        self.shell_pump_albums()

    def shell_albums_error(self, message: object) -> None:
        """Report a failed album page instead of leaving the pane silently empty.

        message: the model's error text, or None when it was cleared.
        Returns None.
        """
        if isinstance(message, str):
            self.shell_status_changed.emit(f"Albums could not be listed: {message}")

    def shell_reply(self, reply: WorkerResult | WorkerFailure) -> None:
        """Absorb worker replies: phone state, counters and archive lifecycle.

        reply: a worker result or failure.
        Returns None.
        """
        self.worker.worker_check_thread()
        if reply.operation in DEVICE_OPERATIONS:
            if isinstance(reply, WorkerResult) and not reply.cancelled:
                self.phone = "connected"
            elif isinstance(reply, WorkerFailure) and reply.operation == PHONE_PROBE_OPERATION:
                self.phone = "disconnected"
        tracked = self.requests.pop(reply.request_id, None)
        if tracked == "stats" and isinstance(reply, WorkerResult):
            value = reply.value
            if isinstance(value, dict):
                self.counts.update({str(key): int(number) for key, number in value.items()})
                self.navigation.navigation_set_counts(self.counts)
        elif tracked == "marks" and isinstance(reply, WorkerResult):
            marks = reply.value
            if isinstance(marks, list):
                self.counts["marked"] = len(marks)
                self.navigation.navigation_set_counts(self.counts)
        if reply.operation in {"open_archive", "create_archive"}:
            self.shell_archive_changed(isinstance(reply, WorkerResult))
        elif reply.operation == "close_archive":
            self.shell_archive_changed(False)
        elif reply.operation in MODEL_MUTATIONS or getattr(reply, "cancelled", False):
            # An import or a purge changes what the counters and album rows mean,
            # so they are re-read once the models' barriers have cleared.
            self.shell_refresh()
        self.shell_apply_state()

    def shell_archive_changed(self, opened: bool) -> None:
        """Reset shell state for a newly opened or closed archive.

        opened: whether an archive is now open.
        Returns None.
        """
        self.counts.clear()
        self.navigation.navigation_set_counts({})
        self.navigation.navigation_set_albums([])
        self.requests.clear()
        self.gallery.grid.grid_clear_selection()
        self.shell_show_view(LIBRARY_VIEWS[0].key)
        if opened:
            self.shell_refresh()

    def shell_worker_stopped(self) -> None:
        """Fall back to the closed-archive presentation after worker shutdown."""
        self.worker.worker_check_thread()
        self.shell_archive_changed(False)
        self.shell_apply_state()

    def shell_archive_label(self) -> str:
        """Return the open archive's display name, or a placeholder.

        Returns the archive folder name, or "No archive" when none is open.
        """
        root = self.worker.archive_root
        return Path(root).name if root is not None else "No archive"

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Auto-collapse the navigation pane on narrow windows."""
        super().resizeEvent(event)
        self.navigation.navigation_apply_width(self.width())
