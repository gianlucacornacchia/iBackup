"""Thumbnail generation and caching for archive browsing.

Neither Qt nor browsers can display HEIC/HEVC natively, so previews are
transcoded to JPEG once and cached under ``.ibackup/thumbnails/`` keyed by the
asset's SHA-256. Originals are only ever read, never modified, which keeps the
append-only guarantee intact.

Videos get a poster frame extracted with PyAV, which ships FFmpeg in its wheels
and so needs no system FFmpeg install on Windows. iPhone clips are recorded in
landscape and carry a display-matrix rotation, so the frame is rotated to its
display orientation before it is saved; skipping that step renders every
portrait video sideways. PyAV is imported lazily and a missing or broken
install degrades to a placeholder rather than breaking image thumbnails.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..config import ArchivePaths

if TYPE_CHECKING:
    from PIL.Image import Image as PillowImage

LOGGER = logging.getLogger(__name__)

DEFAULT_THUMBNAIL_SIZE = 256
THUMBNAIL_SUFFIX = ".jpg"
THUMBNAIL_QUALITY = 85

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
)
VIDEO_EXTENSIONS = frozenset({".mov", ".mp4", ".m4v", ".avi", ".3gp", ".3g2", ".mkv"})

# Poster frames are taken a little way in because the opening frames of a clip
# are often black, blurred or still auto-exposing.
VIDEO_SEEK_FRACTION = 0.1
VIDEO_SEEK_MAX_SECONDS = 2.0
# Seeking lands on the keyframe before the target, so frames are decoded
# forward from there. The cap stops a pathological file scanning forever.
VIDEO_MAX_SCAN_FRAMES = 600
# Clips that open on a fade-in or a dark room would otherwise produce a black
# tile, so a nearly-black poster frame triggers a short search for a better one.
VIDEO_DARK_LUMA = 16.0
VIDEO_DARK_SCAN_FRAMES = 120


@dataclass(frozen=True)
class ThumbnailResult:
    """Outcome of a thumbnail request."""

    sha256: str
    path: Path | None
    cached: bool
    error: str | None = None

    @property
    def available(self) -> bool:
        """Report whether a usable thumbnail file was produced."""
        return self.path is not None


def thumbnails_is_video(source_path: Path) -> bool:
    """Report whether a file is a video needing a poster frame rather than a decode.

    source_path: the archived original to inspect.
    Returns True for container formats handled by the video path.
    """
    return source_path.suffix.lower() in VIDEO_EXTENSIONS


def thumbnails_is_supported(source_path: Path) -> bool:
    """Report whether a file type can be rendered into a thumbnail.

    source_path: the archived original to inspect.
    Returns True for still images Pillow (plus pillow-heif) can decode and for
    videos PyAV can open.
    """
    return thumbnails_is_video(source_path) or source_path.suffix.lower() in IMAGE_EXTENSIONS


def thumbnails_cache_path(paths: ArchivePaths, sha256: str, size: int) -> Path:
    """Compute the cache location of an asset's thumbnail.

    paths: resolved archive paths.
    sha256: content hash identifying the asset.
    size: the requested bounding-box size in pixels.
    Returns the path the thumbnail is or would be cached at.
    """
    return paths.thumbnails_dir / f"{sha256}_{size}{THUMBNAIL_SUFFIX}"


def thumbnails_register_heif() -> bool:
    """Register the HEIF/HEIC decoder with Pillow if it is installed.

    Returns True when HEIC decoding is available.
    """
    registered = False
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        registered = True
    except ImportError:
        LOGGER.debug("pillow-heif is not installed; HEIC thumbnails are unavailable")
    return registered


def thumbnails_video_seek_seconds(duration_seconds: float | None) -> float:
    """Choose how far into a clip the poster frame should be taken from.

    duration_seconds: the clip length, or None when the container omits it.
    Returns an offset in seconds that stays inside even very short clips.
    """
    offset = 0.0
    if duration_seconds is not None and duration_seconds > 0:
        offset = min(
            duration_seconds * VIDEO_SEEK_FRACTION,
            VIDEO_SEEK_MAX_SECONDS,
            duration_seconds / 2,
        )
    return offset


def thumbnails_apply_rotation(image: PillowImage, rotation: int) -> PillowImage:
    """Turn a decoded video frame into its intended display orientation.

    image: the frame exactly as stored in the container.
    rotation: the display rotation FFmpeg reports, in counter-clockwise degrees.
    Returns the rotated image, or the original when no rotation is needed.
    """
    from PIL import Image

    # Pillow's ROTATE_* transposes are counter-clockwise, the same convention
    # FFmpeg uses for the display matrix, so the angle applies as-is.
    transposes = {
        90: Image.Transpose.ROTATE_90,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_270,
    }
    transpose = transposes.get(rotation % 360)
    return image if transpose is None else image.transpose(transpose)


def thumbnails_frame_brightness(image: PillowImage) -> float:
    """Estimate how bright a frame is, cheaply.

    image: the frame to measure.
    Returns the mean luma (0-255) of a 16x16 reduction of the frame.
    """
    from PIL import ImageStat

    reduced = image.convert("L").resize((16, 16))
    return float(ImageStat.Stat(reduced).mean[0])


def thumbnails_video_best_frame(container: Any, stream: Any, first: PillowImage) -> PillowImage:
    """Look a little further ahead when the poster frame is essentially black.

    container: the open PyAV container, positioned at the poster frame.
    stream: the video stream being decoded.
    first: the frame already chosen by the seek.
    Returns the first acceptably bright frame, or the brightest one seen.

    Clips that open on a fade-in or a dark room would otherwise fill the
    gallery grid with black tiles.
    """
    best = first
    best_brightness = thumbnails_frame_brightness(first)
    if best_brightness >= VIDEO_DARK_LUMA:
        return best
    for index, frame in enumerate(container.decode(stream)):
        candidate = frame.to_image()
        brightness = thumbnails_frame_brightness(candidate)
        if brightness > best_brightness:
            best, best_brightness = candidate, brightness
        if brightness >= VIDEO_DARK_LUMA or index >= VIDEO_DARK_SCAN_FRAMES:
            break
    return best


def thumbnails_video_frame_at(container: Any, stream: Any, offset: float) -> Any:
    """Decode forward to the first frame at or after an offset.

    container: the open PyAV container, already seeked.
    stream: the video stream being decoded.
    offset: the wanted position in seconds.
    Returns the chosen frame, or None when the stream yields nothing.

    Seeking only reaches the preceding keyframe, so decoding must continue to
    the target; returning the keyframe itself would hand back the black
    lead-in that many clips start with.
    """
    selected = None
    for index, frame in enumerate(container.decode(stream)):
        selected = frame
        if frame.time is None or frame.time >= offset:
            break
        if index >= VIDEO_MAX_SCAN_FRAMES:
            LOGGER.debug("stopped poster-frame scan after %d frames", index)
            break
    return selected


def thumbnails_extract_video_frame(source_path: Path) -> PillowImage:
    """Decode a single poster frame from a video in display orientation.

    source_path: the archived clip to read (never modified).
    Returns the frame as a Pillow image; raises when the clip cannot be decoded.
    """
    import av

    with av.open(str(source_path)) as container:
        if not container.streams.video:
            raise ValueError("file contains no video stream")
        stream = container.streams.video[0]
        # Frame-level threading keeps HEVC decoding responsive for the GUI grid.
        stream.thread_type = "AUTO"
        time_base = stream.time_base
        duration = None
        if stream.duration is not None and time_base is not None:
            duration = float(stream.duration * time_base)
        offset = thumbnails_video_seek_seconds(duration)
        # Without a time base there is no way to express the seek target, so
        # the poster frame is taken from the start instead.
        if offset > 0 and time_base is not None:
            try:
                container.seek(int(offset / time_base), stream=stream)
            except Exception as error:
                LOGGER.debug("seek failed for %s, decoding from start: %s", source_path, error)
                container.seek(0)
        frame = thumbnails_video_frame_at(container, stream, offset)
        if frame is None and offset > 0:
            # A seek past the last keyframe yields nothing; retry from the start.
            container.seek(0)
            frame = thumbnails_video_frame_at(container, stream, 0.0)
        if frame is None:
            raise ValueError("no decodable video frame found")
        poster = thumbnails_video_best_frame(container, stream, frame.to_image())
        return thumbnails_apply_rotation(poster, int(frame.rotation))


def thumbnails_render_video(source_path: Path, target_path: Path, size: int) -> None:
    """Render a downscaled JPEG poster frame of a video.

    source_path: the archived clip to read (never modified).
    target_path: where the JPEG preview is written atomically.
    size: bounding-box size in pixels for the longest edge.
    Returns None; raises on decode or write failure.
    """
    frame = thumbnails_extract_video_frame(source_path)
    preview = frame.convert("RGB")
    preview.thumbnail((size, size))
    thumbnails_save_atomic(preview, target_path)


def thumbnails_save_atomic(preview: PillowImage, target_path: Path) -> None:
    """Write a preview to the cache so readers never observe a partial file.

    preview: the downscaled RGB image to store.
    target_path: the final cache location.
    Returns None; raises on write failure.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # The GUI renders previews on several threads while the CLI may be running
    # too, so the staging name is unique per writer; a shared one would let two
    # writers interleave into the same partial file.
    staging_path = target_path.with_name(f"{target_path.name}.{os.getpid()}.{uuid4().hex}.part")
    try:
        preview.save(staging_path, format="JPEG", quality=THUMBNAIL_QUALITY)
        staging_path.replace(target_path)
    finally:
        staging_path.unlink(missing_ok=True)


