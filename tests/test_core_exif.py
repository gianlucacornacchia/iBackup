"""Tests for best-effort EXIF metadata extraction from archived photo files."""

from __future__ import annotations

import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402
from PIL.ExifTags import GPSTAGS  # noqa: E402

from iphone_archive.core import exif  # noqa: E402


def _gps_ifd_tag_id(name: str) -> int:
    for tag_id, tag_name in GPSTAGS.items():
        if tag_name == name:
            return tag_id
    raise AssertionError(f"unknown GPS tag: {name}")


def make_jpeg_with_exif(
    *,
    make: str | None = "Apple",
    model: str | None = "iPhone 12",
    lens_model: str | None = "iPhone 12 back camera 4.2mm f/1.6",
    iso: int | None = 64,
    aperture: float | None = 1.6,
    focal_length: float | None = 4.2,
    latitude: float | None = None,
    longitude: float | None = None,
) -> bytes:
    """Build an in-memory JPEG carrying the given EXIF facts."""
    image = Image.new("RGB", (4, 4), color="red")
    exif_data = Image.Exif()
    if make is not None:
        exif_data[exif.TAG_MAKE] = make
    if model is not None:
        exif_data[exif.TAG_MODEL] = model

    photo_ifd = exif_data.get_ifd(exif.TAG_EXIF_IFD)
    if lens_model is not None:
        photo_ifd[exif.TAG_LENS_MODEL] = lens_model
    if iso is not None:
        photo_ifd[exif.TAG_ISO] = iso
    if aperture is not None:
        photo_ifd[exif.TAG_FNUMBER] = aperture
    if focal_length is not None:
        photo_ifd[exif.TAG_FOCAL_LENGTH] = focal_length

    if latitude is not None and longitude is not None:
        gps_ifd = {}
        gps_ifd[_gps_ifd_tag_id("GPSLatitudeRef")] = "N" if latitude >= 0 else "S"
        gps_ifd[_gps_ifd_tag_id("GPSLatitude")] = exif_decimal_to_dms(abs(latitude))
        gps_ifd[_gps_ifd_tag_id("GPSLongitudeRef")] = "E" if longitude >= 0 else "W"
        gps_ifd[_gps_ifd_tag_id("GPSLongitude")] = exif_decimal_to_dms(abs(longitude))
        exif_data[exif.TAG_GPS_IFD] = gps_ifd

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif_data)
    return buffer.getvalue()


def exif_decimal_to_dms(value: float) -> tuple[float, float, float]:
    """Convert decimal degrees to an EXIF (degrees, minutes, seconds) triple."""
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return (degrees, minutes, seconds)


def test_reads_camera_lens_and_exposure_facts(tmp_path):
    """Make/Model, lens, ISO, aperture and focal length are all extracted."""
    path = tmp_path / "photo.jpg"
    path.write_bytes(make_jpeg_with_exif())

    metadata = exif.exif_read_metadata(path)

    assert metadata.camera_model == "Apple iPhone 12"
    assert metadata.lens_model == "iPhone 12 back camera 4.2mm f/1.6"
    assert metadata.iso == 64
    assert metadata.aperture == 1.6
    assert metadata.focal_length_mm == 4.2


def test_reads_gps_coordinates_with_sign_from_ref(tmp_path):
    """Southern/western hemisphere refs flip the sign of the decimal coordinate."""
    path = tmp_path / "photo.jpg"
    path.write_bytes(make_jpeg_with_exif(latitude=-45.07, longitude=-7.69))

    metadata = exif.exif_read_metadata(path)

    assert metadata.latitude == pytest.approx(-45.07, abs=0.01)
    assert metadata.longitude == pytest.approx(-7.69, abs=0.01)


def test_missing_exif_degrades_to_all_none(tmp_path):
    """A file with no EXIF block yields an all-None result instead of raising."""
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (4, 4), color="blue").save(path, format="JPEG")

    metadata = exif.exif_read_metadata(path)

    assert metadata == exif.ExifMetadata()


def test_corrupt_file_degrades_to_all_none_without_raising(tmp_path):
    """A file that cannot be decoded as an image never fails the import."""
    path = tmp_path / "not-a-photo.jpg"
    path.write_bytes(b"this is not a jpeg")

    metadata = exif.exif_read_metadata(path)

    assert metadata == exif.ExifMetadata()


def test_model_already_naming_make_is_not_duplicated():
    """Combining Make/Model avoids repeating the brand when the model already has it."""
    assert exif.exif_combine_make_model("Apple", "Apple iPhone 12") == "Apple iPhone 12"
    assert exif.exif_combine_make_model("Apple", "iPhone 12") == "Apple iPhone 12"
    assert exif.exif_combine_make_model(None, "iPhone 12") == "iPhone 12"
    assert exif.exif_combine_make_model("Apple", None) == "Apple"


def test_numeric_fields_unwrap_one_item_tuples():
    """Some cameras report single numeric values wrapped in a one-item tuple."""
    assert exif.exif_to_int((64,)) == 64
    assert exif.exif_to_float((1.6,)) == 1.6
    assert exif.exif_to_int(None) is None
    assert exif.exif_to_float("not-a-number") is None
