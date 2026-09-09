"""Command-line interface.

Thin adapter over ``AppService``: it parses arguments, prints results, and sets
exit codes. All behaviour lives in the service layer, which is what keeps the
CLI and the GUI at exact feature parity. Destructive commands are dry-run or
confirmation-gated by default.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperGroup

from .device.afc_device import AfcDevice
from .device.fake_device import FakeDevice
from .device.interface import DeviceError, MediaSource
from .logging_setup import logging_setup_close, logging_setup_configure, logging_setup_get_logger
from .service.app_service import AppService, ArchiveNotFoundError
from .service.marks import TARGET_ALBUM, TARGET_ASSET
from .service.progress import ProgressEvent, ProgressHandle
from .settings import (
    SettingsError,
    settings_field_names,
    settings_load,
)

ARCHIVE_ENV_VAR = "IBACKUP_ARCHIVE"
FAKE_DEVICE_ENV_VAR = "IBACKUP_FAKE_DEVICE"

EXIT_OK = 0
EXIT_FAILURE = 1
COMMAND_CONTEXT: ContextVar[typer.Context | None] = ContextVar("command_context", default=None)


class CliGroup(TyperGroup):
    """Surface operational failures without hiding their cause or returning success."""

    def invoke(self, ctx: Any) -> Any:
        """Translate errors for Typer's version-dependent Click context/result types."""
        try:
            result = super().invoke(ctx)
            logging_setup_get_logger("cli").info("Command completed")
            return result
        except (DeviceError, OSError, sqlite3.Error, ValueError) as error:
            logging_setup_get_logger("cli").error("Command failed: %s", error)
            cli_fail(str(error))
        except typer.Exit as error:
            logging_setup_get_logger("cli").info("Command exited with status %s", error.exit_code)
            raise
        finally:
            logging_setup_close()


app = typer.Typer(
    cls=CliGroup,
    help="iPhone Archive - permanent, append-only backups of iPhone photos and videos.",
    no_args_is_help=True,
    add_completion=False,
)
deleted_app = typer.Typer(help="Review archived assets that no longer exist on the phone.")
marks_app = typer.Typer(help="Stage, review, and commit mark-for-delete requests.")
config_app = typer.Typer(help="Read and change persisted user preferences.")
app.add_typer(deleted_app, name="deleted-on-phone")
app.add_typer(marks_app, name="marks")
app.add_typer(config_app, name="config")

ArchiveOption = typer.Option(None, "--archive", "-a", help="Archive root folder.")


@app.callback()
def cli_context(context: typer.Context) -> None:
    """Own command resources until the root CLI invocation finishes."""
    token = COMMAND_CONTEXT.set(context)
    context.call_on_close(lambda: COMMAND_CONTEXT.reset(token))


def cli_confirm_delete(description: str) -> None:
    """Require explicit typed consent before a permanent archive or phone deletion."""
    typer.echo(description)
    if typer.prompt("Type DELETE to confirm", default="", show_default=False) != "DELETE":
        cli_fail("Deletion cancelled: confirmation did not match DELETE.")


def cli_register_service(service: AppService) -> None:
    """Close a command's catalog even when its operation fails or is cancelled."""
    context = COMMAND_CONTEXT.get()
    if context is not None:
        context.call_on_close(service.app_service_close)


def cli_resolve_archive(archive: Path | None) -> Path:
    """Resolve the archive root from the option, environment, or cwd.

    archive: the explicit ``--archive`` value, or None.
    Returns the archive root to operate on.
    """
    if archive is not None:
        return archive
    from_env = os.environ.get(ARCHIVE_ENV_VAR)
    if from_env:
        return Path(from_env)
    configured = settings_load().default_archive
    return Path(configured) if configured else Path.cwd()


def cli_open_service(archive: Path | None) -> AppService:
    """Open the archive, exiting with a clear message when it is missing.

    archive: the explicit ``--archive`` value, or None.
    Returns an opened ``AppService``.
    """
    service = AppService(cli_resolve_archive(archive))
    cli_register_service(service)
    try:
        service.app_service_open()
    except ArchiveNotFoundError as error:
        cli_fail(f"{error}\nRun 'ibackup init <folder>' first.")
    _, paths = service.app_service_require()
    logging_setup_configure(paths.logs_dir, level=settings_load().log_level)
    context = COMMAND_CONTEXT.get()
    logging_setup_get_logger("cli").info(
        "Command %s opened archive %s",
        context.invoked_subcommand if context is not None else "service",
        service.archive_root,
    )
    return service


