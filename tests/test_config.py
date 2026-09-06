"""Tests for archive path resolution and initialization."""

from __future__ import annotations

from iphone_archive import config


def test_initialize_creates_structure(tmp_path):
    """Initialization creates Photos, Deleted, and the hidden internals."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    assert paths.photos_dir.is_dir()
    assert paths.unsorted_dir.is_dir()
    assert paths.deleted_dir.is_dir()
    assert paths.internal_dir.is_dir()
    assert paths.sidecars_dir.is_dir()
    assert paths.thumbnails_dir.is_dir()
    assert paths.temp_dir.is_dir()
    assert paths.logs_dir.is_dir()


def test_initialize_is_idempotent(tmp_path):
    """Initializing an existing archive does not fail."""
    config.config_initialize_archive(tmp_path / "archive")
    paths = config.config_initialize_archive(tmp_path / "archive")
    assert paths.internal_dir.is_dir()


def test_is_archive_detection(tmp_path):
    """A plain folder is not an archive until initialized."""
    assert not config.config_is_archive(tmp_path / "archive")
    config.config_initialize_archive(tmp_path / "archive")
    assert config.config_is_archive(tmp_path / "archive")


def test_catalog_lives_under_internal(tmp_path):
    """The catalog is inside the hidden folder, not among the photos."""
    paths = config.config_resolve_paths(tmp_path / "archive")
    assert paths.catalog_path.parent == paths.internal_dir
    assert config.PHOTOS_DIR_NAME not in paths.catalog_path.parts
