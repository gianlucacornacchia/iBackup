"""Tests for the device layer: fake source and AFC helpers."""

from __future__ import annotations

import json

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


def test_fake_device_locations_exposed_in_items():
    """FakeDevice attaches latitude/longitude from its ``locations`` mapping."""
    device = FakeDevice(
        {"/DCIM/IMG.HEIC": b"x", "/DCIM/OTHER.HEIC": b"y"},
        locations={"/DCIM/IMG.HEIC": (45.07, 7.69)},
    )
    items = {item.phone_path: item for item in device.device_enumerate()}
    assert (items["/DCIM/IMG.HEIC"].latitude, items["/DCIM/IMG.HEIC"].longitude) == (45.07, 7.69)
    assert items["/DCIM/OTHER.HEIC"].latitude is None
    assert items["/DCIM/OTHER.HEIC"].longitude is None


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


@pytest.mark.parametrize("ambiguous", [False, True])
def test_afc_legacy_photos_metadata_requires_unique_database_filename(
    tmp_path, monkeypatch, ambiguous
):
    """Legacy matching checks unassigned database assets as well as album members."""
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
    if ambiguous:
        connection.execute("INSERT INTO ZASSET VALUES (11, 'A.JPG', 86400, NULL)")
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
    assert item.album_names == ([] if ambiguous else ["Trip"])
    assert item.captured_at == (None if ambiguous else "2001-01-01T00:00:00+00:00")
    assert device.device_album_map() == ({} if ambiguous else {"/DCIM/A.JPG": ["Trip"]})
    assert not list((tmp_path / ".ibackup-device-cache").iterdir())
    device.device_close()


@pytest.mark.parametrize(
    ("paths", "albums", "expected"),
    [
        (
            ["/DCIM/100APPLE/A.JPG", "/DCIM/101APPLE/A.JPG"],
            {"/DCIM/100APPLE/A.JPG": ["Trip"], "/DCIM/101APPLE/A.JPG": ["Archive"]},
            [["Trip"], ["Archive"]],
        ),
        (
            ["/DCIM/100APPLE/A.JPG", "/DCIM/101APPLE/A.JPG"],
            {"/DCIM/100APPLE/A.JPG": ["Trip"]},
            [["Trip"], []],
        ),
        (
            ["/DCIM/100APPLE/A.JPG", "/DCIM/101APPLE/A.JPG"],
            {"A.JPG": ["Trip"]},
            [[], []],
        ),
        (
            ["/DCIM/101APPLE/A.JPG"],
            {"/DCIM/100APPLE/A.JPG": ["Trip"]},
            [[]],
        ),
        (
            ["/DCIM/101APPLE/A.JPG"],
            {"A.JPG": ["Trip"]},
            [["Trip"]],
        ),
        (
            ["/DCIM/102APPLE/A.JPG"],
            {"/DCIM/100APPLE/A.JPG": ["Trip"], "/DCIM/101APPLE/A.JPG": ["Archive"]},
            [[]],
        ),
    ],
)
def test_afc_album_fallback_is_only_for_legacy_bare_keys(monkeypatch, paths, albums, expected):
    from iphone_archive.device.interface import PhoneItem

    items = [
        PhoneItem(phone_path=path, original_name="A.JPG", size=1, media_type="image")
        for path in paths
    ]
    device = AfcDevice()
    monkeypatch.setattr(device, "afc_device_require_client", lambda: object())
    monkeypatch.setattr(device, "afc_device_walk", lambda client, root: iter(items))
    monkeypatch.setattr(
        device, "afc_device_photo_metadata", lambda: (albums, {"A.JPG": "capture-time"}, {})
    )
    result = list(device.device_enumerate())
    assert [item.album_names for item in result] == expected
    assert [item.captured_at for item in result] == [
        "capture-time" if len(paths) == 1 else None
    ] * len(paths)
    assert device.album_cache == {
        path: names for path, names in zip(paths, expected, strict=True) if names
    }


def test_afc_location_fallback_is_only_for_legacy_bare_keys(monkeypatch):
    """A direct phone-path location match is used as-is; a bare filename is only
    used as a fallback when the original name is unique across the inventory."""
    from iphone_archive.device.interface import PhoneItem

    item = PhoneItem(
        phone_path="/DCIM/101APPLE/A.JPG", original_name="A.JPG", size=1, media_type="image"
    )
    device = AfcDevice()
    monkeypatch.setattr(device, "afc_device_require_client", lambda: object())
    monkeypatch.setattr(device, "afc_device_walk", lambda client, root: iter([item]))
    monkeypatch.setattr(
        device,
        "afc_device_photo_metadata",
        lambda: ({}, {}, {"A.JPG": (45.07, 7.69)}),
    )
    result = list(device.device_enumerate())
    assert (result[0].latitude, result[0].longitude) == (45.07, 7.69)


