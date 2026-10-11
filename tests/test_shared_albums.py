"""Tests for iCloud Shared Albums: parsing, enumeration, import, listing and CLI."""

from __future__ import annotations

import io
import sqlite3

import pytest
from typer.testing import CliRunner

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.cli import app
from iphone_archive.core import albums, importer, reclaim
from iphone_archive.device.afc_device import AfcDevice
from iphone_archive.device.fake_device import FakeDevice
from iphone_archive.device.interface import DeviceError

SHARED_DIR = "PhotoData/PhotoCloudSharingData/1234/ABCD-GUID/100CLOUD"
SHARED_PATH = f"/{SHARED_DIR}/IMG_0001.JPG"


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def make_photos_db(path, rows, with_kind=True):
    """Build a modern Photos.sqlite with ZDIRECTORY and ZKIND.

    rows: tuples of (album_pk, title, kind, asset_pk, directory, file_name).
    """
    connection = sqlite3.connect(path)
    kind_column = ", ZKIND INTEGER" if with_kind else ""
    connection.executescript(
        f"""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT{kind_column});
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZDATECREATED REAL
        );
        CREATE TABLE Z_33ASSETS (Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER);
        """
    )
    for album_pk, title, kind, asset_pk, directory, file_name in rows:
        if with_kind:
            connection.execute(
                "INSERT OR IGNORE INTO ZGENERICALBUM VALUES (?, ?, ?)", (album_pk, title, kind)
            )
        else:
            connection.execute(
                "INSERT OR IGNORE INTO ZGENERICALBUM VALUES (?, ?)", (album_pk, title)
            )
        connection.execute(
            "INSERT OR IGNORE INTO ZASSET VALUES (?, ?, ?, 0)", (asset_pk, directory, file_name)
        )
        connection.execute("INSERT INTO Z_33ASSETS VALUES (?, ?)", (album_pk, asset_pk))
    connection.commit()
    connection.close()


def test_shared_albums_are_parsed_separately_from_user_albums(tmp_path):
    """ZKIND 1505 albums are shared albums; they never leak into user membership."""
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db(
        database_path,
        [
            (1, "Trip", albums.USER_ALBUM_KIND, 10, "DCIM/100APPLE", "IMG_0001.HEIC"),
            (2, "Family", albums.SHARED_ALBUM_KIND, 11, SHARED_DIR, "IMG_0001.JPG"),
            # A shared-album key outside the sharing cache can never be enumerated.
            (2, "Family", albums.SHARED_ALBUM_KIND, 12, "DCIM/100APPLE", "IMG_0002.HEIC"),
        ],
    )

    assert albums.albums_parse_photos_database(database_path) == {
        "/DCIM/100APPLE/IMG_0001.HEIC": ["Trip"]
    }
    assert albums.albums_parse_shared_albums(database_path) == {SHARED_PATH: ["Family"]}


def test_shared_albums_need_zkind(tmp_path):
    """Without ZKIND no album can be identified as shared, so none is."""
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db(database_path, [(1, "Family", None, 11, SHARED_DIR, "IMG_0001.JPG")], False)

    assert albums.albums_parse_shared_albums(database_path) == {}
    assert albums.albums_parse_photos_database(database_path) == {SHARED_PATH: ["Family"]}


def test_shared_album_parsing_degrades_gracefully(tmp_path):
    """Missing databases and unsupported kinds never raise from the parser."""
    assert albums.albums_parse_shared_albums(tmp_path / "missing.sqlite") == {}
    connection = sqlite3.connect(":memory:")
    with pytest.raises(ValueError):
        albums.albums_membership_query(connection, kind=3)
    connection.close()


def test_is_shared_path():
    assert albums.albums_is_shared_path(SHARED_PATH)
    assert not albums.albums_is_shared_path("/DCIM/100APPLE/IMG_0001.HEIC")
    assert not albums.albums_is_shared_path("/PhotoData/PhotoCloudSharingDataX/a.jpg")


def test_shared_album_imports_into_its_own_folder_and_kind(archive):
    """A shared album never merges with a same-named album of the user's own."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/100APPLE/A.HEIC": b"mine", SHARED_PATH: b"theirs"},
        album_map={"/DCIM/100APPLE/A.HEIC": ["Trip"]},
        shared_album_map={SHARED_PATH: ["Trip"]},
    )

    result = importer.importer_run(connection, paths, device)

    assert result.added_count == 2
    user_dir = paths.photos_dir / "Trip"
    shared_dir = paths.photos_dir / "_Shared Albums" / "Trip"
    assert [entry.read_bytes() for entry in user_dir.iterdir() if entry.is_file()] == [b"mine"]
    assert [entry.read_bytes() for entry in shared_dir.iterdir()] == [b"theirs"]
    listing = {(row.name, row.kind): row for row in albums.albums_list(connection)}
    assert set(listing) == {("Trip", "user"), ("Trip", "shared")}
    assert listing[("Trip", "shared")].safe_name == "_Shared Albums/Trip"
    assert listing[("Trip", "shared")].asset_count == 1
    assert albums.albums_unsorted_count(connection) == 0


def test_reimport_keeps_shared_album_copies_stable(archive):
    """Reconciliation treats shared membership as real membership, not a stale copy."""
    paths, connection = archive
    device = FakeDevice({SHARED_PATH: b"theirs"}, shared_album_map={SHARED_PATH: ["Family"]})
    importer.importer_run(connection, paths, device)
    before = [stored.path for stored in repository.repository_all_asset_files(connection)]

    importer.importer_run(connection, paths, device)

    assert [stored.path for stored in repository.repository_all_asset_files(connection)] == before
    assert before == ["Photos/_Shared Albums/Family/IMG_0001.jpg"]


def test_photo_in_user_and_shared_album_gets_both_copies(archive):
    """User albums come first (the primary copy), shared albums add extra copies."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"both"},
        album_map={"/DCIM/A.HEIC": ["Trip"]},
        shared_album_map={"/DCIM/A.HEIC": ["Family"]},
    )
    importer.importer_run(connection, paths, device)

    stored = sorted(stored.path for stored in repository.repository_all_asset_files(connection))
    assert stored == ["Photos/Trip/A.heic", "Photos/_Shared Albums/Family/A.heic"]


