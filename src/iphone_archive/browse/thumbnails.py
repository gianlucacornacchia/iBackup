"""Thumbnail generation and caching for archive browsing.

Neither Qt nor browsers can display HEIC/HEVC natively, so previews are
transcoded to JPEG once and cached under ``.ibackup/thumbnails/`` keyed by the
asset's SHA-256. Originals are only ever read, never modified, which keeps the
append-only guarantee intact. Video thumbnails are not generated; callers get a
``None`` result and should fall back to a placeholder icon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import ArchivePaths

LOGGER = logging.getLogger(__name__)

DEFAULT_THUMBNAIL_SIZE = 256
THUMBNAIL_SUFFIX = ".jpg"
THUMBNAIL_QUALITY = 85

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
)


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


def thumbnails_is_supported(source_path: Path) -> bool:
    """Report whether a file type can be rendered into a thumbnail.

    source_path: the archived original to inspect.
    Returns True for still-image formats Pillow (plus pillow-heif) can decode.
    """
    return source_path.suffix.lower() in IMAGE_EXTENSIONS


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


def thumbnails_render(source_path: Path, target_path: Path, size: int) -> None:
    """Render a downscaled JPEG preview of an image.

    source_path: the archived original to read (never modified).
    target_path: where the JPEG preview is written atomically.
    size: bounding-box size in pixels for the longest edge.
    Returns None; raises on decode or write failure.
    """
    from PIL import Image

    thumbnails_register_heif()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(target_path.name + ".part")
    with Image.open(source_path) as image:
        preview = image.convert("RGB")
        preview.thumbnail((size, size))
        preview.save(staging_path, format="JPEG", quality=THUMBNAIL_QUALITY)
    staging_path.replace(target_path)


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
