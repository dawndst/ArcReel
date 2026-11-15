"""Cooperative cancellation shared by Note workflow stages."""

from collections.abc import Callable
from contextvars import ContextVar

stop_requested: ContextVar[Callable[[], bool] | None] = ContextVar("novel_stop_requested", default=None)


class NovelReadingInterrupted(RuntimeError):
    """The paid response and completed work are preserved before stopping."""


def check_stop() -> None:
    check = stop_requested.get()
    if check is not None and check():
        raise NovelReadingInterrupted("Novel reading stopped; completed work is saved and can be resumed")
