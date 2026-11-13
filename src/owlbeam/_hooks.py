"""Reports exceptions nobody caught: in the main thread (sys.excepthook) and in
other threads (threading.excepthook). Each hook calls the one that was there
before, so Python still prints the traceback and exits as usual."""

from __future__ import annotations

import sys
import threading
from types import TracebackType
from typing import Any, Callable

_installed = False


def install(capture: Callable[[BaseException, str], None]) -> None:
    """Installs both hooks once per process; capture must never raise."""
    global _installed
    if _installed:
        return
    _installed = True

    previous = sys.excepthook

    def excepthook(type_: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
        if not issubclass(type_, KeyboardInterrupt):
            capture(value, "excepthook")
        previous(type_, value, tb)

    sys.excepthook = excepthook

    previous_thread = threading.excepthook

    def thread_excepthook(args: Any) -> None:
        if args.exc_value is not None and not issubclass(args.exc_type, SystemExit):
            capture(args.exc_value, "threading")
        previous_thread(args)

    threading.excepthook = thread_excepthook
