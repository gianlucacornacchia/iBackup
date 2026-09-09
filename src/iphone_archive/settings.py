"""Persisted user preferences.

Settings are *user defaults*, never archive semantics: they choose which archive
opens by default and how operations are pre-configured, but they can never
weaken the append-only guarantee or cause anything to be deleted automatically.
Safety options are deliberately one-way — they may only add friction.

The file lives per-user outside the archive
(``%APPDATA%\\ibackup\\settings.json`` on Windows) so an archive folder stays a
pure, portable data directory that can be moved between machines.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .core.archive_layout import LINK_MODE_COPY, LINK_MODE_HARDLINK

LOGGER = logging.getLogger(__name__)

SETTINGS_DIR_NAME = "ibackup"
SETTINGS_FILE_NAME = "settings.json"
SETTINGS_DIR_ENV_VAR = "IBACKUP_CONFIG_DIR"

MAX_RECENT_ARCHIVES = 10
THUMBNAIL_SIZE_CHOICES = (128, 256, 512)
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR")
DELETED_ACTION_RECYCLE = "recycle"
DELETED_ACTION_PURGE = "purge"
DELETED_ACTION_CHOICES = (DELETED_ACTION_RECYCLE, DELETED_ACTION_PURGE)


class SettingsError(ValueError):
    """Raised when a settings key or value is not valid."""


@dataclass
class Settings:
    """User preferences applied as defaults to CLI and GUI operations."""

    default_archive: str | None = None
    reopen_last_archive: bool = True
    recent_archives: list[str] = field(default_factory=list)
    album_link_mode: str = LINK_MODE_COPY
    scan_phone_after_import: bool = True
    thumbnail_size: int = 256
    confirm_word_required: bool = True
    default_deleted_action: str = DELETED_ACTION_RECYCLE
    log_level: str = "INFO"


def settings_directory() -> Path:
    """Resolve the per-user folder holding the settings file.

    Returns the settings directory. ``IBACKUP_CONFIG_DIR`` overrides it, which
    keeps tests and portable installs isolated from the real user profile.
    """
    override = os.environ.get(SETTINGS_DIR_ENV_VAR)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / SETTINGS_DIR_NAME


def settings_path() -> Path:
    """Resolve the full path of the settings file.

    Returns the location of ``settings.json``.
    """
    return settings_directory() / SETTINGS_FILE_NAME


def settings_field_names() -> list[str]:
    """List every configurable setting key.

    Returns the setting names in declaration order.
    """
    return [item.name for item in fields(Settings)]


def settings_load() -> Settings:
    """Read the settings file, falling back to defaults.

    Returns the stored ``Settings``. A missing, unreadable, or corrupt file
    yields defaults rather than an error, so a bad file can never block the app.
    """
    target = settings_path()
    result = Settings()
    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.warning("ignoring unreadable settings file %s: %s", target, error)
        else:
            if not isinstance(raw, dict):
                raise SettingsError(f"settings file must contain an object: {target}")
            known = settings_field_names()
            for key, value in raw.items():
                if key in known:
                    setattr(result, key, value)
                else:
                    LOGGER.debug("ignoring unknown setting %r", key)
            settings_validate(result)
    return result


def settings_save(settings: Settings) -> Path:
    """Write settings to disk atomically.

    settings: the preferences to persist.
    Returns the path written.
    """
    settings_validate(settings)
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".tmp")
    staging.write_text(json.dumps(asdict(settings), indent=2, sort_keys=True), encoding="utf-8")
    staging.replace(target)
    return target


def settings_coerce(key: str, value: str) -> object:
    """Convert a text value from the CLI into the type a setting expects.

    key: the setting name.
    value: the raw text supplied by the user.
    Returns the converted value. Raises ``SettingsError`` on a bad key or value.
    """
    if key not in settings_field_names():
        raise SettingsError(f"unknown setting: {key}")
    booleans = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}
    lowered = value.strip().lower()
    if key in {"reopen_last_archive", "scan_phone_after_import", "confirm_word_required"}:
        if lowered not in booleans:
            raise SettingsError(f"{key} must be true or false, got {value!r}")
        return booleans[lowered]
    if key == "thumbnail_size":
        if not lowered.isdigit():
            raise SettingsError(f"thumbnail_size must be a number, got {value!r}")
        return int(lowered)
    if key == "recent_archives":
        raise SettingsError("recent_archives is managed automatically and cannot be set")
    if key == "default_archive":
        return str(Path(value).expanduser()) if value else None
    return value


def settings_validate(settings: Settings) -> None:
    """Check that every value is one the application supports.

    settings: the preferences to check.
    Returns None. Raises ``SettingsError`` describing the first invalid value.
    """
    for name in ("reopen_last_archive", "scan_phone_after_import", "confirm_word_required"):
        if not isinstance(getattr(settings, name), bool):
            raise SettingsError(f"{name} must be a boolean")
    if settings.default_archive is not None and not isinstance(settings.default_archive, str):
        raise SettingsError("default_archive must be a path string or null")
    if not isinstance(settings.recent_archives, list) or any(
        not isinstance(entry, str) for entry in settings.recent_archives
    ):
        raise SettingsError("recent_archives must be a list of path strings")
    if not isinstance(settings.thumbnail_size, int) or isinstance(settings.thumbnail_size, bool):
        raise SettingsError("thumbnail_size must be an integer")
    if settings.album_link_mode not in (LINK_MODE_COPY, LINK_MODE_HARDLINK):
        raise SettingsError(
            f"album_link_mode must be {LINK_MODE_COPY} or {LINK_MODE_HARDLINK}, "
            f"got {settings.album_link_mode!r}"
        )
    if settings.thumbnail_size not in THUMBNAIL_SIZE_CHOICES:
        raise SettingsError(f"thumbnail_size must be one of {THUMBNAIL_SIZE_CHOICES}")
    if settings.default_deleted_action not in DELETED_ACTION_CHOICES:
        raise SettingsError(f"default_deleted_action must be one of {DELETED_ACTION_CHOICES}")
    if (
        not isinstance(settings.log_level, str)
        or settings.log_level.upper() not in LOG_LEVEL_CHOICES
    ):
        raise SettingsError(f"log_level must be one of {LOG_LEVEL_CHOICES}")
    # A confirmation may be made stricter but never switched off.
    if not settings.confirm_word_required:
        raise SettingsError(
            "confirm_word_required cannot be disabled; destructive actions always confirm"
        )


def settings_set(key: str, value: str) -> Settings:
    """Update one setting and persist the result.

    key: the setting name.
    value: the raw text value to store.
    Returns the saved ``Settings``. Raises ``SettingsError`` when invalid, in
    which case nothing is written.
    """
    settings = settings_load()
    setattr(settings, key, settings_coerce(key, value))
    settings_validate(settings)
    settings_save(settings)
    return settings


def settings_get(key: str) -> object:
    """Read one setting.

    key: the setting name.
    Returns the stored value. Raises ``SettingsError`` for an unknown key.
    """
    if key not in settings_field_names():
        raise SettingsError(f"unknown setting: {key}")
    return getattr(settings_load(), key)


def settings_reset() -> Settings:
    """Restore every setting to its default and persist it.

    Returns the freshly defaulted ``Settings``.
    """
    settings = Settings()
    settings_save(settings)
    return settings


def settings_remember_archive(archive_root: Path) -> Settings:
    """Record an archive as the most recently used one.

    archive_root: the archive that was just opened.
    Returns the saved ``Settings`` with the updated recent list.
    """
    settings = settings_load()
    entry = str(Path(archive_root).expanduser().resolve())
    recent = [item for item in settings.recent_archives if item != entry]
    recent.insert(0, entry)
    settings.recent_archives = recent[:MAX_RECENT_ARCHIVES]
    if settings.default_archive is None:
        settings.default_archive = entry
    settings_save(settings)
    return settings


def settings_forget_archive(archive_root: Path) -> Settings:
    """Drop an archive from the recent list without touching its files.

    archive_root: the archive to forget.
    Returns the saved ``Settings``.
    """
    settings = settings_load()
    entry = str(Path(archive_root).expanduser().resolve())
    settings.recent_archives = [item for item in settings.recent_archives if item != entry]
    if settings.default_archive == entry:
        settings.default_archive = None
    settings_save(settings)
    return settings
