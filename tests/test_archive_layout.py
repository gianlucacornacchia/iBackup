"""Tests for placing files into the archive's album folders."""

from __future__ import annotations

import hashlib
import io

import pytest

from iphone_archive import config
from iphone_archive.core import archive_layout


def make_archive(tmp_path):
    """Initialize a temporary archive and return its paths."""
    return config.config_initialize_archive(tmp_path / "archive")


def test_store_stream_writes_and_hashes(tmp_path):
    """Stored content is byte-for-byte identical and correctly hashed."""
    paths = make_archive(tmp_path)
    payload = b"photo-bytes" * 500
    target = archive_layout.archive_layout_album_dir(paths, "Family Trip")

    placed = archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(payload), target, "IMG_0001.HEIC"
    )

    assert placed.path.read_bytes() == payload
    assert placed.sha256 == hashlib.sha256(payload).hexdigest()
    assert placed.size == len(payload)
    assert placed.path.parent.name == "Family Trip"


def test_no_temp_file_left_behind(tmp_path):
    """Atomic placement leaves no .partial staging file."""
    paths = make_archive(tmp_path)
    archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(b"data"), paths.unsorted_dir, "IMG.JPG"
    )
    assert list(paths.temp_dir.glob("*.partial")) == []


def test_album_dir_sanitizes_name(tmp_path):
    """Album folder names are made Windows-safe."""
    paths = make_archive(tmp_path)
    target = archive_layout.archive_layout_album_dir(paths, "Trip: <2024>?")
    for char in '<>:"/\\|?*':
        assert char not in target.name


def test_album_less_goes_to_unsorted(tmp_path):
    """An album-less asset is filed under _Unsorted."""
    paths = make_archive(tmp_path)
    assert archive_layout.archive_layout_album_dir(paths, None) == paths.unsorted_dir


def test_unsorted_dated_folder(tmp_path):
    """Album-less assets are filed under _Unsorted/YYYY/MM."""
    paths = make_archive(tmp_path)
    target = archive_layout.archive_layout_unsorted_dir(paths, "2024-03-15T10:00:00")
    assert target.parts[-2:] == ("2024", "03")


def test_unsorted_dated_folder_bad_timestamp(tmp_path):
    """An unparsable capture time still yields a dated folder."""
    paths = make_archive(tmp_path)
    target = archive_layout.archive_layout_unsorted_dir(paths, "not-a-date")
    assert target.parent.parent == paths.unsorted_dir


def test_name_collision_gets_unique_path(tmp_path):
    """Two different files with the same name both survive."""
    paths = make_archive(tmp_path)
    target = archive_layout.archive_layout_album_dir(paths, "Trip")

    first = archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(b"one"), target, "IMG_0001.HEIC"
    )
    second = archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(b"two"), target, "IMG_0001.HEIC"
    )

    assert first.path != second.path
    assert first.path.read_bytes() == b"one"
    assert second.path.read_bytes() == b"two"


def test_duplicate_file_copy_mode(tmp_path):
    """A multi-album asset becomes a real file in the second album."""
    paths = make_archive(tmp_path)
    first_dir = archive_layout.archive_layout_album_dir(paths, "Trip")
    second_dir = archive_layout.archive_layout_album_dir(paths, "Favorites")
    placed = archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(b"shared"), first_dir, "IMG.HEIC"
    )

    duplicate = archive_layout.archive_layout_duplicate_file(placed.path, second_dir)

    assert duplicate.path.is_file()
    assert not duplicate.path.is_symlink()
    assert duplicate.sha256 == placed.sha256


def test_duplicate_file_hardlink_mode(tmp_path):
    """Hardlink mode still yields a real, non-symlink file with equal content."""
    paths = make_archive(tmp_path)
    first_dir = archive_layout.archive_layout_album_dir(paths, "Trip")
    second_dir = archive_layout.archive_layout_album_dir(paths, "Favorites")
    placed = archive_layout.archive_layout_store_stream(
        paths, io.BytesIO(b"shared"), first_dir, "IMG.HEIC"
    )

    duplicate = archive_layout.archive_layout_duplicate_file(
        placed.path, second_dir, link_mode=archive_layout.LINK_MODE_HARDLINK
    )

    assert not duplicate.path.is_symlink()
    assert duplicate.path.read_bytes() == b"shared"
    assert duplicate.link_mode in (
        archive_layout.LINK_MODE_HARDLINK,
        archive_layout.LINK_MODE_COPY,
    )


def test_relative_path_uses_forward_slashes(tmp_path):
    """Catalog paths are archive-relative POSIX paths."""
    paths = make_archive(tmp_path)
    target = archive_layout.archive_layout_album_dir(paths, "Trip")
    placed = archive_layout.archive_layout_store_stream(paths, io.BytesIO(b"x"), target, "IMG.HEIC")
    relative = archive_layout.archive_layout_relative_path(paths, placed.path)
    assert relative.startswith("Photos/Trip/")
    assert "\\" not in relative


def test_exclusive_copy_never_overwrites_existing_file(tmp_path):
    """Destination collisions preserve the original bytes even on the fallback path."""
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"new")
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        archive_layout.archive_layout_copy_exclusive(source, destination)
    assert destination.read_bytes() == b"original"


def test_missing_atomic_publication_fails_without_partial_final(tmp_path, monkeypatch):
    """Unsupported publication must not fall back to an untracked public file creation."""

    def unsupported(*args, **kwargs):
        raise OSError("hardlinks unsupported")

    monkeypatch.setattr(archive_layout, "file_operations_publish", unsupported)
    paths = make_archive(tmp_path)
    with pytest.raises(OSError, match="hardlinks unsupported"):
        archive_layout.archive_layout_store_stream(
            paths, io.BytesIO(b"content"), paths.unsorted_dir, "A.JPG"
        )
    assert not list(paths.unsorted_dir.iterdir())
    assert not list((paths.internal_dir / "import-staging").iterdir())
