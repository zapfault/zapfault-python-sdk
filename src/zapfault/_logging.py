"""Turns log records into breadcrumbs, so an error shows what the app logged
just before it. It wraps Logger.callHandlers rather than adding a handler: a
handler on the root logger would stop Python from printing warnings in apps
that never set up logging."""

from __future__ import annotations

import logging
from typing import Callable

_installed = False


def install(on_record: Callable[[logging.LogRecord], None]) -> None:
    """Wraps once per process; on_record must never raise."""
    global _installed
    if _installed:
        return
    _installed = True

    original = logging.Logger.callHandlers

    def call_handlers(self: logging.Logger, record: logging.LogRecord) -> None:
        on_record(record)
        original(self, record)

    logging.Logger.callHandlers = call_handlers  # type: ignore[method-assign]


def level(levelno: int) -> str:
    if levelno >= logging.CRITICAL:
        return "fatal"
    if levelno >= logging.ERROR:
        return "error"
    if levelno >= logging.WARNING:
        return "warning"
    return "info" if levelno >= logging.INFO else "debug"
