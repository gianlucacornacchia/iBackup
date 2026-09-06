"""Tests for the device layer: fake source and AFC helpers."""

from __future__ import annotations

import pytest

from iphone_archive.device.afc_device import AfcDevice, afc_device_classify
from iphone_archive.device.fake_device import FakeDevice, fake_device_media_type
from iphone_archive.device.interface import DeviceError, MediaSource


def test_fake_device_satisfies_protocol():
    """The fake source implements the MediaSource contract."""
    assert isinstance(FakeDevice(), MediaSource)


def test_enumerate_reports_metadata():
    """Enumeration yields sizes and names without reading content."""
    device = FakeDevice({"/DCIM/IMG_0001.HEIC": b"abc", "/DCIM/VID_0002.MOV": b"defgh"})
    items = list(device.device_enumerate())
    assert [item.original_name for item in items] == ["IMG_0001.HEIC", "VID_0002.MOV"]
    assert [item.size for item in items] == [3, 5]
    assert [item.media_type for item in items] == ["image", "video"]


def test_open_streams_content():
    """Opening an item returns its exact bytes."""
    device = FakeDevice({"/DCIM/IMG.HEIC": b"payload"})
    with device.device_open("/DCIM/IMG.HEIC") as stream:
        assert stream.read() == b"payload"


def test_open_missing_raises():
    """Reading an unknown path raises a device error."""
    with pytest.raises(DeviceError):
        FakeDevice().device_open("/DCIM/missing.HEIC")


def test_delete_removes_and_records():
    """Deletion removes the item and is recorded for assertions."""
    device = FakeDevice({"/DCIM/IMG.HEIC": b"x"})
    device.device_delete("/DCIM/IMG.HEIC")
    assert device.deleted_paths == ["/DCIM/IMG.HEIC"]
    assert list(device.device_enumerate()) == []


def test_delete_missing_raises():
    """Deleting an unknown path raises a device error."""
    with pytest.raises(DeviceError):
        FakeDevice().device_delete("/DCIM/missing.HEIC")


def test_album_map_exposed_in_items():
    """Album membership is attached to enumerated items."""
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x"}, album_map={"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}
    )
    item = next(iter(device.device_enumerate()))
    assert item.album_names == ["Trip", "Favorites"]
    assert device.device_album_map() == {"/DCIM/IMG.HEIC": ["Trip", "Favorites"]}


def test_media_type_classification():
    """Extensions map to the expected media types."""
    assert fake_device_media_type("a.MOV") == "video"
    assert fake_device_media_type("a.HEIC") == "image"


def test_afc_classify_extensions():
    """AFC classification accepts media and rejects other files."""
    assert afc_device_classify("IMG_0001.HEIC") == "image"
    assert afc_device_classify("VID_0002.mov") == "video"
    assert afc_device_classify("notes.txt") is None
    assert afc_device_classify("noextension") is None


def test_afc_connect_without_library_raises(monkeypatch):
    """A clear device error is raised when the phone cannot be reached."""
    device = AfcDevice()
    with pytest.raises(DeviceError):
        device.afc_device_connect()
