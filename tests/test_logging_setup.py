"""Tests for application logging configuration."""

from __future__ import annotations

import logging

from iphone_archive import logging_setup


def test_console_only_configuration():
    """Without a logs folder only a console handler is attached."""
    logger = logging_setup.logging_setup_configure(logs_dir=None)
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.StreamHandler)


def test_file_handler_writes_log(tmp_path):
    """With a logs folder, messages reach the rotating log file."""
    logs_dir = tmp_path / "logs"
    logger = logging_setup.logging_setup_configure(logs_dir=logs_dir)
    logger.info("archive initialized")
    for handler in logger.handlers:
        handler.flush()

    log_file = logs_dir / logging_setup.LOG_FILE_NAME
    assert log_file.is_file()
    assert "archive initialized" in log_file.read_text(encoding="utf-8")


def test_verbose_sets_debug_console_level():
    """Verbose mode lowers the console handler to debug."""
    logger = logging_setup.logging_setup_configure(logs_dir=None, verbose=True)
    assert logger.handlers[0].level == logging.DEBUG


def test_child_logger_namespaced():
    """Module loggers are children of the application logger."""
    child = logging_setup.logging_setup_get_logger("importer")
    assert child.name == f"{logging_setup.LOGGER_NAME}.importer"


def test_reconfigure_does_not_duplicate_handlers(tmp_path):
    """Configuring twice replaces handlers instead of stacking them."""
    logging_setup.logging_setup_configure(logs_dir=tmp_path / "logs")
    logger = logging_setup.logging_setup_configure(logs_dir=tmp_path / "logs")
    assert len(logger.handlers) == 2
