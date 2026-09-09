"""Cross-thread progress/cancellation and bounded history contracts."""

from concurrent.futures import ThreadPoolExecutor

from iphone_archive.service.progress import ProgressHandle


def test_progress_history_is_bounded_and_snapshots_are_isolated():
    """A long operation cannot retain unbounded per-file event history."""
    handle = ProgressHandle(history_limit=2)
    for index in range(5):
        handle.progress_report("import", index, 5)
    snapshot = handle.events
    assert [event.current for event in snapshot] == [3, 4]
    snapshot.clear()
    assert len(handle.events) == 2


def test_cancellation_can_be_requested_from_another_thread():
    """The UI can cancel a worker without touching worker-owned SQLite state."""
    handle = ProgressHandle()
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(handle.progress_cancel).result()
    assert handle.progress_is_cancelled()
