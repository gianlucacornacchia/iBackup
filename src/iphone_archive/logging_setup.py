"""Application logging setup.

Configures a console handler plus a rotating file handler inside the archive's
hidden ``.ibackup/logs`` folder, so every operation on a permanent archive leaves
a durable trace.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "iphone_archive"
LOG_FILE_NAME = "ibackup.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def logging_setup_configure(logs_dir: Path | None = None, verbose: bool = False) -> logging.Logger:
    """Configure and return the application logger.

    logs_dir: folder for the rotating log file; when None only console logging
        is configured (used before an archive is known).
    verbose: when True, emit debug-level messages to the console.
    Returns the configured application logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / LOG_FILE_NAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


def logging_setup_get_logger(module_name: str) -> logging.Logger:
    """Return a child logger for a module.

    module_name: short module identifier appended to the app logger name.
    Returns the child logger instance.
    """
    return logging.getLogger(f"{LOGGER_NAME}.{module_name}")