def cli_fail(message: str) -> None:
    """Print an error and terminate with a failure exit code.

    message: the error text shown to the user.
    Returns None; always raises ``typer.Exit``.
    """
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(EXIT_FAILURE)


def cli_build_source(udid: str | None = None) -> MediaSource:
    """Build the media source for phone operations.

    udid: optional device identifier to target a specific phone.
    Returns a ``MediaSource``. When ``IBACKUP_FAKE_DEVICE`` points at a folder,
    an offline fake device backed by that folder is used instead of USB.
    """
    fake_dir = os.environ.get(FAKE_DEVICE_ENV_VAR)
    if fake_dir:
        return cli_fake_source(Path(fake_dir))
    device = AfcDevice(udid=udid)
    try:
        device.afc_device_connect()
    except DeviceError as error:
        cli_fail(str(error))
    context = COMMAND_CONTEXT.get()
    if context is not None:
        context.call_on_close(device.device_close)
    return device


def cli_fake_source(folder: Path) -> FakeDevice:
    """Build an offline media source from a folder of files.

    folder: a directory whose files stand in for the phone's media.
    Returns a ``FakeDevice`` holding that folder's contents.
    """
    items: dict[str, bytes] = {}
    for entry in sorted(folder.rglob("*")):
        if entry.is_file():
            items["/DCIM/" + entry.relative_to(folder).as_posix()] = entry.read_bytes()
    return FakeDevice(items)


def cli_progress(verbose: bool) -> ProgressHandle:
    """Build a progress handle that optionally echoes each step.

    verbose: print per-item progress when True.
    Returns the configured ``ProgressHandle``.
    """

    def echo_event(event: ProgressEvent) -> None:
        """Print a single progress event."""
        typer.echo(f"  {event.operation} {event.current}/{event.total} {event.message}")

    return ProgressHandle(echo_event if verbose else None)


@app.command("init")
def cli_init(
    archive_root: Path = typer.Argument(..., help="Folder to initialize as an archive."),
) -> None:
    """Create the archive folder structure and catalog."""
    service = AppService(archive_root)
    cli_register_service(service)
    paths = service.app_service_initialize()
    logging_setup_configure(paths.logs_dir, level=settings_load().log_level)
    logging_setup_get_logger("cli").info("Initialized archive at %s", paths.root)
    service.app_service_close()
    typer.echo(f"Initialized archive at {paths.root}")


@app.command("device-info")
def cli_device_info(
    device_udid: str | None = typer.Option(None, "--device", help="Select this device UDID."),
) -> None:
    """Show the connected iPhone and how many media items it holds."""
    source = cli_build_source(device_udid)
    info = AppService(Path.cwd()).app_service_device_info(source)
    typer.echo(f"Device: {info.udid}")
    typer.echo(f"Media items: {info.media_count}")


