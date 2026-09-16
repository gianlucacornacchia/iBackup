"""Where each service capability is reachable in the GUI.

The CLI and the GUI are two adapters over the same ``AppService``. Nothing stops
a new service method from being wired into the CLI and quietly forgotten in the
GUI, which is how a desktop app ends up with capabilities its users cannot
reach. This module is the declaration that closes that gap: every service
operation names the surface that runs it, and ``tests/test_gui_parity.py``
fails when an operation exists with no entry here, when an entry names an
operation the service does not have, or when a declared surface turns out not to
submit its operation at runtime.

The descriptions are deliberately written the way the user would find the verb,
not the way the code is organised, because that is what the parity map in
``docs/ui-sketch/README.md`` §8 promises.
"""

from __future__ import annotations

from .commands import COMMANDS
from .settings_dialog import SETTINGS_OPERATIONS
from .shell import REVIEW_VIEWS

# Not capabilities: these guard the worker's thread affinity and the "an archive
# must be open" rule, and every other operation goes through them.
INTERNAL_OPERATIONS = frozenset({"app_service_check_thread", "app_service_require"})

# Session lifecycle. The command bar names these with its own keys
# (``create_archive`` and friends) because the window, not the worker, owns the
# transition, but they are still the service calls behind the verbs.
LIFECYCLE_SURFACES = {
    "app_service_initialize": 'Command bar overflow: "New archive"',
    "app_service_open": 'Command bar: "Open archive"',
    "app_service_close": 'Command bar overflow: "Close archive"',
}

# Surfaces whose operation is chosen inside a handler rather than declared in a
# table the code already exports. The test proves each of these really is
# submitted, so this stays a description rather than a promise.
ACTION_SURFACES = {
    "app_service_list_assets": "Centre grid: All photos and album views",
    "app_service_list_unsorted": "Left navigation: Unsorted",
    "app_service_list_recycled": "Left navigation: Recycle bin",
    "app_service_list_albums": "Left navigation: ALBUMS section",
    "app_service_mark": 'Album right-click: "Mark album for delete"; single-copy mark scope prompt',
    "app_service_mark_many": 'Selection bar and viewer: "Mark"',
    "app_service_unmark": 'Marked view: "Unmark"',
    "app_service_clear_marks": 'Marked view: "Clear all marks"',
    "app_service_commit_marks": 'Marked view: "Recycle marked" / "Delete permanently"',
    "app_service_move_selection": 'Selection bar and viewer: "Move to album..."',
    "app_service_move_to_deleted": 'Selection bar, viewer and phone report: "Delete..."',
    "app_service_restore": 'Recycle bin and viewer: "Restore"',
    "app_service_purge": 'Selection bar, viewer and phone report: "Purge..."',
    "app_service_settings_path": 'Settings: "Show settings file"',
}

# Capabilities the GUI covers by another route than calling the method. Each one
# needs a reason: this is the only place an operation may have no button, so an
# unexplained entry here is exactly the gap the parity test exists to catch.
INDIRECT_SURFACES = {
    "app_service_set_setting": (
        'Settings dialog "Save", which writes every edited preference in one '
        "app_service_update_settings call rather than one round trip per field"
    ),
    "app_service_thumbnail": (
        "Grid tiles and the viewer, which render previews through the GUI's own "
        "preview pool so scrolling never queues work behind an archive operation"
    ),
}

# Every CLI command, and where the same capability lives in the GUI. Keyed by the
# command path as Typer spells it, so a new command fails the parity test until
# it is either given a surface or explained here.
CLI_SURFACES = {
    "init": 'Command bar overflow: "New archive"',
    "device-info": 'Command bar overflow: "Check phone"',
    "import": 'Command bar: "Import"',
    "verify": 'Command bar: "Verify"',
    "dedup": 'Command bar overflow: "Duplicate report"',
    "albums": "Left navigation: ALBUMS section",
    "list": "Centre grid, with Unsorted and Recycle bin in the left navigation",
    "stats": "Status bar counters, refreshed from the command bar overflow",
    "scan-phone": 'Command bar: "Scan phone"',
    "reclaim": 'Command bar: "Free up space"',
    "move": 'Selection bar and viewer: "Move to album..."',
    "thumbnail": "Grid tiles and the viewer render previews on demand",
    "clear-thumbnails": 'Settings ▸ Maintenance: "Clear cache"',
    "deleted-on-phone list": "Left navigation: Deleted from phone",
    "deleted-on-phone to-deleted": 'Deleted from phone: "Move to Deleted"',
    "deleted-on-phone restore": 'Recycle bin and viewer: "Restore"',
    "deleted-on-phone purge": 'Deleted from phone and the selection bar: "Purge..."',
    "marks add": 'Selection bar "Mark", the scope prompt, and the album right-click',
    "marks list": "Left navigation: Marked",
    "marks remove": 'Marked view: "Unmark"',
    "marks clear": 'Marked view: "Clear all marks"',
    "marks commit": 'Marked view: "Recycle marked" / "Delete permanently"',
    "config list": "Settings dialog",
    "config get": "Settings dialog",
    "config set": 'Settings dialog "Save"',
    "config reset": 'Settings ▸ Advanced: "Reset settings"',
    "config path": 'Settings ▸ Advanced: "Show settings file"',
    "config forget": 'Settings ▸ Advanced: "Forget" on a recent archive',
}


def parity_command_surfaces() -> dict[str, str]:
    """Collect the surfaces the command bar declares for itself.

    Returns a mapping of service operation to the command that runs it. The
    command bar's own table is the source, so a renamed or removed command
    changes this map instead of leaving a stale description behind.
    """
    surfaces: dict[str, str] = {}
    for command in COMMANDS:
        if command.operation.startswith("app_service_"):
            where = "Command bar overflow" if command.overflow else "Command bar"
            surfaces[command.operation] = f'{where}: "{command.label}"'
    return surfaces


def parity_gui_surfaces() -> dict[str, str]:
    """Build the full operation-to-surface map the GUI claims to offer.

    Returns a mapping of service operation to a human-readable location. The
    generated halves (command bar, settings dialog, review views) are read from
    the same tables the widgets use, so only genuinely code-driven verbs need a
    written description.
    """
    surfaces: dict[str, str] = dict(LIFECYCLE_SURFACES)
    surfaces.update(ACTION_SURFACES)
    surfaces.update(parity_command_surfaces())
    for operation in SETTINGS_OPERATIONS:
        surfaces.setdefault(operation, "Settings dialog")
    for view, operation in REVIEW_VIEWS.items():
        surfaces.setdefault(operation, f"Left navigation: {view} report")
    return surfaces


def parity_uncovered_operations(operations: frozenset[str] | set[str]) -> list[str]:
    """Report the service operations no GUI surface reaches.

    operations: every public service operation name.
    Returns the uncovered names in sorted order. Internal guards are excluded,
    and an operation covered by a documented indirect route counts as reachable
    because a user can still get the effect without the CLI.
    """
    covered = set(parity_gui_surfaces()) | set(INDIRECT_SURFACES) | INTERNAL_OPERATIONS
    return sorted(operation for operation in operations if operation not in covered)
