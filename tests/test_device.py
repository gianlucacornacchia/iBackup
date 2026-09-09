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
    """Missing-library behavior is tested without importing or probing real USB services."""
    import builtins

    original_import = builtins.__import__

    def missing_dependency(name, *args, **kwargs):
        if name.startswith("pymobiledevice3"):
            raise ImportError("simulated missing dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_dependency)
    device = AfcDevice()
    with pytest.raises(DeviceError, match="pymobiledevice3 is not installed"):
        device.afc_device_connect()
    assert device.loop is None


def test_afc_connector_failure_is_fully_offline(monkeypatch):
    """An injected async connector failure exercises cleanup without USB/network access."""
    import sys
    from types import ModuleType

    calls = []

    async def unavailable_connector(**kwargs):
        calls.append(kwargs)
        raise OSError("simulated connector failure")

    def unused_service(**kwargs):
        pytest.fail("AFC must not start after the connector fails")

    lockdown_module = ModuleType("pymobiledevice3.lockdown")
    afc_module = ModuleType("pymobiledevice3.services.afc")
    lockdown_module.create_using_usbmux = unavailable_connector
    afc_module.AfcService = unused_service
    monkeypatch.setitem(sys.modules, "pymobiledevice3.lockdown", lockdown_module)
    monkeypatch.setitem(sys.modules, "pymobiledevice3.services.afc", afc_module)
    device = AfcDevice(udid="OFFLINE-TEST")
    with pytest.raises(DeviceError, match="no trusted iPhone found"):
        device.afc_device_connect()
    assert calls == [{"serial": "OFFLINE-TEST"}]
    assert device.loop is None
    assert device.lockdown is None
    assert device.afc_client is None


def test_async_afc_stream_is_bounded_and_closes_handle():
    """Modern coroutine APIs share one loop and never buffer a whole device file."""
    from iphone_archive.device.afc_device import READ_CHUNK_SIZE

    class Client:
        def __init__(self):
            self.read_sizes = []
            self.closed_handles = []

        async def stat(self, path):
            return {"st_size": 3 * READ_CHUNK_SIZE, "st_ifmt": "S_IFREG"}

        async def fopen(self, path, mode):
            return 7

        async def fread(self, handle, size):
            self.read_sizes.append(size)
            return b"x" * size

        async def fclose(self, handle):
            self.closed_handles.append(handle)

    device = AfcDevice()
    client = Client()
    device.afc_client = client
    with device.device_open("/DCIM/LARGE.MOV") as stream:
        assert stream.read(2 * READ_CHUNK_SIZE) == b"x" * (2 * READ_CHUNK_SIZE)
        assert stream.read() == b"x" * READ_CHUNK_SIZE
    assert max(client.read_sizes) <= READ_CHUNK_SIZE
    assert client.closed_handles == [7]
    device.device_close()


def test_afc_truncated_read_is_error_and_handle_is_closed():
    """Unexpected EOF must not be mistaken for a successful short import."""

    class Client:
        def stat(self, path):
            return {"st_size": 10, "st_ifmt": "S_IFREG"}

        def fopen(self, path, mode):
            return 9

        def fread(self, handle, size):
            return b""

        def fclose(self, handle):
            self.closed = handle

    device = AfcDevice()
    client = Client()
    device.afc_client = client
    with pytest.raises(DeviceError), device.device_open("/DCIM/A.JPG") as stream:
        stream.read()
    assert client.closed == 9
    device.device_close()


@pytest.mark.parametrize("operation", ["listdir", "stat"])
def test_afc_incomplete_inventory_raises(operation):
    """An inaccessible media subtree is never returned as a complete empty inventory."""

    class Client:
        async def listdir(self, path):
            if operation == "listdir":
                raise OSError("disconnected")
            return ["A.JPG"]

        async def stat(self, path):
            raise OSError("disconnected")

    device = AfcDevice()
    device.afc_client = Client()
    with pytest.raises(DeviceError):
        list(device.device_enumerate())
    device.device_close()


def test_afc_photos_database_populates_albums_and_capture_time(tmp_path, monkeypatch):
    """The real parser receives an accessible snapshot and its metadata reaches items."""
    import io
    import sqlite3

    database_path = tmp_path / "Photos.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT);
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY, ZFILENAME TEXT, ZDATECREATED REAL, ZMOMENT INTEGER
        );
        CREATE TABLE Z_28ASSETS (Z_28ALBUMS INTEGER, Z_3ASSETS INTEGER);
        INSERT INTO ZGENERICALBUM VALUES (1, 'Trip');
        INSERT INTO ZASSET VALUES (10, 'A.JPG', 0, NULL);
        INSERT INTO Z_28ASSETS VALUES (1, 10);
    """)
    connection.commit()
    connection.close()
    payload = database_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    class Client:
        def listdir(self, path):
            return ["A.JPG"]

        def stat(self, path):
            return {"st_ifmt": "S_IFREG", "st_size": 1, "st_mtime": "timestamp"}

    def device_open(path):
        if path.endswith("Photos.sqlite"):
            return io.BytesIO(payload)
        raise DeviceError("no WAL")

    device = AfcDevice()
    device.afc_client = Client()
    device.device_open = device_open
    item = list(device.device_enumerate())[0]
    assert item.album_names == ["Trip"]
    assert item.captured_at == "2001-01-01T00:00:00+00:00"
    assert device.device_album_map() == {"/DCIM/A.JPG": ["Trip"]}
    assert not list((tmp_path / ".ibackup-device-cache").iterdir())
    device.device_close()


def test_afc_delete_is_gated_without_touching_device():
    """Even regular media cannot be deleted through unvalidated raw AFC operations."""

    class Client:
        def stat(self, path):
            pytest.fail("unsupported deletion must not access device metadata")

        def rm_single(self, path):
            pytest.fail("real-device deletion is disabled")

    device = AfcDevice()
    device.afc_client = Client()
    with pytest.raises(DeviceError, match="real iPhone deletion is disabled"):
        device.device_delete("/DCIM/A.JPG")
    device.device_close()


def test_afc_delete_gate_requires_no_dependency_or_connection(monkeypatch):
    """A disconnected wrapper reports unsupported deletion without trying to connect."""
    device = AfcDevice()
    monkeypatch.setattr(
        device, "afc_device_connect", lambda: pytest.fail("deletion must not connect")
    )
    with pytest.raises(DeviceError, match="Photos-library deletion validation"):
        device.device_delete("/DCIM/A.JPG")
    assert device.afc_client is None
    assert device.loop is None


def test_afc_rejects_cross_thread_use():
    """An event loop and USB transport are never silently moved between GUI workers."""
    from concurrent.futures import ThreadPoolExecutor

    device = AfcDevice()
    device.afc_client = object()
    device.afc_device_require_client()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(device.afc_device_require_client)
        with pytest.raises(DeviceError, match="owning worker thread"):
            future.result()
    device.device_close()
