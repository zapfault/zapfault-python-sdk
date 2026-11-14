"""Zapfault error tracking. Call zapfault.init(dsn=...) once when the app starts."""

from ._api import (
    add_breadcrumb,
    capture_exception,
    capture_message,
    close,
    flush,
    init,
    is_enabled,
    scope,
    set_context,
    set_tag,
    set_tags,
    set_user,
)
from ._version import __version__

__all__ = [
    "__version__",
    "add_breadcrumb",
    "capture_exception",
    "capture_message",
    "close",
    "flush",
    "init",
    "is_enabled",
    "scope",
    "set_context",
    "set_tag",
    "set_tags",
    "set_user",
]
