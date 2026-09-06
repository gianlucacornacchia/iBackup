"""Tests for per-asset JSON sidecar files."""

from __future__ import annotations

import json

from iphone_archive.catalog.sidecar import (
    SidecarData,
    sidecar_path_for,
    sidecar_read,
    sidecar_write,
)


def make_sidecar() -> SidecarData:
    """Build a representative sidecar payload."""
    return SidecarData(
        sha256="c" * 64,
        size=2048,
        original_name="IMG_0007.HEIC",
        media_type="image",
        source_phone_path="/DCIM/100APPLE/IMG_0007.HEIC",
        captured_at="2026-01-02T03:04:05",
        imported_at="2026-09-07T00:00:00",
        albums=["Family Trip", "Favorites"],
    )


def test_write_creates_expected_file(tmp_path):
    """The sidecar is written at <sha256>.json under the sidecars folder."""
    written = sidecar_write(tmp_path / "sidecars", make_sidecar())
    assert written == sidecar_path_for(tmp_path / "sidecars", "c" * 64)
    assert written.exists()


def test_round_trip_equals_original(tmp_path):
    """Reading back a sidecar returns the same data."""
    original = make_sidecar()
    sidecar_write(tmp_path / "sidecars", original)
    assert sidecar_read(tmp_path / "sidecars", original.sha256) == original


def test_written_json_is_valid_and_has_fields(tmp_path):
    """The file contains valid JSON with the expected keys."""
    written = sidecar_write(tmp_path / "sidecars", make_sidecar())
    raw = json.loads(written.read_text(encoding="utf-8"))
    for key in ("sha256", "size", "original_name", "media_type", "albums"):
        assert key in raw
    assert raw["albums"] == ["Family Trip", "Favorites"]


def test_rewrite_is_stable(tmp_path):
    """Writing the same sidecar twice produces identical bytes and no temp file."""
    first = sidecar_write(tmp_path / "sidecars", make_sidecar()).read_bytes()
    second_path = sidecar_write(tmp_path / "sidecars", make_sidecar())
    assert second_path.read_bytes() == first
    assert list((tmp_path / "sidecars").glob("*.tmp")) == []
