"""Best-effort EXIF metadata extraction from archived photo files.

The phone's ``Photos.sqlite`` gives capture time and GPS, but says nothing
about the camera itself: the lens, aperture, ISO and focal length only exist
in the file's own EXIF block, written by the iPhone at the moment of
capture. This module reads that block from the file the app has already
archived, so no extra device round trip is needed, and the GPS it finds
there also serves as a fallback for photos whose phone-database location
could not be determined (or that were imported from somewhere other than an
iPhone's Photos.sqlite entirely).

Reading is always best-effort: a video, a corrupt file, or a format Pillow
cannot decode must never fail an import, so every failure degrades to "no
metadata" rather than raising.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Standard EXIF/GPS IFD tag numbers (stable across Pillow versions), so no
# extra dependency is needed just to name them.
TAG_MAKE = 271
TAG_MODEL = 272
TAG_EXIF_IFD = 34665
TAG_GPS_IFD = 34853
TAG_FNUMBER = 33437
TAG_ISO = 34855
TAG_FOCAL_LENGTH = 37386
TAG_LENS_MODEL = 42036
GPS_TAG_LAT_REF = 1
GPS_TAG_LAT = 2
GPS_TAG_LON_REF = 3
GPS_TAG_LON = 4

_heif_registered = False


@dataclass(frozen=True)
class ExifMetadata:
    """Camera facts and a GPS fallback read straight from one file's EXIF."""

    camera_model: str | None = None
    lens_model: str | None = None
    iso: int | None = None
    aperture: float | None = None
    focal_length_mm: float | None = None
    latitude: float | None = None
    longitude: float | None = None


def exif_register_heif() -> None:
    """Register the HEIF/HEIC decoder with Pillow if it is installed.

    Returns None. Safe to call repeatedly; registration only happens once.
    """
    global _heif_registered
    if _heif_registered:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        logger.debug("pillow-heif is not installed; HEIC EXIF reading is unavailable")
    _heif_registered = True


def exif_read_metadata(path: Path) -> ExifMetadata:
    """Read camera, lens and GPS facts from one archived photo file.

    path: the archived file to inspect.
    Returns an ``ExifMetadata`` with whatever fields the file actually
    carries; every field is None when the file has no EXIF block, is a
    video, or fails to parse.
    """
    exif_register_heif()
    try:
        from PIL import Image
    except ImportError:
        return ExifMetadata()

    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return ExifMetadata()
            camera_model = exif_combine_make_model(exif.get(TAG_MAKE), exif.get(TAG_MODEL))

            photo_ifd = exif.get_ifd(TAG_EXIF_IFD) if hasattr(exif, "get_ifd") else {}
            lens_model = exif_clean_text(photo_ifd.get(TAG_LENS_MODEL))
            iso = exif_to_int(photo_ifd.get(TAG_ISO))
            aperture = exif_to_float(photo_ifd.get(TAG_FNUMBER))
            focal_length = exif_to_float(photo_ifd.get(TAG_FOCAL_LENGTH))

            gps_ifd = exif.get_ifd(TAG_GPS_IFD) if hasattr(exif, "get_ifd") else {}
            latitude, longitude = exif_parse_gps(gps_ifd)
    except Exception as error:  # noqa: BLE001 - metadata is a bonus, never a reason to fail
        logger.debug("exif read failed for %s: %s", path, error)
        return ExifMetadata()

    return ExifMetadata(
        camera_model=camera_model,
        lens_model=lens_model,
        iso=iso,
        aperture=aperture,
        focal_length_mm=focal_length,
        latitude=latitude,
        longitude=longitude,
    )


def exif_clean_text(value: object) -> str | None:
    """Normalize an EXIF string field, discarding padding and empty values.

    value: the raw EXIF value, which may be bytes, str, or None.
    Returns the trimmed text, or None when nothing meaningful remains.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip().strip("\x00").strip()
    return text or None


def exif_combine_make_model(make: object, model: object) -> str | None:
    """Combine EXIF Make/Model into one display string without duplicating the brand.

    make: the raw EXIF ``Make`` value (e.g. "Apple").
    model: the raw EXIF ``Model`` value (e.g. "iPhone 12").
    Returns "Make Model" unless the model already names the make, or just
    whichever of the two is present.
    """
    make_text = exif_clean_text(make)
    model_text = exif_clean_text(model)
    if not model_text:
        return make_text
    if make_text and not model_text.lower().startswith(make_text.lower()):
        return f"{make_text} {model_text}"
    return model_text


def exif_to_int(value: object) -> int | None:
    """Coerce an EXIF numeric field (possibly a one-item tuple) to an int.

    value: the raw EXIF value.
    Returns the integer, or None when it cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def exif_to_float(value: object) -> float | None:
    """Coerce an EXIF rational field (possibly a one-item tuple) to a float.

    value: the raw EXIF value.
    Returns the value rounded to two decimal places, or None when it cannot
    be parsed.
    """
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    try:
        return round(float(value), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def exif_dms_to_decimal(value: object) -> float | None:
    """Convert an EXIF (degrees, minutes, seconds) GPS triple to decimal degrees.

    value: the raw three-part EXIF rational tuple.
    Returns the decimal-degree value, or None when it cannot be parsed.
    """
    try:
        degrees, minutes, seconds = (float(part) for part in value)  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return None
    return degrees + minutes / 60.0 + seconds / 3600.0


def exif_parse_gps(gps_ifd: object) -> tuple[float | None, float | None]:
    """Extract a (latitude, longitude) pair from an EXIF GPS IFD.

    gps_ifd: the GPS tag dictionary from ``Exif.get_ifd(GPSIFD)``.
    Returns ``(None, None)`` when the file carries no usable GPS tags.
    """
    try:
        get = gps_ifd.get  # type: ignore[attr-defined]
    except AttributeError:
        return None, None
    latitude = exif_dms_to_decimal(get(GPS_TAG_LAT))
    longitude = exif_dms_to_decimal(get(GPS_TAG_LON))
    if latitude is None or longitude is None:
        return None, None
    if exif_clean_text(get(GPS_TAG_LAT_REF)) == "S":
        latitude = -latitude
    if exif_clean_text(get(GPS_TAG_LON_REF)) == "W":
        longitude = -longitude
    return latitude, longitude