def test_reclaim_never_offers_shared_album_cache_files(archive):
    """Deleting iCloud's shared-album cache frees nothing and would alter the album."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"mine", SHARED_PATH: b"theirs"},
        shared_album_map={SHARED_PATH: ["Family"]},
    )
    importer.importer_run(connection, paths, device)

    candidates = reclaim.reclaim_find_candidates(connection, paths, device)

    assert [candidate.phone_path for candidate in candidates] == ["/DCIM/A.HEIC"]


def test_afc_enumerates_only_shared_album_members(tmp_path, monkeypatch):
    """Real SQLite parsing plus AFC walking of the shared-album cache."""
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db(
        database_path,
        [
            (1, "Family", albums.SHARED_ALBUM_KIND, 11, SHARED_DIR, "IMG_0001.JPG"),
            (1, "Family", albums.SHARED_ALBUM_KIND, 12, SHARED_DIR, "NOT_CACHED.JPG"),
        ],
    )
    payload = database_path.read_bytes()
    monkeypatch.chdir(tmp_path)
    root = albums.SHARED_MEDIA_ROOT
    tree = {
        "/DCIM": [],
        root: ["1234"],
        f"{root}/1234": ["ABCD-GUID"],
        f"{root}/1234/ABCD-GUID": ["100CLOUD", "info.plist"],
        f"/{SHARED_DIR}": ["IMG_0001.JPG", "IMG_0001_THUMB.JPG"],
    }

    class Client:
        def listdir(self, path):
            return tree[path]

        def stat(self, path):
            if path in tree:
                return {"st_ifmt": "S_IFDIR"}
            return {"st_ifmt": "S_IFREG", "st_size": 7}

    def device_open(path):
        if path == "/PhotoData/Photos.sqlite":
            return io.BytesIO(payload)
        raise DeviceError("no such file")

    device = AfcDevice()
    device.afc_client = Client()
    monkeypatch.setattr(device, "device_open", device_open)
    try:
        items = list(device.device_enumerate())
    finally:
        device.device_close()

    assert [(item.phone_path, item.shared_album_names) for item in items] == [
        (SHARED_PATH, ["Family"])
    ]
    assert items[0].album_names == []
    assert items[0].captured_at == "2001-01-01T00:00:00+00:00"


def test_afc_shared_walk_failure_does_not_break_enumeration(monkeypatch, caplog):
    """An unreadable sharing cache drops shared albums, never the user's own media."""
    from iphone_archive.catalog.models import PhoneItem

    mine = PhoneItem(phone_path="/DCIM/A.JPG", original_name="A.JPG", size=1, media_type="image")
    device = AfcDevice()
    monkeypatch.setattr(device, "afc_device_require_client", lambda: object())

    def walk(client, root):
        if root == albums.SHARED_MEDIA_ROOT:
            raise DeviceError("cannot list sharing cache")
        return iter([mine])

    def metadata():
        device.shared_album_membership = {SHARED_PATH: ["Family"]}
        return {}, {}, {}

    monkeypatch.setattr(device, "afc_device_walk", walk)
    monkeypatch.setattr(device, "afc_device_photo_metadata", metadata)

    assert [item.phone_path for item in device.device_enumerate()] == ["/DCIM/A.JPG"]
    assert "shared albums unavailable" in caplog.text


def test_cli_albums_tags_and_filters_shared_albums(tmp_path, monkeypatch):
    """`ibackup albums` tags shared albums; `--shared` lists only them."""
    from iphone_archive.service.app_service import AppService

    runner = CliRunner()
    root = tmp_path / "archive"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.setenv("IBACKUP_ARCHIVE", str(root))
    assert "No shared albums yet." in runner.invoke(app, ["albums", "--shared"]).output

    service = AppService(root)
    service.app_service_open()
    try:
        service.app_service_import(
            FakeDevice(
                {"/DCIM/A.HEIC": b"mine", SHARED_PATH: b"theirs"},
                album_map={"/DCIM/A.HEIC": ["Trip"]},
                shared_album_map={SHARED_PATH: ["Family"]},
            )
        )
    finally:
        service.app_service_close()

    everything = runner.invoke(app, ["albums"]).output
    assert "Trip" in everything and "Family  (shared)" in everything
    only_shared = runner.invoke(app, ["albums", "--shared"]).output
    assert "Family  (shared)" in only_shared and "Trip" not in only_shared
