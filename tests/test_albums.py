"""Tests for album extraction and album listings."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.core import albums, importer, recycle
from iphone_archive.device.fake_device import FakeDevice


@pytest.fixture
def archive(tmp_path):
    """An initialized archive with an open catalog connection."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def make_photos_db(path, rows):
    """Build a minimal Photos.sqlite-like database for parsing tests."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT);
        CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZFILENAME TEXT, ZMOMENT INTEGER);
        CREATE TABLE Z_28ASSETS (Z_28ALBUMS INTEGER, Z_3ASSETS INTEGER);
        """
    )
    for album_pk, title, asset_pk, file_name in rows:
        connection.execute(
            "INSERT OR IGNORE INTO ZGENERICALBUM(Z_PK, ZTITLE) VALUES (?, ?)",
            (album_pk, title),
        )
        connection.execute(
            "INSERT OR IGNORE INTO ZASSET(Z_PK, ZFILENAME, ZMOMENT) VALUES (?, ?, NULL)",
            (asset_pk, file_name),
        )
        connection.execute(
            "INSERT INTO Z_28ASSETS(Z_28ALBUMS, Z_3ASSETS) VALUES (?, ?)",
            (album_pk, asset_pk),
        )
    connection.commit()
    connection.close()


def make_ios26_photos_db(path, rows, join_ordinal=33):
    """Build an iOS 26-style photo database whose join table ordinal differs.

    path: destination file.
    rows: tuples of (album_pk, title, kind, asset_pk, file_name).
    join_ordinal: the Core Data entity number embedded in the join table name.
    """
    connection = sqlite3.connect(path)
    join_table = f"Z_{join_ordinal}ASSETS"
    album_column = f"Z_{join_ordinal}ALBUMS"
    connection.executescript(
        f"""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER);
        CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZFILENAME TEXT);
        CREATE TABLE "{join_table}" ({album_column} INTEGER, Z_3ASSETS INTEGER);
        """
    )
    for album_pk, title, kind, asset_pk, file_name in rows:
        connection.execute(
            "INSERT OR IGNORE INTO ZGENERICALBUM(Z_PK, ZTITLE, ZKIND) VALUES (?, ?, ?)",
            (album_pk, title, kind),
        )
        connection.execute(
            "INSERT OR IGNORE INTO ZASSET(Z_PK, ZFILENAME) VALUES (?, ?)",
            (asset_pk, file_name),
        )
        connection.execute(
            f'INSERT INTO "{join_table}"({album_column}, Z_3ASSETS) VALUES (?, ?)',
            (album_pk, asset_pk),
        )
    connection.commit()
    connection.close()


def make_photos_db_with_directory(path, rows, join_ordinal=33):
    """Build a Photos.sqlite that includes ZDIRECTORY (modern iOS schema).

    path: destination file.
    rows: tuples of (album_pk, title, kind, asset_pk, directory, file_name).
    """
    connection = sqlite3.connect(path)
    join_table = f"Z_{join_ordinal}ASSETS"
    album_column = f"Z_{join_ordinal}ALBUMS"
    connection.executescript(
        f"""
        CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER);
        CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT);
        CREATE TABLE "{join_table}" ({album_column} INTEGER, Z_3ASSETS INTEGER);
        """
    )
    for album_pk, title, kind, asset_pk, directory, file_name in rows:
        connection.execute(
            "INSERT OR IGNORE INTO ZGENERICALBUM(Z_PK, ZTITLE, ZKIND) VALUES (?, ?, ?)",
            (album_pk, title, kind),
        )
        connection.execute(
            "INSERT OR IGNORE INTO ZASSET(Z_PK, ZDIRECTORY, ZFILENAME) VALUES (?, ?, ?)",
            (asset_pk, directory, file_name),
        )
        connection.execute(
            f'INSERT INTO "{join_table}"({album_column}, Z_3ASSETS) VALUES (?, ?)',
            (album_pk, asset_pk),
        )
    connection.commit()
    connection.close()


