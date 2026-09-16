"""Offscreen preferences: the six panels, their service calls and their effects.

These tests drive the real dialog against the real settings store in ``tmp_path``
(the autouse fixture redirects ``IBACKUP_CONFIG_DIR``), so a "saved" assertion
means the file on disk really changed.

Two things are checked far harder than the rest, because they are the ones a
preference must never be able to do: no panel may weaken a confirmation, and no
preference may open, create or modify an archive. Reopen-on-startup reopens only
a folder that is already an archive, and the settings operations run with no
archive open at all - against a service whose root is a sentinel that cannot be
one.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402

from iphone_archive.gui import main_window as main_window_module  # noqa: E402
from iphone_archive.gui.main_window import (  # noqa: E402
    MainWindow,
    main_window_preferences,
    main_window_preview_size,
)
from iphone_archive.gui.settings_dialog import (  # noqa: E402
    RESET_CONFIRM,
    RESET_PROMPT,
    SETTINGS_OPERATIONS,
    SettingsDialog,
    settings_dialog_index,
    settings_dialog_open_location,
)
from iphone_archive.gui.theme import ThemeController  # noqa: E402
from iphone_archive.gui.worker import WorkerController  # noqa: E402
from iphone_archive.service.app_service import (  # noqa: E402
    ARCHIVE_FREE_OPERATIONS,
    AppService,
    app_service_preferences,
)
from iphone_archive.settings import (  # noqa: E402
    DELETED_ACTION_PURGE,
    DELETED_ACTION_RECYCLE,
    Settings,
    settings_load,
    settings_path,
    settings_save,
)


@pytest.fixture
def window(qapp, qtbot):
    """Build a real window and shut its worker down afterwards."""
    created = []

    def create():
        main = MainWindow()
        qtbot.addWidget(main)
        main.show()
        created.append(main)
        return main

    yield create
    for main in created:
        main.worker.worker_shutdown()
        assert main.worker.worker_wait(5000)
        main.previews.previews_shutdown()
        main.viewer_previews.previews_shutdown()
        qapp.processEvents()
        main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def helper_open_settings(main, qtbot):
    """Open the settings dialog through the navigation pane and wait for it.

    main: the window under test.
    qtbot: the pytest-qt bot.
    Returns the dialog, which the window opens only once the worker has answered.
    """
    main.shell.navigation.navigation_settings.emit()
    qtbot.waitUntil(lambda: main.settings_dialog is not None, timeout=15000)
    return main.settings_dialog


def helper_select(box, value):
    """Point a labelled combo box at a stored value.

    box: the combo box to change.
    value: the stored value to select.
    Returns None.
    """
    for row in range(box.count()):
        if box.itemData(row) == value:
            box.setCurrentIndex(row)
            return
    raise AssertionError(f"{value!r} is not offered by the combo box")


def test_the_panels_show_what_is_stored_and_return_what_was_edited(qtbot):
    """The dialog is an editor over a detached copy, not a second settings store."""
    stored = Settings(
        default_archive="/archives/main",
        reopen_last_archive=False,
        recent_archives=["/archives/main", "/archives/old"],
        album_link_mode="hardlink",
        scan_phone_after_import=False,
        thumbnail_size=512,
        default_deleted_action=DELETED_ACTION_PURGE,
        log_level="DEBUG",
        theme="dark",
    )
    dialog = SettingsDialog(stored, settings_path())
    qtbot.addWidget(dialog)

    assert dialog.panels.count() == 6
    assert dialog.category_list.count() == 6
    assert dialog.archive_edit.text() == "/archives/main"
    assert dialog.reopen_box.isChecked() is False
    assert [
        dialog.recent_list.item(row).text() for row in range(dialog.recent_list.count())
    ] == stored.recent_archives
    assert dialog.link_mode_box.currentData() == "hardlink"
    assert dialog.scan_box.isChecked() is False
    assert dialog.size_box.currentData() == "512"
    assert dialog.deleted_action_box.currentData() == DELETED_ACTION_PURGE
    assert dialog.log_level_box.currentData() == "DEBUG"
    assert dialog.theme_box.currentData() == "dark"
    assert str(settings_path()) in dialog.path_label.text()

    dialog.archive_edit.setText("  /archives/other  ")
    dialog.reopen_box.setChecked(True)
    helper_select(dialog.size_box, "128")
    helper_select(dialog.theme_box, "light")
    edited = dialog.settings_dialog_values()
    assert edited.default_archive == "/archives/other"
    assert edited.reopen_last_archive is True
    assert edited.thumbnail_size == 128
    assert edited.theme == "light"
    # The service maintains the recent list; the dialog only displays it.
    assert edited.recent_archives == stored.recent_archives

    dialog.archive_edit.setText("   ")
    assert dialog.settings_dialog_values().default_archive is None
    assert settings_dialog_index((("a", "A"), ("b", "B")), "missing") == 0


def test_no_panel_can_weaken_a_confirmation(qtbot):
    """Preferences may add friction; they may never remove it."""
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog.confirm_box.isChecked() and not dialog.confirm_box.isEnabled()
    assert dialog.dry_run_box.isChecked() and not dialog.dry_run_box.isEnabled()
    # Even a forced widget state cannot travel: the value is not read back.
    dialog.confirm_box.setChecked(False)
    dialog.dry_run_box.setChecked(False)
    assert dialog.settings_dialog_values().confirm_word_required is True


def test_saving_validates_before_anything_leaves_the_dialog(qtbot):
    """An invalid value is refused where it was typed, not after the dialog closed."""
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    requests = []
    dialog.settings_requested.connect(lambda operation, data: requests.append((operation, data)))

    dialog.size_box.addItem("999 px", "999")
    dialog.size_box.setCurrentIndex(dialog.size_box.count() - 1)
    dialog.settings_dialog_save()
    assert requests == []
    assert "Not saved" in dialog.message_label.text()
    assert dialog.isVisible() is not True or dialog.result() == 0

    helper_select(dialog.size_box, "256")
    dialog.settings_dialog_save()
    assert requests[0][0] == "app_service_update_settings"
    assert requests[0][1]["settings"].thumbnail_size == 256


def test_reset_asks_once_and_forget_names_the_archive(qtbot):
    """Neither button may act on a single stray press or on nothing at all."""
    dialog = SettingsDialog(Settings(recent_archives=["/archives/main"]))
    qtbot.addWidget(dialog)
    requests = []
    dialog.settings_requested.connect(lambda operation, data: requests.append((operation, data)))

    dialog.reset_button.click()
    assert requests == []
    assert dialog.reset_button.text() == RESET_CONFIRM
    dialog.reset_button.click()
    assert requests == [("app_service_reset_settings", {})]
    assert dialog.reset_button.text() == RESET_PROMPT

    requests.clear()
    assert dialog.forget_button.isEnabled() is False
    dialog.settings_dialog_forget()
    assert requests == []
    dialog.recent_list.setCurrentRow(0)
    assert dialog.forget_button.isEnabled() is True
    dialog.forget_button.click()
    assert requests[0][0] == "app_service_forget_archive"
    assert str(requests[0][1]["archive_root"]) == "/archives/main"
    assert "files are untouched" in dialog.message_label.text()


def test_cache_and_folder_buttons_need_something_to_act_on(qtbot, tmp_path, monkeypatch):
    """A button with no archive behind it explains itself instead of failing."""
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    requests = []
    dialog.settings_requested.connect(lambda operation, data: requests.append((operation, data)))

    assert dialog.clear_button.isEnabled() is False
    assert dialog.logs_button.isEnabled() is False
    dialog.settings_dialog_clear_cache()
    assert requests == []
    assert "Open an archive first" in dialog.message_label.text()
    dialog.settings_dialog_open_logs()
    assert "no log folder" in dialog.message_label.text()

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: bool(opened.append(url.toLocalFile()))
    )
    assert settings_dialog_open_location(None) is False
    assert settings_dialog_open_location(tmp_path / "missing" / "settings.json") is False
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    dialog.settings_file = settings_file
    dialog.settings_dialog_show_file()
    assert opened == [str(tmp_path)]

    with_archive = SettingsDialog(Settings(), archive_open=True, logs_dir=tmp_path)
    qtbot.addWidget(with_archive)
    cleared = []
    with_archive.settings_requested.connect(lambda operation, data: cleared.append(operation))
    assert with_archive.clear_button.isEnabled() is True
    with_archive.clear_button.click()
    assert cleared == ["app_service_clear_thumbnails"]


def test_preferences_run_with_no_archive_open(qtbot):
    """Settings are per-user, so the editor must work before an archive exists."""
    controller = WorkerController()
    replies, failures = {}, {}
    controller.result_ready.connect(lambda reply: replies.update({reply.request_id: reply}))
    controller.failed.connect(lambda failure: failures.update({failure.request_id: failure}))

    def wait(request_id):
        qtbot.waitUntil(lambda: request_id in replies or request_id in failures, timeout=15000)
        return replies.get(request_id), failures.get(request_id)

    try:
        saved = Settings(theme="dark", thumbnail_size=128)
        reply, failure = wait(
            controller.worker_submit("app_service_update_settings", {"settings": saved})
        )
        assert failure is None and reply.value.theme == "dark"
        reply, _ = wait(controller.worker_submit("app_service_get_settings", {}))
        assert reply.value.thumbnail_size == 128
        reply, _ = wait(controller.worker_submit("app_service_settings_path", {}))
        assert reply.value == settings_path()
        reply, _ = wait(controller.worker_submit("app_service_reset_settings", {}))
        assert reply.value.theme == "system"
        # An operation that needs an archive still refuses; the preferences
        # service is bound to a root that cannot be one.
        _, failure = wait(controller.worker_submit("app_service_stats", {}))
        assert failure is not None
        assert "Open an archive" in failure.message
        assert controller.archive_root is None
    finally:
        controller.worker_shutdown()
        assert controller.worker_wait(5000)
    assert settings_load().theme == "system"


def test_the_preferences_service_cannot_reach_an_archive(tmp_path, monkeypatch):
    """The sentinel root fails closed: no archive-free operation can invent one."""
    service = app_service_preferences()
    assert isinstance(service, AppService)
    assert service.app_service_get_settings() == Settings()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Exception) as error:
        service.app_service_stats()
    assert "not an ibackup archive" in str(error.value)
    assert list(tmp_path.iterdir()) == []
    assert set(SETTINGS_OPERATIONS) - {"app_service_clear_thumbnails"} <= ARCHIVE_FREE_OPERATIONS


def test_the_window_saves_and_applies_what_was_edited(window, qtbot, qapp):
    """A saved preference reaches the file and the running window, not just one of them."""
    main = window()
    controller = ThemeController(qapp, main)
    palette = qapp.palette()
    try:
        dialog = helper_open_settings(main, qtbot)
        assert dialog.settings_file == settings_path()
        assert dialog.clear_button.isEnabled() is False

        helper_select(dialog.size_box, "128")
        helper_select(dialog.theme_box, "dark")
        helper_select(dialog.deleted_action_box, DELETED_ACTION_PURGE)
        helper_select(dialog.log_level_box, "WARNING")
        dialog.reopen_box.setChecked(True)
        dialog.archive_edit.setText("/archives/main")
        dialog.save_button.click()

        qtbot.waitUntil(lambda: settings_path().is_file(), timeout=15000)
        qtbot.waitUntil(lambda: main.preferences.thumbnail_size == 128, timeout=15000)
        stored = settings_load()
        assert stored.thumbnail_size == 128
        assert stored.theme == "dark"
        assert stored.default_deleted_action == DELETED_ACTION_PURGE
        assert stored.log_level == "WARNING"
        assert stored.default_archive == "/archives/main"
        assert stored.confirm_word_required is True
        # Applied live, not only at the next launch.
        assert main.previews.size == 128
        assert controller.preference == "dark"
        review = main.shell.reviews["deleted-phone"]
        assert review.buttons["purge"].isDefault() is True
        assert review.buttons["recycle"].isDefault() is False
        qtbot.waitUntil(lambda: main.settings_dialog is None, timeout=15000)
    finally:
        controller.timer.stop()
        qapp.setPalette(palette)


def test_resetting_from_the_window_restores_the_defaults(window, qtbot):
    """A reset re-reads from the service, so the dialog shows what is really stored."""
    settings_save(Settings(thumbnail_size=512, theme="light", scan_phone_after_import=False))
    main = window()
    dialog = helper_open_settings(main, qtbot)
    assert dialog.size_box.currentData() == "512"

    dialog.reset_button.click()
    dialog.reset_button.click()
    qtbot.waitUntil(lambda: dialog.size_box.currentData() == "256", timeout=15000)
    assert settings_load() == Settings()
    assert dialog.theme_box.currentData() == "system"
    assert dialog.scan_box.isChecked() is True
    assert dialog.reset_button.text() == RESET_PROMPT
    assert main.preferences.thumbnail_size == 256
    assert main.shell.reviews["deleted-phone"].buttons["recycle"].isDefault() is True


def test_forgetting_an_archive_keeps_its_files(window, qtbot, tmp_path):
    """Forgetting is a preference change, never a deletion."""
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "photo.jpg").write_bytes(b"not a real photo")
    settings_save(Settings(recent_archives=[str(archive)], default_archive=str(archive)))
    main = window()
    dialog = helper_open_settings(main, qtbot)
    assert dialog.recent_list.count() == 1

    dialog.recent_list.setCurrentRow(0)
    dialog.forget_button.click()
    qtbot.waitUntil(lambda: dialog.recent_list.count() == 0, timeout=15000)
    assert settings_load().recent_archives == []
    assert (archive / "photo.jpg").read_bytes() == b"not a real photo"


def test_the_settings_dialog_is_opened_once(window, qtbot):
    """A second press raises the open dialog instead of building a rival one."""
    main = window()
    dialog = helper_open_settings(main, qtbot)
    main.main_window_command("settings")
    assert main.settings_dialog is dialog
    assert main.settings_requests == {}


def test_reopen_on_startup_only_reopens_a_real_archive(window, qtbot, tmp_path):
    """The preference remembers a location; it may never create or damage one."""
    main = window()
    missing = tmp_path / "gone"
    settings_save(Settings(default_archive=str(missing), reopen_last_archive=True))
    main.preferences = settings_load()
    assert main.main_window_restore_session() is None
    assert missing.exists() is False
    assert main.worker.archive_root is None

    root = tmp_path / "archive"
    main.main_window_open_path(root, create=True)
    qtbot.waitUntil(lambda: main.worker.archive_root == root, timeout=15000)
    main.main_window_command("close")
    qtbot.waitUntil(lambda: main.worker.archive_root is None, timeout=15000)

    settings_save(Settings(default_archive=str(root), reopen_last_archive=False))
    main.preferences = settings_load()
    assert main.main_window_restore_session() is None
    assert main.worker.archive_root is None

    settings_save(Settings(default_archive=None, recent_archives=[str(root)]))
    main.preferences = settings_load()
    assert main.main_window_restore_session() is not None
    qtbot.waitUntil(lambda: main.worker.archive_root == root, timeout=15000)


def test_a_broken_settings_file_never_stops_the_window(tmp_path, monkeypatch, caplog):
    """A hand-edited file falls back to defaults instead of blocking the interface."""
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text('{"thumbnail_size": 999}', encoding="utf-8")
    assert main_window_preferences() == Settings()
    assert main_window_preview_size() == 256
    assert main_window_preview_size(Settings(thumbnail_size=128)) == 128
    # A value outside the loader's bounds is replaced rather than trusted.
    assert main_window_preview_size(Settings(thumbnail_size=999999)) == 256


def test_an_unapplicable_preference_is_ignored_rather_than_raising(window, qtbot):
    """Replies that are not settings must not be applied as if they were."""
    main = window()
    main.main_window_apply_preferences("not settings")
    assert main.preferences == Settings()
    main.main_window_show_settings(None)
    assert main.settings_dialog is None
    main.main_window_settings_action("app_service_update_settings", "not parameters")
    assert main.settings_requests == {}
    assert main_window_module.DEFERRED_COMMANDS == {}


def test_a_refused_save_is_reported_and_changes_nothing(window, qtbot, monkeypatch):
    """A service refusal leaves the stored preferences exactly as they were."""
    settings_save(Settings(theme="light"))
    main = window()
    messages = []
    main.statusBar().messageChanged.connect(messages.append)

    # A value the service refuses, bypassing the dialog's own validation.
    request_id = main.main_window_settings_submit(
        "app_service_update_settings", {"settings": Settings(confirm_word_required=False)}
    )
    qtbot.waitUntil(lambda: request_id not in main.settings_requests, timeout=15000)
    assert settings_load().theme == "light"
    assert settings_load().confirm_word_required is True
    assert any("failed" in message for message in messages)
    assert main.preferences.confirm_word_required is True


def test_the_deleted_review_only_suggests_the_preferred_action(window, qtbot):
    """A preference may change which button is offered, never what it does."""
    main = window()
    review = main.shell.reviews["deleted-phone"]
    main.shell.shell_set_deleted_default(DELETED_ACTION_PURGE)
    assert review.buttons["purge"].isDefault() is True
    main.shell.shell_set_deleted_default(DELETED_ACTION_RECYCLE)
    assert review.buttons["recycle"].isDefault() is True
    assert review.buttons["purge"].isDefault() is False
    # Suggesting does not enable: without a selection the verbs stay disabled.
    assert review.buttons["purge"].isEnabled() is False
    assert review.buttons["recycle"].isEnabled() is False
