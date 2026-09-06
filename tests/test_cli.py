"""Tests for the command-line interface.

The CLI is a thin adapter, so these tests focus on argument wiring, output, exit
codes, and — most importantly — that destructive commands stay safe by default.
An offline fake device is supplied through ``IBACKUP_FAKE_DEVICE``.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from iphone_archive.cli import app

runner = CliRunner()


@pytest.fixture
def phone(tmp_path, monkeypatch):
    """A folder of fake phone media wired in through the environment."""
    folder = tmp_path / "phone"
    folder.mkdir()
    (folder / "A.HEIC").write_bytes(b"photo-a")
    (folder / "B.HEIC").write_bytes(b"photo-b")
    monkeypatch.setenv("IBACKUP_FAKE_DEVICE", str(folder))
    return folder


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """An initialized archive wired in through the environment."""
    root = tmp_path / "archive"
    result = runner.invoke(app, ["init", str(root)])
    assert result.exit_code == 0
    monkeypatch.setenv("IBACKUP_ARCHIVE", str(root))
    return root


def helper_run(*args: str):
    """Invoke the CLI and return the result."""
    return runner.invoke(app, list(args))


def helper_asset_ids(output: str) -> list[str]:
    """Extract asset ids from ``list`` output lines."""
    ids = []
    for line in output.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit() and len(parts) > 1 and not line.endswith("asset(s)"):
            ids.append(parts[0])
    return ids


def test_no_args_shows_help():
    """Running with no arguments prints usage."""
    result = helper_run()
    assert "iPhone Archive" in result.output


def test_init_creates_archive(tmp_path):
    """init creates the archive structure."""
    root = tmp_path / "new-archive"
    result = helper_run("init", str(root))
    assert result.exit_code == 0
    assert (root / ".ibackup").is_dir()
    assert (root / "Photos").is_dir()


def test_commands_fail_clearly_without_archive(tmp_path, monkeypatch):
    """Operating on a non-archive folder gives a helpful error."""
    monkeypatch.setenv("IBACKUP_ARCHIVE", str(tmp_path / "not-an-archive"))
    result = helper_run("stats")
    assert result.exit_code == 1


def test_device_info(phone):
    """device-info reports the fake device and its item count."""
    result = helper_run("device-info")
    assert result.exit_code == 0
    assert "Media items: 2" in result.output


def test_import_then_list_and_stats(archive, phone):
    """A full import is reflected in list and stats output."""
    imported = helper_run("import")
    assert imported.exit_code == 0
    assert "Added 2" in imported.output

    assert "2 asset(s)" in helper_run("list").output
    assert "assets: 2" in helper_run("stats").output


def test_import_is_incremental(archive, phone):
    """Re-importing skips everything already archived."""
    helper_run("import")
    second = helper_run("import")
    assert "Added 0" in second.output
    assert "skipped 2" in second.output


def test_verify_passes_after_import(archive, phone):
    """verify succeeds on a healthy archive."""
    helper_run("import")
    result = helper_run("verify")
    assert result.exit_code == 0
    assert "mismatched 0" in result.output


def test_verify_fails_on_corruption(archive, phone):
    """verify exits non-zero when a file is corrupted."""
    helper_run("import")
    target = next((archive / "Photos").rglob("*.heic"))
    target.write_bytes(b"corrupted")

    result = helper_run("verify")

    assert result.exit_code == 1
    assert "mismatched 1" in result.output


def test_dedup_and_albums_output(archive, phone):
    """dedup and albums produce readable reports."""
    helper_run("import")
    assert "Unique assets: 2" in helper_run("dedup").output
    assert "No albums yet." in helper_run("albums").output


def test_list_unsorted_and_recycled(archive, phone):
    """The list filters target the right collections."""
    helper_run("import")
    assert "2 asset(s)" in helper_run("list", "--unsorted").output
    assert "0 asset(s)" in helper_run("list", "--recycled").output


def test_deleted_on_phone_review_and_recycle(archive, phone):
    """Deleting on the phone surfaces a review, and to-deleted recycles it."""
    helper_run("import")
    (phone / "B.HEIC").unlink()
    helper_run("scan-phone")

    listed = helper_run("deleted-on-phone", "list")
    assert "1 asset(s) deleted on phone" in listed.output

    asset_id = helper_asset_ids(listed.output)[0]
    moved = helper_run("deleted-on-phone", "to-deleted", asset_id)
    assert "Moved 1" in moved.output
    assert "1 asset(s)" in helper_run("list", "--recycled").output


def test_restore_from_recycle_bin(archive, phone):
    """Recycled assets can be restored from the CLI."""
    helper_run("import")
    asset_id = helper_asset_ids(helper_run("list").output)[0]
    helper_run("deleted-on-phone", "to-deleted", asset_id)

    result = helper_run("deleted-on-phone", "restore", asset_id)

    assert "Restored 1" in result.output
    assert "0 asset(s)" in helper_run("list", "--recycled").output


def test_purge_requires_confirm(archive, phone):
    """Purge is a dry run until --confirm is passed."""
    helper_run("import")
    asset_id = helper_asset_ids(helper_run("list").output)[0]

    dry = helper_run("deleted-on-phone", "purge", asset_id)
    assert "Dry run" in dry.output
    assert "2 asset(s)" in helper_run("list").output

    confirmed = helper_run("deleted-on-phone", "purge", asset_id, "--confirm")
    assert "Purged 1" in confirmed.output
    assert "1 asset(s)" in helper_run("list").output


def test_reclaim_is_dry_run_by_default(archive, phone):
    """reclaim never touches the phone without --confirm."""
    helper_run("import")

    dry = helper_run("reclaim")

    assert "Dry run" in dry.output
    assert (phone / "A.HEIC").exists()


def test_reclaim_with_confirm_deletes_on_phone(archive, phone):
    """reclaim --confirm deletes verified assets from the phone only."""
    helper_run("import")

    result = helper_run("reclaim", "--confirm")

    assert "Deleted 2 item(s)" in result.output
    assert "2 asset(s)" in helper_run("list").output


def test_marks_lifecycle(archive, phone):
    """Marks stage, list, and only act on commit --confirm."""
    helper_run("import")
    asset_id = helper_asset_ids(helper_run("list").output)[0]

    helper_run("marks", "add", asset_id, "--reason", "blurry")
    assert "1 pending mark(s)" in helper_run("marks", "list").output

    assert "Dry run" in helper_run("marks", "commit").output
    assert "2 asset(s)" in helper_run("list").output

    assert "Recycled 1" in helper_run("marks", "commit", "--confirm").output
    assert "1 asset(s)" in helper_run("list", "--recycled").output


def test_marks_remove(archive, phone):
    """A staged mark can be cancelled."""
    helper_run("import")
    asset_id = helper_asset_ids(helper_run("list").output)[0]
    helper_run("marks", "add", asset_id)

    helper_run("marks", "remove", "1")

    assert "0 pending mark(s)" in helper_run("marks", "list").output


def test_move_selection(archive, phone):
    """move relocates a selection into a named album."""
    helper_run("import")
    asset_ids = helper_asset_ids(helper_run("list").output)

    result = helper_run("move", "Favorites", *asset_ids)

    assert "Moved 2" in result.output
    assert (archive / "Photos" / "Favorites").is_dir()


def test_thumbnail_reports_unsupported_media(archive, phone):
    """A thumbnail request for non-image content fails cleanly."""
    helper_run("import")
    asset_id = helper_asset_ids(helper_run("list").output)[0]

    result = helper_run("thumbnail", asset_id)

    assert result.exit_code == 1
    assert "No thumbnail" in result.output
