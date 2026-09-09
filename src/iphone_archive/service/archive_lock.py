"""Exclusive local archive sessions, shared by CLI and future GUI workers."""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import BinaryIO


class ArchiveBusyError(OSError):
    """Another process or service currently owns this archive."""


class ArchiveLock:
    """Hold an OS lock for a service lifetime; process death releases the lock."""

    def __init__(self, path: Path) -> None:
        """Create a lock for the archive's persistent lock file."""
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        """Acquire without waiting; reject competing sessions explicitly."""
        handle = self.path.open("a+b")
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ArchiveBusyError(
                    f"archive is already open: {self.path.parent.parent}"
                ) from error
            raise
        self.handle = handle

    def release(self) -> None:
        """Release the OS lock by closing its owning file descriptor."""
        if self.handle is not None:
            self.handle.close()
            self.handle = None