def test_parses_album_membership(tmp_path):
    """A well-formed photo database yields file-to-album mapping."""
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db(
        database_path,
        [(1, "Trip", 10, "IMG_0001.HEIC"), (2, "Favorites", 10, "IMG_0001.HEIC")],
    )

    membership = albums.albums_parse_photos_database(database_path)

    assert membership["IMG_0001.HEIC"] == ["Trip", "Favorites"]


def test_album_pages_use_one_query_with_deterministic_ties(archive):
    _, connection = archive
    connection.executemany(
        "INSERT INTO albums(name, safe_name) VALUES (?, 'same')",
        [(f"Album {index}",) for index in range(7)],
    )
    connection.commit()
    queries = []
    connection.set_trace_callback(queries.append)
    page = albums.albums_list(connection, limit=3, offset=2)
    connection.set_trace_callback(None)
    assert len(queries) == 1
    assert [row.name for row in page] == ["Album 2", "Album 3", "Album 4"]
    assert all(row.asset_count == 0 for row in page)
    assert albums.albums_list(connection, offset=5) == albums.albums_list(connection)[5:]
    assert albums.albums_list(connection, limit=0) == []
    for limit, offset in [(-1, 0), (None, -1), (False, 0)]:
        with pytest.raises(ValueError):
            albums.albums_list(connection, limit, offset)


@pytest.mark.parametrize("ordinal", [28, 33, 41])
def test_join_table_ordinal_is_discovered(tmp_path, ordinal):
    """The join table is found whatever entity ordinal the iOS version used.

    Regression test: the ordinal was hardcoded to 28, so a real iPhone running
    iOS 26 (Z_33ASSETS) silently produced no album data at all.
    """
    database_path = tmp_path / "Photos.sqlite"
    make_ios26_photos_db(
        database_path, [(1, "USA 2022", 2, 10, "IMG_0001.HEIC")], join_ordinal=ordinal
    )

    membership = albums.albums_parse_photos_database(database_path)

    assert membership == {"IMG_0001.HEIC": ["USA 2022"]}


def test_non_user_albums_are_ignored(tmp_path):
    """Smart albums and internal bookkeeping albums are not archived as albums."""
    database_path = tmp_path / "Photos.sqlite"
    make_ios26_photos_db(
        database_path,
        [
            (1, "Holiday", 2, 10, "IMG_0001.HEIC"),
            (2, "progress-sync", 3571, 11, "IMG_0002.HEIC"),
            (3, "", 2, 12, "IMG_0003.HEIC"),
        ],
    )

    membership = albums.albums_parse_photos_database(database_path)

    assert membership == {"IMG_0001.HEIC": ["Holiday"]}


def test_zdirectory_keying_disambiguates_duplicate_filenames(tmp_path):
    """When ZDIRECTORY is present the key includes the full path.

    Regression: shared-album copies in PhotoData/PhotoCloudSharingData/ reuse
    the original filename (e.g. IMG_0001.HEIC appears in both DCIM/100APPLE and
    several PhotoCloudSharingData subdirectories).  The old filename-only key
    caused one of the duplicates to win the membership lookup, misassigning some
    photos to wrong albums.
    """
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db_with_directory(
        database_path,
        [
            # Real DCIM photo belonging to "Trip"
            (1, "Trip", 2, 10, "DCIM/100APPLE", "IMG_0001.HEIC"),
            # Cloud-shared copy in a different directory – same filename, different album
            (2, "Shared", 2, 11, "PhotoData/PhotoCloudSharingData/abc/100CLOUD", "IMG_0001.HEIC"),
        ],
    )

    membership = albums.albums_parse_photos_database(database_path)

    # Both paths should be keyed separately by full path
    assert membership["/DCIM/100APPLE/IMG_0001.HEIC"] == ["Trip"]
    assert membership["/PhotoData/PhotoCloudSharingData/abc/100CLOUD/IMG_0001.HEIC"] == ["Shared"]
    # The bare filename must NOT appear as a key (would be ambiguous)
    assert "IMG_0001.HEIC" not in membership


