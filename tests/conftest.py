"""Shared pytest fixtures: temporary archives, catalogs, and fake media."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iphone_archive.catalog import database
from iphone_archive.settings import SETTINGS_DIR_ENV_VAR


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect user settings into tmp_path so tests never touch the real profile."""
    config_dir = tmp_path / "config"
    monkeypatch.setenv(SETTINGS_DIR_ENV_VAR, str(config_dir))
    monkeypatch.delenv("IBACKUP_ARCHIVE", raising=False)
    monkeypatch.delenv("IBACKUP_FAKE_DEVICE", raising=False)
    return config_dir


@pytest.fixture
def catalog_connection(tmp_path: Path) -> sqlite3.Connection:
    """An initialized catalog on a temporary path."""
    connection = database.database_connect(tmp_path / ".ibackup" / "catalog.sqlite")
    database.database_initialize(connection)
    yield connection
    connection.close()


@pytest.fixture
def sample_media() -> dict[str, bytes]:
    """A small set of byte blobs standing in for media files."""
    return {
        "IMG_0001.HEIC": b"\x00heic-one" * 64,
        "IMG_0002.JPG": b"\xff\xd8jpeg-two" * 64,
        "VID_0003.MOV": b"\x00\x00mov-three" * 64,
    }
