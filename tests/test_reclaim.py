"""Regression coverage for content-verified and explicitly selected phone reclamation."""

import pytest

from iphone_archive import config
from iphone_archive.catalog import database, repository
from iphone_archive.core import importer, reclaim
from iphone_archive.device.fake_device import FakeDevice


@pytest.fixture
def archive(tmp_path):
    """Create a local archive without any real device operations."""
    paths = config.config_initialize_archive(tmp_path / "archive")
    connection = database.database_connect(paths.catalog_path)
    database.database_initialize(connection)
    yield paths, connection
    connection.close()


def test_reclaim_selected_subset_only(archive):
    """Selected content never expands into deletion of every archived phone item."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"a", "/DCIM/B.JPG": b"b"})
    importer.importer_run(connection, paths, device)
    selected = repository.repository_all_asset_files(connection)[0].asset_id
    result = reclaim.reclaim_run(connection, paths, device, confirmed=True, asset_ids=[selected])
    assert result.deleted_count == 1
    assert device.deleted_paths == ["/DCIM/A.JPG"]


def test_reclaim_empty_selection_deletes_nothing(archive):
    """An explicitly empty selection means no targets, not all targets."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"a"})
    importer.importer_run(connection, paths, device)
    result = reclaim.reclaim_run(connection, paths, device, confirmed=True, asset_ids=[])
    assert result.deleted_count == 0
    assert device.deleted_paths == []


def test_reclaim_rejects_same_size_replacement_even_with_same_metadata(archive):
    """Fresh phone hashing defeats stale identities, including preserved mtimes."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"old"})
    device.metadata["/DCIM/A.JPG"] = {"modified_at": "unchanged"}
    importer.importer_run(connection, paths, device)
    device.items["/DCIM/A.JPG"] = b"new"
    assert reclaim.reclaim_run(connection, paths, device, confirmed=True).deleted_count == 0
    assert device.deleted_paths == []


def test_reclaim_rechecks_content_immediately_before_delete(archive, monkeypatch):
    """Changing bytes after candidate preparation invalidates destructive confirmation."""
    paths, connection = archive
    device = FakeDevice({"/DCIM/A.JPG": b"old"})
    importer.importer_run(connection, paths, device)
    original = reclaim.reclaim_find_candidates

    def replace_after(*args, **kwargs):
        candidates = original(*args, **kwargs)
        device.items["/DCIM/A.JPG"] = b"new"
        return candidates

    monkeypatch.setattr(reclaim, "reclaim_find_candidates", replace_after)
    result = reclaim.reclaim_run(connection, paths, device, confirmed=True)
    assert result.deleted_count == 0
    assert len(result.errors) == 1
    assert device.deleted_paths == []