def test_zdirectory_keying_device_enumerate_uses_phone_path(tmp_path):
    """device_enumerate assigns album_names via phone_path, not filename.

    Regression: the old code suppressed album assignment entirely for any item
    whose original_name appeared more than once across the enumerated tree
    (counts[item.original_name] != 1), sending legitimate DCIM photos to
    _Unsorted whenever a shared-album copy reused the same filename.
    """
    from iphone_archive.device.fake_device import FakeDevice

    # Two files with the same filename in different directories
    device = FakeDevice(
        {"/DCIM/100APPLE/IMG_0001.HEIC": b"real", "/DCIM/110APPLE/IMG_0001.HEIC": b"old"},
        album_map={
            "/DCIM/100APPLE/IMG_0001.HEIC": ["Trip"],
            "/DCIM/110APPLE/IMG_0001.HEIC": ["Archive"],
        },
    )
    items = list(device.device_enumerate())
    by_path = {item.phone_path: item for item in items}
    # Each file gets its own correct album assignment
    assert by_path["/DCIM/100APPLE/IMG_0001.HEIC"].album_names == ["Trip"]
    assert by_path["/DCIM/110APPLE/IMG_0001.HEIC"].album_names == ["Archive"]


def test_schema_without_album_tables_returns_empty(tmp_path):
    """An unrecognisable schema degrades to no album data rather than raising."""
    database_path = tmp_path / "Photos.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript("CREATE TABLE ZUNRELATED (Z_PK INTEGER);")
    connection.close()

    assert albums.albums_parse_photos_database(database_path) == {}


def test_legacy_ambiguity_includes_assets_without_albums(tmp_path):
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db(database_path, [(1, "Offloaded trip", 10, "A.JPG")])
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("INSERT INTO ZASSET VALUES (11, 'A.JPG', NULL)")
    assert albums.albums_parse_photos_database(database_path) == {}


@pytest.mark.parametrize("directory", [None, "", "/", "///"])
def test_modern_missing_directory_never_becomes_a_filename_key(tmp_path, directory):
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db_with_directory(database_path, [(1, "Trip", 2, 10, directory, "A.JPG")])
    assert albums.albums_parse_photos_database(database_path) == {}


def test_directory_slashes_are_normalized(tmp_path):
    database_path = tmp_path / "Photos.sqlite"
    make_photos_db_with_directory(database_path, [(1, "Trip", 2, 10, "/DCIM/100APPLE/", "A.JPG")])
    assert albums.albums_parse_photos_database(database_path) == {"/DCIM/100APPLE/A.JPG": ["Trip"]}


def test_missing_database_returns_empty(tmp_path):
    """A missing photo database degrades gracefully to no album data."""
    assert albums.albums_parse_photos_database(tmp_path / "nope.sqlite") == {}


def test_unreadable_database_returns_empty(tmp_path):
    """A corrupt photo database does not raise; assets fall back to _Unsorted."""
    bogus = tmp_path / "Photos.sqlite"
    bogus.write_bytes(b"not a database")
    assert albums.albums_parse_photos_database(bogus) == {}


def test_album_listing_counts_assets(archive):
    """Albums are listed with their archived asset counts."""
    paths, connection = archive
    device = FakeDevice(
        {"/DCIM/A.HEIC": b"a", "/DCIM/B.HEIC": b"b"},
        album_map={"/DCIM/A.HEIC": ["Trip"], "/DCIM/B.HEIC": ["Trip"]},
    )
    importer.importer_run(connection, paths, device)

    listing = albums.albums_list(connection)

    assert len(listing) == 1
    assert listing[0].name == "Trip"
    assert listing[0].asset_count == 2


def test_recycled_assets_excluded_from_counts(archive):
    """Assets moved to Deleted/ stop counting toward their album."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.HEIC": b"a"}, album_map={"/DCIM/A.HEIC": ["Trip"]})
    importer.importer_run(connection, paths, device)
    asset_id = repository.repository_all_asset_files(connection)[0].asset_id

    recycle.recycle_move_to_deleted(connection, paths, [asset_id])

    assert albums.albums_list(connection)[0].asset_count == 0


def test_unsorted_count(archive):
    """Album-less assets are counted separately."""
    paths, connection = archive
    importer.importer_run(connection, paths, FakeDevice({"/DCIM/A.HEIC": b"a"}))
    assert albums.albums_unsorted_count(connection) == 1
