"""Tests for persisted user preferences and the ``ibackup config`` command."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from iphone_archive import settings as settings_module
from iphone_archive.cli import app
from iphone_archive.core.archive_layout import LINK_MODE_HARDLINK
from iphone_archive.service.app_service import AppService
from iphone_archive.settings import (
    Settings,
    SettingsError,
    settings_forget_archive,
    settings_get,
    settings_load,
    settings_path,
    settings_remember_archive,
    settings_reset,
    settings_save,
    settings_set,
    settings_validate,
)

runner = CliRunner()


def test_defaults_when_no_file_exists():
    """A fresh install reports sane defaults without writing anything."""
    loaded = settings_load()

    assert loaded == Settings()
    assert loaded.album_link_mode == "copy"
    assert loaded.confirm_word_required is True
    assert not settings_path().exists()


def test_save_then_load_round_trip():
    """Saved preferences survive a reload."""
    stored = Settings(default_archive="D:/arch", thumbnail_size=512, log_level="DEBUG")

    settings_save(stored)

    assert settings_load() == stored


def test_settings_file_location_is_overridable(isolated_settings):
    """The config directory honours IBACKUP_CONFIG_DIR, keeping tests isolated."""
    assert settings_path().parent == isolated_settings


def test_corrupt_file_falls_back_to_defaults():
    """A damaged settings file never blocks the application."""
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json", encoding="utf-8")

    assert settings_load() == Settings()


def test_unknown_keys_in_file_are_ignored():
    """Forward-compatibility: unknown keys are dropped, known ones survive."""
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"log_level": "DEBUG", "from_future": 1}), encoding="utf-8")

    loaded = settings_load()

    assert loaded.log_level == "DEBUG"
    assert not hasattr(loaded, "from_future")


def test_set_and_get_round_trip():
    """A value set through the API reads back converted to its real type."""
    settings_set("thumbnail_size", "512")
    settings_set("reopen_last_archive", "false")

    assert settings_get("thumbnail_size") == 512
    assert settings_get("reopen_last_archive") is False


def test_unknown_key_is_rejected():
    """Typos are reported instead of silently stored."""
    with pytest.raises(SettingsError):
        settings_set("colour_scheme", "dark")
    with pytest.raises(SettingsError):
        settings_get("colour_scheme")


def test_invalid_values_are_rejected_and_nothing_is_written():
    """A rejected value leaves the previous settings untouched."""
    settings_set("thumbnail_size", "512")

    with pytest.raises(SettingsError):
        settings_set("thumbnail_size", "999")
    with pytest.raises(SettingsError):
        settings_set("album_link_mode", "symlink")

    assert settings_get("thumbnail_size") == 512


def test_confirmation_cannot_be_disabled():
    """Safety options may add friction but never remove it."""
    with pytest.raises(SettingsError):
        settings_set("confirm_word_required", "false")

    assert settings_get("confirm_word_required") is True
    with pytest.raises(SettingsError):
        settings_validate(Settings(confirm_word_required=False))


def test_recent_archives_are_managed_not_set():
    """The recent list is maintained by the app, not hand-edited."""
    with pytest.raises(SettingsError):
        settings_set("recent_archives", "D:/arch")


def test_hardlink_mode_is_accepted():
    """Both supported album link modes validate."""
    settings_set("album_link_mode", LINK_MODE_HARDLINK)
    assert settings_get("album_link_mode") == LINK_MODE_HARDLINK


def test_remember_archive_updates_recent_and_default(tmp_path):
    """Opening an archive records it, most-recent-first, without duplicates."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()

    settings_remember_archive(first)
    settings_remember_archive(second)
    settings_remember_archive(first)

    loaded = settings_load()
    assert loaded.recent_archives == [str(first.resolve()), str(second.resolve())]
    assert loaded.default_archive == str(first.resolve())


def test_recent_archives_are_capped(tmp_path):
    """The recent list does not grow without bound."""
    for index in range(settings_module.MAX_RECENT_ARCHIVES + 5):
        folder = tmp_path / f"archive{index}"
        folder.mkdir()
        settings_remember_archive(folder)

    assert len(settings_load().recent_archives) == settings_module.MAX_RECENT_ARCHIVES


def test_forget_archive_touches_no_files(tmp_path):
    """Forgetting an archive is a preference change only."""
    root = tmp_path / "arch"
    root.mkdir()
    (root / "keepme.txt").write_text("data", encoding="utf-8")
    settings_remember_archive(root)

    settings_forget_archive(root)

    assert settings_load().recent_archives == []
    assert settings_load().default_archive is None
    assert (root / "keepme.txt").read_text(encoding="utf-8") == "data"