@app.command("import")
def cli_import(
    archive: Path = ArchiveOption,
    link_mode: str | None = typer.Option(
        None, "--album-link-mode", help="How extra album copies are stored."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print per-item progress."),
    device_udid: str | None = typer.Option(None, "--device", help="Select this device UDID."),
) -> None:
    """Import new photos and videos from the phone (incremental, append-only)."""
    service = cli_open_service(archive)
    source = cli_build_source(device_udid)
    result = service.app_service_import(source, cli_progress(verbose), link_mode)
    typer.echo(
        f"Added {result.added_count}, skipped {result.skipped_count}, "
        f"duplicates {result.duplicate_count}, errors {result.error_count}"
    )
    if result.error_count:
        for error in result.errors:
            typer.echo(error, err=True)
        raise typer.Exit(EXIT_FAILURE)


@app.command("verify")
def cli_verify(
    archive: Path = ArchiveOption,
    limit: int | None = typer.Option(None, "--limit", help="Verify at most this many files."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print per-file progress."),
) -> None:
    """Re-hash archived files and report any corruption or missing copies."""
    service = cli_open_service(archive)
    result = service.app_service_verify(cli_progress(verbose), limit)
    typer.echo(
        f"Checked {result.checked_count}, ok {result.ok_count}, "
        f"mismatched {result.mismatch_count}, missing {result.missing_count}"
    )
    if not result.passed:
        raise typer.Exit(EXIT_FAILURE)


@app.command("dedup")
def cli_dedup(archive: Path = ArchiveOption) -> None:
    """Report duplicate content and the storage cost of multi-album copies."""
    service = cli_open_service(archive)
    result = service.app_service_dedup_report()
    typer.echo(f"Unique assets: {result.asset_count}")
    typer.echo(f"Stored files: {result.file_count}")
    typer.echo(f"Assets in several albums: {len(result.multi_copy_groups)}")
    typer.echo(f"Extra bytes from album copies: {result.reclaimable_bytes}")


@app.command("albums")
def cli_albums(archive: Path = ArchiveOption) -> None:
    """List albums and how many assets each one holds."""
    service = cli_open_service(archive)
    summaries = service.app_service_list_albums()
    if not summaries:
        typer.echo("No albums yet.")
    for summary in summaries:
        typer.echo(f"{summary.album_id:>5}  {summary.asset_count:>6}  {summary.name}")


@app.command("list")
def cli_list(
    archive: Path = ArchiveOption,
    album_id: int | None = typer.Option(None, "--album", help="Restrict to one album id."),
    unsorted: bool = typer.Option(False, "--unsorted", help="Only assets in no album."),
    recycled: bool = typer.Option(False, "--recycled", help="Only assets in Deleted/."),
    limit: int | None = typer.Option(None, "--limit", help="Maximum rows to print."),
    show_files: bool = typer.Option(
        False, "--files", help="Show file ids for album-scoped deletion marks."
    ),
) -> None:
    """List archived assets."""
    service = cli_open_service(archive)
    if recycled:
        views = service.app_service_list_recycled()
    elif unsorted:
        views = service.app_service_list_unsorted()
    else:
        views = service.app_service_list_assets(album_id=album_id, limit=limit)
    for view in views:
        location = view.paths[0] if view.paths else "(no stored copy)"
        typer.echo(f"{view.asset_id:>6}  {view.sha256[:12]}  {view.size:>10}  {location}")
        if show_files:
            for file_id, path in zip(view.file_ids, view.paths, strict=True):
                typer.echo(f"  file {file_id}: {path}")
    typer.echo(f"{len(views)} asset(s)")


@app.command("stats")
def cli_stats(archive: Path = ArchiveOption) -> None:
    """Show headline archive counts."""
    service = cli_open_service(archive)
    for key, value in service.app_service_stats().items():
        typer.echo(f"{key:>26}: {value}")


@app.command("scan-phone")
def cli_scan_phone(
    archive: Path = ArchiveOption,
    device_udid: str | None = typer.Option(None, "--device", help="Select this device UDID."),
) -> None:
    """Refresh which archived assets are still present on the phone."""
    service = cli_open_service(archive)
    source = cli_build_source(device_udid)
    service.app_service_scan_phone(source)
    typer.echo(
        f"Deleted on phone: {service.app_service_deleted_on_phone(source.device_udid()).count}"
    )


@deleted_app.command("list")
def cli_deleted_list(
    archive: Path = ArchiveOption,
    rescan: bool = typer.Option(False, "--rescan", help="Scan the phone before listing."),
    device_udid: str | None = typer.Option(
        None, "--device", help="Restrict results (and optional rescan) to this device UDID."
    ),
) -> None:
    """List archived assets that no longer exist on the phone."""
    service = cli_open_service(archive)
    if rescan:
        service.app_service_scan_phone(cli_build_source(device_udid))
    result = service.app_service_deleted_on_phone(device_udid=device_udid)
    for item in result.items:
        typer.echo(f"{item.asset_id:>6}  {item.sha256[:12]}  {item.original_name}")
    typer.echo(f"{result.count} asset(s) deleted on phone, still safe in the archive")


@deleted_app.command("to-deleted")
def cli_deleted_to_deleted(
    asset_ids: list[int] = typer.Argument(..., help="Asset ids to move."),
    archive: Path = ArchiveOption,
    file_ids: list[int] | None = typer.Option(
        None, "--file", help="Restrict to file ids (repeatable)."
    ),
) -> None:
    """Move assets into the reversible Deleted/ recycle bin."""
    service = cli_open_service(archive)
    result = service.app_service_move_to_deleted(asset_ids, file_ids=file_ids)
    typer.echo(f"Moved {result.moved_count}, skipped {result.skipped_count}")


@deleted_app.command("restore")
def cli_deleted_restore(
    asset_ids: list[int] = typer.Argument(..., help="Asset ids to restore."),
    archive: Path = ArchiveOption,
    file_ids: list[int] | None = typer.Option(
        None, "--file", help="Restrict to file ids (repeatable)."
    ),
) -> None:
    """Restore assets from Deleted/ back into the browsable album tree."""
    service = cli_open_service(archive)
    result = service.app_service_restore(asset_ids, file_ids=file_ids)
    typer.echo(f"Restored {result.restored_count}, skipped {result.skipped_count}")


@deleted_app.command("purge")
def cli_deleted_purge(
    asset_ids: list[int] = typer.Argument(..., help="Asset ids to delete permanently."),
    archive: Path = ArchiveOption,
    confirm: bool = typer.Option(False, "--confirm", help="Required; without it nothing happens."),
    recycled_only: bool = typer.Option(
        False, "--recycled-only", help="Delete only Deleted copies, retaining active album copies."
    ),
    file_ids: list[int] | None = typer.Option(
        None, "--file", help="Restrict to file ids (repeatable)."
    ),
) -> None:
    """Permanently delete assets from the archive. This cannot be undone."""
    service = cli_open_service(archive)
    if confirm:
        scope = (
            "selected copies of"
            if file_ids is not None
            else "recycled copies of"
            if recycled_only
            else "all copies of"
        )
        cli_confirm_delete(
            f"Permanently delete {scope} {len(set(asset_ids))} asset(s) from the archive."
        )
    result = service.app_service_purge(
        asset_ids, confirmed=confirm, recycled_only=recycled_only, file_ids=file_ids
    )
    if not confirm:
        typer.echo(f"Dry run: {len(asset_ids)} asset(s) would be purged. Re-run with --confirm.")
    else:
        typer.echo(f"Purged {result.purged_count}, skipped {result.skipped_count}")


@app.command("reclaim")
def cli_reclaim(
    archive: Path = ArchiveOption,
    confirm: bool = typer.Option(False, "--confirm", help="Delete from the phone for real."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print per-item progress."),
    asset_ids: list[int] | None = typer.Option(
        None, "--asset", help="Restrict to these archived asset ids (repeatable)."
    ),
    device_udid: str | None = typer.Option(None, "--device", help="Select this device UDID."),
) -> None:
    """Free space on the phone by deleting only archived, re-verified assets."""
    service = cli_open_service(archive)
    source = cli_build_source(device_udid)
    if confirm:
        cli_confirm_delete("Permanently delete freshly verified candidate files from the phone.")
    result = service.app_service_reclaim(
        source, confirm, cli_progress(verbose), asset_ids=asset_ids
    )
    if result.dry_run:
        typer.echo(
            f"Dry run: {len(result.candidates)} item(s), {result.reclaimable_bytes} bytes "
            "could be freed. Re-run with --confirm."
        )
        for candidate in result.candidates:
            typer.echo(f"  {candidate.asset_id}  {candidate.size}  {candidate.phone_path}")
    else:
        typer.echo(f"Deleted {result.deleted_count} item(s) from the phone")
    if result.skipped_count:
        typer.echo(f"Skipped {result.skipped_count} item(s)")
    if result.errors:
        for error in result.errors:
            typer.echo(error, err=True)
        raise typer.Exit(EXIT_FAILURE)


@marks_app.command("add")
def cli_marks_add(
    target_id: int = typer.Argument(..., help="Asset or album id to mark."),
    archive: Path = ArchiveOption,
    album: bool = typer.Option(False, "--album", help="Treat the id as an album id."),
    file: bool = typer.Option(False, "--file", help="Treat the id as one archive file id."),
    reason: str | None = typer.Option(None, "--reason", help="Optional note."),
) -> None:
    """Stage a mark-for-delete. Nothing is deleted until you commit."""
    service = cli_open_service(archive)
    if album and file:
        cli_fail("Choose only one of --album or --file.")
    target_type = "file" if file else TARGET_ALBUM if album else TARGET_ASSET
    mark_id = service.app_service_mark(target_type, target_id, reason)
    typer.echo(f"Marked {target_type} {target_id} (mark {mark_id})")


@marks_app.command("list")
def cli_marks_list(archive: Path = ArchiveOption) -> None:
    """List staged, uncommitted marks."""
    service = cli_open_service(archive)
    pending = service.app_service_list_marks()
    for mark in pending:
        typer.echo(f"{mark.mark_id:>5}  {mark.target_type:>5} {mark.target_id:>6}  {mark.reason}")
    typer.echo(f"{len(pending)} pending mark(s)")


@marks_app.command("remove")
def cli_marks_remove(
    mark_id: int = typer.Argument(..., help="Mark id to cancel."),
    archive: Path = ArchiveOption,
) -> None:
    """Cancel a staged mark."""
    service = cli_open_service(archive)
    service.app_service_unmark(mark_id)
    typer.echo(f"Removed mark {mark_id}")


@marks_app.command("commit")
def cli_marks_commit(
    archive: Path = ArchiveOption,
    confirm: bool = typer.Option(False, "--confirm", help="Required; without it nothing happens."),
    purge: bool = typer.Option(False, "--purge", help="Delete permanently instead of recycling."),
) -> None:
    """Apply staged marks by recycling them, or purging with --purge."""
    service = cli_open_service(archive)
    if not confirm:
        pending = len(service.app_service_list_marks())
        typer.echo(f"Dry run: {pending} mark(s) pending. Re-run with --confirm.")
        return
    if purge:
        cli_confirm_delete("Permanently delete the files covered by the pending marks.")
    result = service.app_service_commit_marks(confirmed=True, purge=purge)
    typer.echo(f"Recycled {result.moved_count}, purged {result.purged_count}")


@app.command("move")
def cli_move(
    album_name: str = typer.Argument(..., help="Destination album name."),
    asset_ids: list[int] = typer.Argument(..., help="Asset ids to move."),
    archive: Path = ArchiveOption,
    source_album: int | None = typer.Option(
        None, "--from-album", help="Move only copies in this album, retaining other albums."
    ),
    file_ids: list[int] | None = typer.Option(
        None, "--file", help="Restrict to file ids (repeatable)."
    ),
) -> None:
    """Move a selection of assets into another album."""
    service = cli_open_service(archive)
    result = service.app_service_move_selection(
        asset_ids, album_name, source_album_id=source_album, file_ids=file_ids
    )
    typer.echo(f"Moved {result.affected_count}, skipped {result.skipped_count}")


@app.command("thumbnail")
def cli_thumbnail(
    asset_id: int = typer.Argument(..., help="Asset id to preview."),
    archive: Path = ArchiveOption,
    size: int | None = typer.Option(None, "--size", help="Longest edge in pixels."),
) -> None:
    """Generate and cache a preview image for an asset."""
    service = cli_open_service(archive)
    result = service.app_service_thumbnail(asset_id, size)
    if not result.available:
        cli_fail(f"No thumbnail: {result.error}")
    typer.echo(str(result.path))


@app.command("clear-thumbnails")
def cli_clear_thumbnails(archive: Path = ArchiveOption) -> None:
    """Remove regenerable cached previews without touching original media."""
    removed = cli_open_service(archive).app_service_clear_thumbnails()
    typer.echo(f"Removed {removed} cached thumbnail(s).")


@marks_app.command("clear")
def cli_marks_clear(archive: Path = ArchiveOption) -> None:
    """Cancel every pending mark without deleting media."""
    removed = cli_open_service(archive).app_service_clear_marks()
    typer.echo(f"Removed {removed} pending mark(s).")


@config_app.command("list")
def cli_config_list() -> None:
    """Show every setting and its current value."""
    service = AppService(Path.cwd())
    settings = service.app_service_get_settings()
    for name in settings_field_names():
        typer.echo(f"{name:>24}: {getattr(settings, name)}")
    typer.echo(f"\nStored in {service.app_service_settings_path()}")


@config_app.command("get")
def cli_config_get(
    key: str = typer.Argument(..., help="Setting name, as shown by 'config list'."),
) -> None:
    """Show one setting."""
    try:
        if key not in settings_field_names():
            raise SettingsError(f"unknown setting: {key}")
        typer.echo(str(getattr(AppService(Path.cwd()).app_service_get_settings(), key)))
    except SettingsError as error:
        cli_fail(str(error))


@config_app.command("set")
def cli_config_set(
    key: str = typer.Argument(..., help="Setting name, as shown by 'config list'."),
    value: str = typer.Argument(..., help="New value."),
) -> None:
    """Change one setting. Invalid values are rejected and nothing is written."""
    try:
        AppService(Path.cwd()).app_service_set_setting(key, value)
    except SettingsError as error:
        cli_fail(str(error))
    typer.echo(f"{key} = {value}")


@config_app.command("reset")
def cli_config_reset() -> None:
    """Restore every setting to its default."""
    AppService(Path.cwd()).app_service_reset_settings()
    typer.echo("Settings restored to defaults.")


@config_app.command("path")
def cli_config_path() -> None:
    """Show where the settings file lives."""
    typer.echo(str(AppService(Path.cwd()).app_service_settings_path()))


@config_app.command("forget")
def cli_config_forget(
    archive_root: Path = typer.Argument(..., help="Archive to drop from the recent list."),
) -> None:
    """Forget an archive. Only the preference is removed; no files are touched."""
    AppService(Path.cwd()).app_service_forget_archive(archive_root)
    typer.echo(f"Forgot {archive_root}. No files were changed.")


def main() -> int:
    """Entry point for the ``ibackup`` console script.

    Returns the process exit code.
    """
    logging_setup_configure()
    exit_code = EXIT_OK
    try:
        app()
    except SystemExit as error:
        exit_code = int(error.code or EXIT_OK)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
