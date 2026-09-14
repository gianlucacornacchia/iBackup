"""Offscreen preview pipeline: caching, coalescing, cancellation and shutdown."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event, get_ident

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QObject, QThread  # noqa: E402

from iphone_archive.browse import thumbnails  # noqa: E402
from iphone_archive.config import ArchivePaths, config_initialize_archive  # noqa: E402
from iphone_archive.gui.previews import (  # noqa: E402
    PreviewCache,
    PreviewEntry,
    PreviewLoader,
    PreviewReply,
    PreviewState,
    previews_check_hash,
    previews_check_relative,
    previews_check_size,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture
def archive(tmp_path):
    """Create an initialized archive with two real photos to preview."""
    root = tmp_path / "archive"
    config_initialize_archive(root)
    paths = ArchivePaths(root)
    album = paths.photos_dir / "Trip"
    album.mkdir(parents=True, exist_ok=True)
    for name, colour in (("IMG_0001.png", "red"), ("IMG_0002.png", "blue")):
        Image.new("RGB", (400, 300), colour).save(album / name)
    return root


@pytest.fixture
def loader(qtbot, archive):
    """Build a loader bound to the sample archive and shut it down afterwards."""
    owner = QObject()
    instance = PreviewLoader(owner, size=64, cache_entries=4, pending_limit=3, worker_count=2)
    instance.previews_set_archive(archive)
    yield instance
    instance.previews_shutdown()
    owner.deleteLater()


def helper_wait_ready(qtbot, loader, sha256, relative_path):
    """Request a preview and block until the loader reports it ready."""
    with qtbot.waitSignal(loader.preview_ready, timeout=15000):
        assert loader.previews_entry(sha256, relative_path).state is PreviewState.PENDING
    return loader.previews_entry(sha256, relative_path)


def test_check_hash_rejects_path_separators():
    """A hash becomes a cache file name, so only plain tokens are accepted."""
    assert previews_check_hash(HASH_A) == HASH_A
    for bad in ("", "../escape", "a/b", "a b", 5):
        with pytest.raises(ValueError):
            previews_check_hash(bad)


def test_check_relative_rejects_escaping_paths():
    """Stored paths must stay inside the archive root on both path flavours."""
    assert previews_check_relative("Photos/Trip/IMG_0001.png")
    for bad in ("", "   ", "/etc/passwd", "C:/Windows/system.ini", "Photos/../../secret"):
        with pytest.raises(ValueError):
            previews_check_relative(bad)


def test_check_size_range():
    """Preview sizes outside the supported range are rejected before scheduling."""
    assert previews_check_size(256) == 256
    for bad in (0, 31, 4096, True, "256"):
        with pytest.raises(ValueError):
            previews_check_size(bad)


def test_cache_evicts_least_recently_used(qtbot):
    """The pixmap cache is bounded and evicts in least-recently-used order."""
    from PySide6.QtGui import QPixmap

    cache = PreviewCache(2)
    first, second, third = QPixmap(1, 1), QPixmap(1, 1), QPixmap(1, 1)
    cache.previews_cache_put((HASH_A, 64), first)
    cache.previews_cache_put((HASH_B, 64), second)
    assert cache.previews_cache_get((HASH_A, 64)) is first
    cache.previews_cache_put(("c" * 64, 64), third)
    assert cache.previews_cache_size() == 2
    assert cache.previews_cache_get((HASH_B, 64)) is None
    assert cache.previews_cache_get((HASH_A, 64)) is first
    with pytest.raises(ValueError):
        PreviewCache(0)


def test_request_renders_then_serves_from_cache(qtbot, loader, archive):
    """The first request renders in the background; later ones hit the cache with no I/O."""
    entry = helper_wait_ready(qtbot, loader, HASH_A, "Photos/Trip/IMG_0001.png")
    assert entry.state is PreviewState.READY
    assert entry.pixmap is not None and not entry.pixmap.isNull()
    assert max(entry.pixmap.width(), entry.pixmap.height()) == 64
    cached = ArchivePaths(archive).thumbnails_dir / f"{HASH_A}_64.jpg"
    assert cached.is_file()
    # A cache hit must not schedule any further background work.
    assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png").pixmap is entry.pixmap
    assert not loader.pending


def test_repeated_requests_are_coalesced(qtbot, loader):
    """Many tiles asking for one key produce exactly one render."""
    rendered = []
    original = thumbnails.thumbnails_get

    def counting_get(*args, **kwargs):
        rendered.append(args[1])
        return original(*args, **kwargs)

    thumbnails.thumbnails_get = counting_get
    try:
        with qtbot.waitSignal(loader.preview_ready, timeout=15000):
            for _ in range(5):
                assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png").state is (
                    PreviewState.PENDING
                )
            assert len(loader.pending) == 1
    finally:
        thumbnails.thumbnails_get = original
    assert rendered == [HASH_A]


def test_missing_source_is_remembered_as_failed(qtbot, loader):
    """A broken file fails once and is not retried on every repaint."""
    with qtbot.waitSignal(loader.preview_failed, timeout=15000) as blocker:
        loader.previews_entry(HASH_B, "Photos/Trip/missing.png")
    assert blocker.args[0] == HASH_B
    entry = loader.previews_entry(HASH_B, "Photos/Trip/missing.png")
    assert entry.state is PreviewState.FAILED
    assert entry.error
    assert not loader.pending
    loader.previews_retry(HASH_B)
    assert loader.previews_entry(HASH_B, "Photos/Trip/missing.png").state is PreviewState.PENDING


def test_scrolled_past_requests_are_cancelled(qtbot, loader):
    """Cancel-on-scroll drops pending renders for tiles that left the viewport."""
    loader.pool.setMaxThreadCount(1)
    blocker = Event()
    original = thumbnails.thumbnails_get
    thumbnails.thumbnails_get = lambda *a, **k: (blocker.wait(10), original(*a, **k))[1]
    try:
        loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png")
        loader.previews_entry(HASH_B, "Photos/Trip/IMG_0002.png")
        assert len(loader.pending) == 2
        assert loader.previews_cancel_stale([HASH_A]) == 1
        assert list(loader.pending) == [(HASH_A, 64)]
    finally:
        blocker.set()
        thumbnails.thumbnails_get = original
        loader.previews_cancel_all()


def test_pending_limit_drops_oldest_requests(qtbot, loader):
    """The outstanding-render bound is enforced by dropping the least recent keys."""
    loader.pool.setMaxThreadCount(1)
    blocker = Event()
    original = thumbnails.thumbnails_get
    thumbnails.thumbnails_get = lambda *a, **k: (blocker.wait(10), original(*a, **k))[1]
    try:
        for index in range(6):
            loader.previews_entry(f"{index:064d}", "Photos/Trip/IMG_0001.png")
        assert len(loader.pending) == loader.pending_limit == 3
        assert [key[0] for key in loader.pending] == [f"{index:064d}" for index in (3, 4, 5)]
    finally:
        blocker.set()
        thumbnails.thumbnails_get = original
        loader.previews_cancel_all()


def test_cancelled_results_are_ignored(qtbot, loader):
    """Results from a previous archive or cancellation round never reach the cache."""
    loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png")
    key = (HASH_A, 64)
    token = loader.pending[key]
    loader.previews_cancel_all()
    loader.previews_finished(PreviewReply(key, token, error="stale"))
    assert key not in loader.failures
    assert loader.cache.previews_cache_get(key) is None


def test_superseded_reply_cannot_fail_its_replacement(qtbot, loader):
    """A reply emitted just before cancellation must not resolve the re-request.

    A tile can scroll out of view, be cancelled, then scroll back in. The
    cancelled render may already have emitted, and if its error were applied to
    the replacement the tile would stay failed forever even though the file
    renders fine.
    """
    loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png")
    key = (HASH_A, 64)
    stale_token = loader.pending[key]
    assert loader.previews_cancel_stale([]) == 1
    with qtbot.waitSignal(loader.preview_ready, timeout=15000):
        assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png").state is (
            PreviewState.PENDING
        )
        assert loader.pending[key] is not stale_token
        loader.previews_finished(PreviewReply(key, stale_token, error="transient I/O error"))
    assert key not in loader.failures
    assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png").state is PreviewState.READY


def test_changing_archive_clears_cache_and_pending(qtbot, loader, tmp_path):
    """Identical hashes resolve to different files per archive, so state is discarded."""
    helper_wait_ready(qtbot, loader, HASH_A, "Photos/Trip/IMG_0001.png")
    assert loader.cache.previews_cache_size() == 1
    other = tmp_path / "other"
    config_initialize_archive(other)
    loader.previews_set_archive(other)
    assert loader.cache.previews_cache_size() == 0
    assert loader.archive_root == other
    loader.previews_set_archive(None)
    assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png").state is PreviewState.FAILED


def test_changing_size_keeps_other_sizes_cached(qtbot, loader):
    """The cache key includes the size, so switching sizes re-renders without clearing."""
    helper_wait_ready(qtbot, loader, HASH_A, "Photos/Trip/IMG_0001.png")
    loader.previews_set_size(128)
    assert loader.cache.previews_cache_get((HASH_A, 64)) is not None
    entry = helper_wait_ready(qtbot, loader, HASH_A, "Photos/Trip/IMG_0001.png")
    assert max(entry.pixmap.width(), entry.pixmap.height()) == 128


def test_rendering_runs_off_the_gui_thread(qtbot, loader):
    """Decoding happens on the pool; only the pixmap conversion is GUI-affine."""
    render_threads = []
    original = thumbnails.thumbnails_get

    def recording_get(*args, **kwargs):
        render_threads.append(get_ident())
        return original(*args, **kwargs)

    thumbnails.thumbnails_get = recording_get
    try:
        helper_wait_ready(qtbot, loader, HASH_A, "Photos/Trip/IMG_0001.png")
    finally:
        thumbnails.thumbnails_get = original
    assert render_threads and get_ident() not in render_threads


def test_loader_rejects_cross_thread_calls(qtbot, loader):
    """Every public loader method is GUI-affine, like the service worker controller."""
    failures = []

    class Caller(QThread):
        def run(self) -> None:
            try:
                loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png")
            except RuntimeError as error:
                failures.append(str(error))

    caller = Caller()
    caller.start()
    assert caller.wait(5000)
    assert failures and "GUI thread" in failures[0]


def test_shutdown_stops_accepting_work(qtbot, loader):
    """After shutdown the pool is idle and no new render is scheduled."""
    assert loader.previews_shutdown() is True
    assert loader.previews_entry(HASH_A, "Photos/Trip/IMG_0001.png") == PreviewEntry(
        PreviewState.FAILED, error="previews stopped"
    )
    assert not loader.pending


def test_concurrent_renders_leave_no_partial_files(tmp_path, archive):
    """Unique staging names keep parallel writers from corrupting one cache entry."""
    from concurrent.futures import ThreadPoolExecutor

    paths = ArchivePaths(archive)
    source = paths.photos_dir / "Trip" / "IMG_0001.png"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: thumbnails.thumbnails_get(paths, HASH_A, source, 64, True),
                range(8),
            )
        )
    assert all(result.path is not None for result in results)
    assert not list(paths.thumbnails_dir.glob("*.part"))
    assert Image.open(paths.thumbnails_dir / f"{HASH_A}_64.jpg").size == (64, 48)


def test_preview_size_survives_an_invalid_settings_file(tmp_path, monkeypatch):
    """A hand-edited thumbnail_size must not stop the window from opening."""
    from iphone_archive.gui.main_window import main_window_preview_size

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text('{"thumbnail_size": 999}', encoding="utf-8")
    monkeypatch.setenv("IBACKUP_CONFIG_DIR", str(config_dir))
    assert main_window_preview_size() == thumbnails.DEFAULT_THUMBNAIL_SIZE


def test_main_window_owns_a_preview_loader(qtbot, archive, monkeypatch):
    """The shell binds previews to the open archive and shuts them down on close."""
    from iphone_archive.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.previews, PreviewLoader)
    assert window.previews.archive_root is None
    monkeypatch.setattr(window.worker, "archive_root", Path(archive))
    window.main_window_sync_previews()
    assert window.previews.archive_root == Path(archive)
    window.close()
    assert window.previews.stopped is True