def thumbnails_render(source_path: Path, target_path: Path, size: int) -> None:
    """Render a downscaled JPEG preview of an image or video.

    source_path: the archived original to read (never modified).
    target_path: where the JPEG preview is written atomically.
    size: bounding-box size in pixels for the longest edge.
    Returns None; raises on decode or write failure.
    """
    from PIL import Image

    if thumbnails_is_video(source_path):
        thumbnails_render_video(source_path, target_path, size)
        return
    thumbnails_register_heif()
    with Image.open(source_path) as image:
        preview = image.convert("RGB")
        preview.thumbnail((size, size))
        thumbnails_save_atomic(preview, target_path)


def thumbnails_get(
    paths: ArchivePaths,
    sha256: str,
    source_path: Path,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    refresh: bool = False,
) -> ThumbnailResult:
    """Return a cached thumbnail, generating it on first request.

    paths: resolved archive paths.
    sha256: content hash identifying the asset.
    source_path: the archived original to preview.
    size: bounding-box size in pixels for the longest edge.
    refresh: regenerate even when a cached thumbnail already exists.
    Returns a ``ThumbnailResult``; failures are reported, never raised.
    """
    cache_path = thumbnails_cache_path(paths, sha256, size)
    result = ThumbnailResult(sha256=sha256, path=cache_path, cached=True)
    if refresh or not cache_path.is_file():
        if not source_path.is_file():
            result = ThumbnailResult(sha256, None, False, "source file is missing")
        elif not thumbnails_is_supported(source_path):
            result = ThumbnailResult(sha256, None, False, "unsupported media type")
        else:
            try:
                thumbnails_render(source_path, cache_path, size)
                result = ThumbnailResult(sha256, cache_path, False)
            except Exception as error:
                LOGGER.warning("thumbnail failed for %s: %s", source_path, error)
                result = ThumbnailResult(sha256, None, False, str(error))
    return result


def thumbnails_purge(paths: ArchivePaths, sha256: str) -> int:
    """Delete every cached thumbnail belonging to an asset.

    paths: resolved archive paths.
    sha256: content hash identifying the asset.
    Returns the number of cached files removed.
    """
    removed = 0
    if paths.thumbnails_dir.is_dir():
        for cached in paths.thumbnails_dir.glob(f"{sha256}_*{THUMBNAIL_SUFFIX}"):
            cached.unlink()
            removed += 1
    return removed


def thumbnails_clear_cache(paths: ArchivePaths) -> int:
    """Delete the whole thumbnail cache.

    paths: resolved archive paths.
    Returns the number of cached files removed.
    """
    removed = 0
    if paths.thumbnails_dir.is_dir():
        for cached in paths.thumbnails_dir.glob(f"*{THUMBNAIL_SUFFIX}"):
            cached.unlink()
            removed += 1
    return removed
