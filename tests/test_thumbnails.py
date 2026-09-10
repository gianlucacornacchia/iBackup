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
    """Still images and videos are both supported; other files are not."""
    assert thumbnails.thumbnails_is_supported(tmp_path / "a.HEIC")
    assert thumbnails.thumbnails_is_supported(tmp_path / "a.jpg")
    assert thumbnails.thumbnails_is_supported(tmp_path / "a.MOV")
    assert not thumbnails.thumbnails_is_supported(tmp_path / "a.txt")


def test_is_video_by_extension(tmp_path):
    """Video containers are routed to the poster-frame path, images are not."""
    assert thumbnails.thumbnails_is_video(tmp_path / "clip.MOV")
    assert thumbnails.thumbnails_is_video(tmp_path / "clip.mp4")
    assert not thumbnails.thumbnails_is_video(tmp_path / "photo.heic")


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
    """A non-media file reports an unsupported result, not a crash."""
    document = tmp_path / "notes.txt"
    document.write_bytes(b"plain text")

    result = thumbnails.thumbnails_get(paths, "hash5", document)

    assert not result.available
    assert result.error == "unsupported media type"


def test_corrupt_video_reports_error(paths, tmp_path):
    """A file that only looks like a video is reported so the GUI can fall back."""
    movie = tmp_path / "clip.MOV"
    movie.write_bytes(b"not really a movie")

    result = thumbnails.thumbnails_get(paths, "hash5b", movie)

    assert not result.available
    assert result.error


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


# --- Video poster frames -------------------------------------------------
#
# iPhone clips are stored landscape with a display-matrix rotation and often
# open on a black or still-exposing frame, so both the orientation and the
# seek-past-the-lead-in behaviour are pinned down here. Expected orientations
# were cross-checked against the ffmpeg CLI's own autorotate output.

av = pytest.importorskip("av")

VIDEO_WIDTH = 160
VIDEO_HEIGHT = 120
VIDEO_LEAD_IN_FRAMES = 40


def helper_write_video(path, rotation: int = 0, frames: int = 200, lead_in: bool = True) -> None:
    """Write a small test clip with a yellow top-left marker after a black lead-in."""
    from PIL import Image

    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height = VIDEO_WIDTH, VIDEO_HEIGHT
        stream.pix_fmt = "yuv420p"
        if rotation:
            stream.set_display_rotation(rotation)
        for index in range(frames):
            if lead_in and index < VIDEO_LEAD_IN_FRAMES:
                image = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
            else:
                image = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (20, 60, 140))
                image.paste(Image.new("RGB", (40, 30), (255, 255, 0)), (0, 0))
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def helper_marker_corner(image) -> str | None:
    """Report which corner of an image holds the yellow marker, if any."""
    width, height = image.size
    pixels = image.convert("RGB").load()
    corners = {
        "TL": (5, 5),
        "TR": (width - 6, 5),
        "BL": (5, height - 6),
        "BR": (width - 6, height - 6),
    }
    found = None
    for name, (x, y) in corners.items():
        red, green, blue = pixels[x, y]
        if red > 200 and green > 200 and blue < 100:
            found = name
    return found


@pytest.mark.parametrize(
    ("rotation", "expected_corner", "expected_portrait"),
    [(0, "TL", False), (90, "BL", True), (180, "BR", False), (270, "TR", True)],
)
def test_video_frame_matches_ffmpeg_display_orientation(
    tmp_path, rotation, expected_corner, expected_portrait
):
    """Frames are rotated to display orientation exactly as ffmpeg autorotate does."""
    clip = tmp_path / f"rot{rotation}.mov"
    helper_write_video(clip, rotation=rotation, frames=60, lead_in=False)

    frame = thumbnails.thumbnails_extract_video_frame(clip)

    assert helper_marker_corner(frame) == expected_corner
    assert (frame.size[1] > frame.size[0]) is expected_portrait


def test_video_poster_frame_skips_black_lead_in(tmp_path):
    """The poster frame is taken past the opening frames, not from frame zero."""
    clip = tmp_path / "leadin.mov"
    helper_write_video(clip, frames=200)

    frame = thumbnails.thumbnails_extract_video_frame(clip)

    assert helper_marker_corner(frame) == "TL"
    assert frame.convert("RGB").getextrema()[2][1] > 0


def test_video_seek_offset_stays_inside_short_clips():
    """The seek offset never runs past the end of a clip and is capped for long ones."""
    assert thumbnails.thumbnails_video_seek_seconds(None) == 0.0
    assert thumbnails.thumbnails_video_seek_seconds(0) == 0.0
    assert thumbnails.thumbnails_video_seek_seconds(0.2) == pytest.approx(0.02)
    assert thumbnails.thumbnails_video_seek_seconds(10) == pytest.approx(1.0)
    assert thumbnails.thumbnails_video_seek_seconds(600) == thumbnails.VIDEO_SEEK_MAX_SECONDS


def test_video_thumbnail_is_cached_downscaled_jpeg(paths, tmp_path):
    """A video yields a cached JPEG preview bounded by the requested size."""
    from PIL import Image

    clip = tmp_path / "clip.MOV"
    helper_write_video(clip, rotation=90, frames=60, lead_in=False)

    first = thumbnails.thumbnails_get(paths, "vid1", clip, size=64)
    second = thumbnails.thumbnails_get(paths, "vid1", clip, size=64)

    assert first.available and not first.cached
    assert second.available and second.cached
    with Image.open(first.path) as preview:
        assert preview.format == "JPEG"
        assert max(preview.size) <= 64
        # Rotation must survive the downscale, or portrait clips read sideways.
        assert preview.size[1] > preview.size[0]


def test_video_original_is_never_modified(paths, tmp_path):
    """Generating a poster frame leaves the archived clip byte-identical."""
    clip = tmp_path / "clip.mov"
    helper_write_video(clip, frames=60, lead_in=False)
    before = clip.read_bytes()

    thumbnails.thumbnails_get(paths, "vid2", clip)

    assert clip.read_bytes() == before


def test_audio_only_file_reports_no_video_stream(paths, tmp_path):
    """A container without a video stream is reported, not raised."""
    clip = tmp_path / "audio.mp4"
    with av.open(str(clip), "w") as container:
        stream = container.add_stream("aac", rate=44100)
        for packet in stream.encode():
            container.mux(packet)

    result = thumbnails.thumbnails_get(paths, "vid3", clip)

    assert not result.available
    assert result.error


def test_missing_pyav_degrades_to_placeholder(paths, tmp_path, monkeypatch):
    """Without PyAV installed, videos report an error instead of crashing."""
    clip = tmp_path / "clip.mov"
    helper_write_video(clip, frames=30, lead_in=False)
    monkeypatch.setitem(__import__("sys").modules, "av", None)

    result = thumbnails.thumbnails_get(paths, "vid4", clip)

    assert not result.available
    assert result.error
