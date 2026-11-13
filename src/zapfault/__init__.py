"""Zapfault error tracking. Call zapfault.init(dsn=...) once when the app starts."""

from ._api import capture_exception, capture_message, close, flush, init, is_enabled
from ._version import __version__

__all__ = ["__version__", "capture_exception", "capture_message", "close", "flush", "init", "is_enabled"]
