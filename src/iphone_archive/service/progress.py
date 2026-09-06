"""Progress reporting and cooperative cancellation.

Long operations report progress through a handle rather than printing, so the
CLI and the GUI can render them differently while sharing one implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ProgressEvent:
    """A single progress update emitted by a long-running operation."""

    operation: str
    current: int
    total: int
    message: str = ""

    @property
    def fraction(self) -> float:
        """Return completion as a value between 0.0 and 1.0."""
        return (self.current / self.total) if self.total else 0.0


class ProgressHandle:
    """Carries a progress callback and a cancellation flag into an operation."""

    def __init__(self, callback: Callable[[ProgressEvent], None] | None = None) -> None:
        """Create a progress handle.

        callback: optional function invoked for each progress event.
        """
        self.callback = callback
        self.cancelled = False
        self.events: list[ProgressEvent] = []

    def progress_report(self, operation: str, current: int, total: int, message: str = "") -> None:
        """Emit a progress event to the callback.

        operation: name of the running operation.
        current: number of units completed so far.
        total: total number of units, or 0 when unknown.
        message: optional human-readable detail.
        Returns None.
        """
        event = ProgressEvent(operation=operation, current=current, total=total, message=message)
        self.events.append(event)
        if self.callback is not None:
            self.callback(event)

    def progress_cancel(self) -> None:
        """Request cancellation of the running operation.

        Returns None. Operations stop at their next safe checkpoint.
        """
        self.cancelled = True

    def progress_is_cancelled(self) -> bool:
        """Report whether cancellation has been requested.

        Returns True when the operation should stop at a safe point.
        """
        return self.cancelled