def test_afc_location_direct_match_is_preferred_over_bare_fallback(monkeypatch):
    from iphone_archive.device.interface import PhoneItem

    item = PhoneItem(
        phone_path="/DCIM/101APPLE/A.JPG", original_name="A.JPG", size=1, media_type="image"
    )
    device = AfcDevice()
    monkeypatch.setattr(device, "afc_device_require_client", lambda: object())
    monkeypatch.setattr(device, "afc_device_walk", lambda client, root: iter([item]))
    monkeypatch.setattr(
        device,
        "afc_device_photo_metadata",
        lambda: (
            {},
            {},
            {"/DCIM/101APPLE/A.JPG": (48.85, 2.35), "A.JPG": (45.07, 7.69)},
        ),
    )
    result = list(device.device_enumerate())
    assert (result[0].latitude, result[0].longitude) == (48.85, 2.35)


def test_offloaded_member_cannot_label_unassigned_local_photo(tmp_path, monkeypatch, caplog):
    """Exercise actual SQLite parsing, AFC enumeration and archive placement."""
    import io
    import sqlite3

    from iphone_archive.service.app_service import AppService

    database_path = tmp_path / "Photos.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER);
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZDATECREATED REAL
        );
        CREATE TABLE Z_33ASSETS (Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER);
        INSERT INTO ZGENERICALBUM VALUES (1, 'Offloaded trip', 2), (2, 'Local trip', 2);
        INSERT INTO ZASSET VALUES
            (1, 'DCIM/100APPLE', 'A.JPG', 0),
            (2, 'DCIM/101APPLE', 'A.JPG', 86400),
            (3, 'DCIM/101APPLE', 'B.JPG', 172800),
            (4, 'DCIM/100APPLE', 'B.JPG', 0);
        INSERT INTO Z_33ASSETS VALUES (1, 1), (2, 3);
    """)
    connection.commit()
    connection.close()
    payload = database_path.read_bytes()
    monkeypatch.chdir(tmp_path)
    media = {"/DCIM/101APPLE/A.JPG": b"unassigned", "/DCIM/101APPLE/B.JPG": b"assigned"}

    class Client:
        def listdir(self, path):
            return ["101APPLE"] if path == "/DCIM" else ["A.JPG", "B.JPG"]

        def stat(self, path):
            if path == "/DCIM/101APPLE":
                return {"st_ifmt": "S_IFDIR"}
            return {"st_ifmt": "S_IFREG", "st_size": len(media[path])}

    def device_open(path):
        if path == "/PhotoData/Photos.sqlite":
            return io.BytesIO(payload)
        if path.endswith("-wal"):
            raise DeviceError("no WAL")
        return io.BytesIO(media[path])

    device = AfcDevice()
    device.afc_client = Client()
    monkeypatch.setattr(device, "device_open", device_open)
    service = AppService(tmp_path / "archive")
    try:
        items = list(device.device_enumerate())
        assert [item.album_names for item in items] == [[], ["Local trip"]]
        assert [item.captured_at for item in items] == [
            "2001-01-02T00:00:00+00:00",
            "2001-01-03T00:00:00+00:00",
        ]
        assert "1 album media paths across 1 albums" in caplog.text
        assert "No filename-based substitutions" in caplog.text
        paths = service.app_service_initialize()
        result = service.app_service_import(device)
        assert (result.added_count, result.error_count) == (2, 0)
        assert {p.name for p in paths.photos_dir.iterdir()} == {"_Unsorted", "Local trip"}
        assert [p.read_bytes() for p in (paths.photos_dir / "Local trip").iterdir()] == [
            b"assigned"
        ]
        assert service.app_service_verify().passed
    finally:
        service.app_service_close()
        device.device_close()
    assert not list((tmp_path / ".ibackup-device-cache").iterdir())


def test_offloaded_photo_falls_back_to_cached_thumbnail_preview(tmp_path, monkeypatch, caplog):
    """An offloaded album member with no USB original is imported as a low-res preview.

    iOS keeps a cached JPEG thumbnail under ``/PhotoData/Thumbnails`` for every
    asset, including ones whose full-resolution original has been offloaded by
    "Optimize iPhone Storage". That cache mirrors the DCIM layout, so this proves
    the adapter can read it, label it clearly, and still place it in its album.
    """
    import io
    import sqlite3

    from iphone_archive.service.app_service import AppService

    database_path = tmp_path / "Photos.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER);
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZDATECREATED REAL
        );
        CREATE TABLE Z_33ASSETS (Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER);
        INSERT INTO ZGENERICALBUM VALUES (1, 'Sardegna', 2);
        INSERT INTO ZASSET VALUES (1, 'DCIM/100APPLE', 'MISSING.JPG', 0);
        INSERT INTO Z_33ASSETS VALUES (1, 1);
    """)
    connection.commit()
    connection.close()
    payload = database_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    thumb_dir = "/PhotoData/Thumbnails/V2/DCIM/100APPLE/MISSING.JPG"
    thumb_file = f"{thumb_dir}/5005.JPG"
    thumb_bytes = b"thumb-bytes"

    class Client:
        def listdir(self, path):
            if path == "/DCIM":
                return ["100APPLE"]
            if path == "/DCIM/100APPLE":
                return []
            if path == thumb_dir:
                return ["5005.JPG"]
            raise OSError(f"unexpected listdir {path}")

        def stat(self, path):
            if path == "/DCIM/100APPLE":
                return {"st_ifmt": "S_IFDIR"}
            if path == thumb_file:
                return {"st_ifmt": "S_IFREG", "st_size": len(thumb_bytes)}
            raise OSError(f"unexpected stat {path}")

    def device_open(path):
        if path == "/PhotoData/Photos.sqlite":
            return io.BytesIO(payload)
        if path.endswith("-wal"):
            raise DeviceError("no WAL")
        if path == thumb_file:
            return io.BytesIO(thumb_bytes)
        raise DeviceError(f"unexpected open {path}")

    device = AfcDevice()
    device.afc_client = Client()
    monkeypatch.setattr(device, "device_open", device_open)
    service = AppService(tmp_path / "archive")
    try:
        items = list(device.device_enumerate())
        assert len(items) == 1
        preview = items[0]
        assert preview.is_offloaded_preview is True
        assert preview.phone_path == thumb_file
        assert preview.size == len(thumb_bytes)
        assert preview.original_name == "MISSING (offloaded preview).JPG"
        assert preview.album_names == ["Sardegna"]
        assert "1 of them have a cached low-resolution preview" in caplog.text
        assert device.album_cache == {thumb_file: ["Sardegna"]}

        paths = service.app_service_initialize()
        result = service.app_service_import(device)
        assert (result.added_count, result.error_count) == (1, 0)
        album_files = list((paths.photos_dir / "Sardegna").iterdir())
        assert [p.read_bytes() for p in album_files] == [thumb_bytes]
        assert album_files[0].name == "MISSING (offloaded preview).jpg"
        assert service.app_service_verify().passed
    finally:
        service.app_service_close()
        device.device_close()
    # The resolved thumbnail path is cached on disk so a later import of the
    # same still-offloaded photo can skip the AFC listdir/stat round-trips.
    cache_dir = tmp_path / ".ibackup-device-cache"
    assert [p.name for p in cache_dir.iterdir()] == ["offloaded-preview-cache.json"]
    cached = json.loads((cache_dir / "offloaded-preview-cache.json").read_text())
    assert cached["unknown"]["/DCIM/100APPLE/MISSING.JPG"]["path"] == thumb_file
    assert cached["unknown"]["/DCIM/100APPLE/MISSING.JPG"]["size"] == len(thumb_bytes)