def test_reset_restores_defaults():
    """Reset clears every customization."""
    settings_set("thumbnail_size", "512")

    settings_reset()

    assert settings_load() == Settings()


def test_service_exposes_settings(tmp_path):
    """The facade reads and writes settings, so the GUI has parity with the CLI."""
    service = AppService(tmp_path / "archive")

    updated = service.app_service_update_settings(Settings(log_level="DEBUG"))

    assert updated.log_level == "DEBUG"
    assert service.app_service_get_settings().log_level == "DEBUG"
    service.app_service_close()


def test_service_rejects_invalid_settings(tmp_path):
    """Invalid preferences are refused by the facade too."""
    service = AppService(tmp_path / "archive")

    with pytest.raises(SettingsError):
        service.app_service_update_settings(Settings(thumbnail_size=999))

    service.app_service_close()


def test_initializing_an_archive_remembers_it(tmp_path):
    """Opening an archive makes it the default for later commands."""
    root = tmp_path / "archive"
    service = AppService(root)

    service.app_service_initialize()

    assert settings_load().default_archive == str(root.resolve())
    service.app_service_close()


def test_cli_config_list_and_path():
    """config list shows every key and where it is stored."""
    result = runner.invoke(app, ["config", "list"])

    assert result.exit_code == 0
    assert "album_link_mode" in result.output
    assert str(settings_path()) in result.output


def test_cli_config_set_get_and_reset():
    """config set/get/reset round-trip through the CLI."""
    assert runner.invoke(app, ["config", "set", "thumbnail_size", "512"]).exit_code == 0
    assert "512" in runner.invoke(app, ["config", "get", "thumbnail_size"]).output

    runner.invoke(app, ["config", "reset"])

    assert "256" in runner.invoke(app, ["config", "get", "thumbnail_size"]).output


def test_cli_config_rejects_bad_values():
    """The CLI reports invalid settings with a non-zero exit code."""
    bad_value = runner.invoke(app, ["config", "set", "thumbnail_size", "999"])
    bad_key = runner.invoke(app, ["config", "get", "nonsense"])

    assert bad_value.exit_code == 1
    assert bad_key.exit_code == 1


def test_cli_uses_default_archive_from_settings(tmp_path):
    """After init, commands work without --archive because the default is stored."""
    root = tmp_path / "archive"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "assets: 0" in result.output


def test_explicit_archive_option_wins_over_settings(tmp_path):
    """An explicit --archive overrides the stored default."""
    stored = tmp_path / "stored"
    other = tmp_path / "other"
    runner.invoke(app, ["init", str(stored)])
    runner.invoke(app, ["init", str(other)])

    result = runner.invoke(app, ["stats", "--archive", str(stored)])

    assert result.exit_code == 0


def test_cli_config_forget(tmp_path):
    """config forget drops the archive from preferences but keeps the data."""
    root = tmp_path / "archive"
    runner.invoke(app, ["init", str(root)])

    result = runner.invoke(app, ["config", "forget", str(root)])

    assert "No files were changed" in result.output
    assert settings_load().recent_archives == []
    assert (root / ".ibackup").is_dir()


def test_import_uses_configured_link_mode(tmp_path, monkeypatch):
    """The stored album link mode is applied when the flag is omitted."""
    phone = tmp_path / "phone"
    phone.mkdir()
    (phone / "A.HEIC").write_bytes(b"a")
    monkeypatch.setenv("IBACKUP_FAKE_DEVICE", str(phone))
    runner.invoke(app, ["init", str(tmp_path / "archive")])
    runner.invoke(app, ["config", "set", "album_link_mode", LINK_MODE_HARDLINK])

    result = runner.invoke(app, ["import"])

    assert result.exit_code == 0
    assert "Added 1" in result.output


def test_scan_after_import_is_configurable(tmp_path, monkeypatch):
    """Disabling the post-import scan skips the extra phone pass."""
    phone = tmp_path / "phone"
    phone.mkdir()
    (phone / "A.HEIC").write_bytes(b"a")
    monkeypatch.setenv("IBACKUP_FAKE_DEVICE", str(phone))
    runner.invoke(app, ["init", str(tmp_path / "archive")])
    runner.invoke(app, ["config", "set", "scan_phone_after_import", "false"])

    assert runner.invoke(app, ["import"]).exit_code == 0
    assert settings_get("scan_phone_after_import") is False
