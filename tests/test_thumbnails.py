"""Tests for thumbnail generation and caching."""

from __future__ import annotations

import pytest

from iphone_archive.browse import thumbnails
from iphone_archive.config import config_initialize_archive
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.service.app_service import AppService

PIL = pytest.importorskip("PIL")


def helper_png_bytes(color: str = "red", size: tuple[int, int] = (600, 400)) -> bytes:
    """Build an in-memory PNG image used as archive content."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def paths(tmp_path):
    """An initialized archive folder structure."""
    return config_initialize_archive(tmp_path / "archive")


def test_is_supported_by_extension(tmp_path):
    """Still images are supported; videos are not."""
    assert thumbnails.thumbnails_is_supported(tmp_path / "a.HEIC")
    assert thumbnails.thumbnails_is_supported(tmp_path / "a.jpg")
    assert not thumbnails.thumbnails_is_supported(tmp_path / "a.MOV")


def test_cache_path_includes_hash_and_size(paths):
    """Cache paths are keyed by content hash and requested size."""
    cache_path = thumbnails.thumbnails_cache_path(paths, "abc123", 256)
    assert cache_path.parent == paths.thumbnails_dir
    assert cache_path.name == "abc123_256.jpg"


def test_generate_then_reuse_cache(paths, tmp_path):
    """The first request renders; the second is served from cache."""
    source = tmp_path / "photo.png"
    source.write_bytes(helper_png_bytes())

    first = thumbnails.thumbnails_get(paths, "hash1", source)
    second = thumbnails.thumbnails_get(paths, "hash1", source)

    assert first.available and not first.cached
    assert second.available and second.cached
    assert first.path == second.path


def test_thumbnail_is_downscaled_jpeg(paths, tmp_path):
    """Previews are JPEG and fit inside the requested bounding box."""
    from PIL import Image

    source = tmp_path / "photo.png"
    source.write_bytes(helper_png_bytes(size=(1000, 500)))

    result = thumbnails.thumbnails_get(paths, "hash2", source, size=128)

    with Image.open(result.path) as preview:
        assert preview.format == "JPEG"
        assert max(preview.size) <= 128


def test_original_is_never_modified(paths, tmp_path):
    """Rendering a preview leaves the archived original byte-identical."""
    original = helper_png_bytes()
    source = tmp_path / "photo.png"
    source.write_bytes(original)

    thumbnails.thumbnails_get(paths, "hash3", source)

    assert source.read_bytes() == original


def test_missing_source_reports_error(paths, tmp_path):
    """A vanished original yields an error result rather than raising."""
    result = thumbnails.thumbnails_get(paths, "hash4", tmp_path / "gone.png")

    assert not result.available
    assert result.error == "source file is missing"


def test_unsupported_media_reports_error(paths, tmp_path):
    """Videos report an unsupported result so the GUI can use a placeholder."""
    movie = tmp_path / "clip.MOV"
    movie.write_bytes(b"not really a movie")

    result = thumbnails.thumbnails_get(paths, "hash5", movie)

    assert not result.available
    assert result.error == "unsupported media type"


def test_corrupt_image_reports_error(paths, tmp_path):
    """An undecodable image is reported, not raised."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"garbage")

    result = thumbnails.thumbnails_get(paths, "hash6", broken)

    assert not result.available
    assert result.error


def test_refresh_regenerates(paths, tmp_path):
    """Refreshing bypasses the cache."""
    source = tmp_path / "photo.png"
    source.write_bytes(helper_png_bytes())
    thumbnails.thumbnails_get(paths, "hash7", source)

    refreshed = thumbnails.thumbnails_get(paths, "hash7", source, refresh=True)

    assert refreshed.available and not refreshed.cached


def test_purge_and_clear_cache(paths, tmp_path):
    """Cached previews can be dropped per asset or wholesale."""
    source = tmp_path / "photo.png"
    source.write_bytes(helper_png_bytes())
    thumbnails.thumbnails_get(paths, "hash8", source, size=128)
    thumbnails.thumbnails_get(paths, "hash8", source, size=256)
    thumbnails.thumbnails_get(paths, "hash9", source, size=128)

    assert thumbnails.thumbnails_purge(paths, "hash8") == 2
    assert thumbnails.thumbnails_clear_cache(paths) == 1


def test_no_partial_files_left_behind(paths, tmp_path):
    """Atomic writes leave no staging files in the cache."""
    source = tmp_path / "photo.png"
    source.write_bytes(helper_png_bytes())

    thumbnails.thumbnails_get(paths, "hash10", source)

    assert list(paths.thumbnails_dir.glob("*.part")) == []


def test_service_thumbnail_for_imported_asset(tmp_path):
    """The facade renders a preview for an archived asset."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()
    service.app_service_import(FakeDevice({"/DCIM/A.PNG": helper_png_bytes()}))
    asset_id = service.app_service_list_assets()[0].asset_id

    result = service.app_service_thumbnail(asset_id)

    assert result.available
    assert service.app_service_clear_thumbnails() == 1
    service.app_service_close()


def test_service_thumbnail_unknown_asset(tmp_path):
    """An unknown asset id reports an error instead of raising."""
    service = AppService(tmp_path / "archive")
    service.app_service_initialize()

    result = service.app_service_thumbnail(999)

    assert not result.available
    assert result.error == "unknown asset"
    service.app_service_close()
