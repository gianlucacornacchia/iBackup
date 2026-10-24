"""Atomic rename/replace retries for transient Windows sharing violations."""

from __future__ import annotations

import pytest

from iphone_archive.core import atomic


@pytest.fixture
def no_sleep(monkeypatch):
    """Record retry delays instead of sleeping."""
    delays = []
    monkeypatch.setattr(atomic.time, "sleep", delays.append)
    monkeypatch.setattr(atomic, "RETRY_ON_PERMISSION_ERROR", True)
    return delays


def flaky(failures, error):
    """A callable that raises ``error`` ``failures`` times, then succeeds."""
    calls = []

    def operation():
        calls.append(None)
        if len(calls) <= failures:
            raise error

    return operation, calls


def test_transient_permission_error_is_retried(no_sleep):
    """A file briefly held by a scanner is replaced after a short wait."""
    operation, calls = flaky(2, PermissionError(13, "Access is denied"))
    atomic.atomic_retry(operation)
    assert len(calls) == 3
    assert no_sleep == list(atomic.RETRY_DELAYS[:2])


def test_persistent_permission_error_is_raised(no_sleep):
    """A real permission problem still surfaces after the bounded retries."""
    operation, calls = flaky(100, PermissionError(13, "Access is denied"))
    with pytest.raises(PermissionError):
        atomic.atomic_retry(operation)
    assert len(calls) == len(atomic.RETRY_DELAYS) + 1


def test_existing_destination_is_never_retried(no_sleep):
    """No-clobber publication fails at once on an existing name."""
    operation, calls = flaky(1, FileExistsError(17, "exists"))
    with pytest.raises(FileExistsError):
        atomic.atomic_retry(operation)
    assert len(calls) == 1
    assert no_sleep == []


def test_permission_error_not_retried_off_windows(no_sleep, monkeypatch):
    """Outside Windows a PermissionError is a real error, not a sharing hold."""
    monkeypatch.setattr(atomic, "RETRY_ON_PERMISSION_ERROR", False)
    operation, calls = flaky(1, PermissionError(13, "denied"))
    with pytest.raises(PermissionError):
        atomic.atomic_retry(operation)
    assert len(calls) == 1


def test_replace_and_rename_move_real_files(tmp_path):
    """Replace overwrites; rename refuses an existing name."""
    source = tmp_path / "a.tmp"
    target = tmp_path / "a.json"
    source.write_text("new")
    target.write_text("old")
    atomic.atomic_replace(source, target)
    assert target.read_text() == "new" and not source.exists()

    staged = tmp_path / "b.tmp"
    staged.write_text("b")
    atomic.atomic_rename(staged, tmp_path / "b.json")
    assert (tmp_path / "b.json").read_text() == "b"