def test_offloaded_preview_lookup_reuses_cache_without_repeating_afc_calls(tmp_path, monkeypatch):
    """A second lookup for an already-resolved offloaded path makes no AFC calls."""
    monkeypatch.chdir(tmp_path)
    thumb_dir = "/PhotoData/Thumbnails/V2/DCIM/100APPLE/MISSING.JPG"
    thumb_file = f"{thumb_dir}/5005.JPG"

    class Client:
        def __init__(self):
            self.calls = 0

        def listdir(self, path):
            self.calls += 1
            if path == thumb_dir:
                return ["5005.JPG"]
            raise OSError(f"unexpected listdir {path}")

        def stat(self, path):
            self.calls += 1
            if path == thumb_file:
                return {"st_ifmt": "S_IFREG", "st_size": 11}
            raise OSError(f"unexpected stat {path}")

    class ExhaustedClient:
        def listdir(self, path):
            raise AssertionError(f"unexpected AFC listdir call for {path}: should be cached")

        def stat(self, path):
            raise AssertionError(f"unexpected AFC stat call for {path}: should be cached")

    client = Client()
    device = AfcDevice()
    device.afc_client = client
    preview = device.afc_device_offloaded_preview(
        client, "/DCIM/100APPLE/MISSING.JPG", "phone-udid"
    )
    assert preview is not None
    assert preview.phone_path == thumb_file
    assert client.calls == 2
    device.afc_device_save_preview_cache()
    device.device_close()

    # A fresh AfcDevice instance (as every import run constructs) must still
    # find the on-disk cache and never touch AFC for the same path again.
    reloaded = AfcDevice()
    reloaded.afc_client = ExhaustedClient()
    second = reloaded.afc_device_offloaded_preview(
        ExhaustedClient(), "/DCIM/100APPLE/MISSING.JPG", "phone-udid"
    )
    assert second is not None
    assert second.phone_path == thumb_file
    assert second.size == 11
    reloaded.device_close()


def test_offloaded_preview_lookup_never_raises_when_no_cache_exists():
    """A path with neither a USB original nor a cached thumbnail is simply skipped."""

    class Client:
        def listdir(self, path):
            raise OSError("no such cached thumbnail")

    device = AfcDevice()
    client = Client()
    assert device.afc_device_offloaded_preview(client, "/DCIM/100APPLE/GONE.JPG") is None
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
