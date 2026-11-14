"""The public functions. Each one catches everything, because the SDK must
never break the app it watches. While the SDK is off, _client is None and
every function does nothing."""

from __future__ import annotations

import atexit
import logging
import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import _debug, _hooks, _logging, _scope
from ._client import Client
from ._dsn import parse_dsn
from ._options import Options
from ._scope import Scope

_client: Client | None = None
_lock = threading.Lock()
_installed = False


def init(dsn: str | None = None, **options: Any) -> None:
    """Turns the SDK on. Calling it again replaces the earlier setup."""
    global _client, _installed
    try:
        with _lock:
            old, _client = _client, None
            if old is not None:
                old.transport.close(old.options.shutdown_timeout)
            _client = _create(Options({"dsn": dsn, **options}))
            if _client is not None:
                _scope.reset(_client.options.tags, _client.options.max_breadcrumbs)
            if _client is not None and not _installed:
                atexit.register(_at_exit)
                _hooks.install(_capture_unhandled)
                _logging.install(_log_breadcrumb)
                _installed = True
    except Exception as e:
        _debug.debug(f"init failed: {e!r}")


def capture_message(message: str, level: str = "info") -> str | None:
    """Sends a message as an event. Returns its event ID, or None when the SDK is off."""
    client = _client
    if client is None:
        return None
    try:
        return client.capture_message(str(message), level)
    except Exception as e:
        _debug.debug(f"capture_message failed: {e!r}")
        return None


def capture_exception(error: BaseException | None = None) -> str | None:
    """Sends an exception you caught; without one, the exception being handled
    in the current except block. Returns its event ID, or None when nothing was sent."""
    client = _client
    if client is None:
        return None
    try:
        if error is None:
            error = sys.exc_info()[1]
        if not isinstance(error, BaseException):
            _debug.debug("capture_exception: no exception to capture")
            return None
        return client.capture_exception(error, "manual", handled=True)
    except Exception as e:
        _debug.debug(f"capture_exception failed: {e!r}")
        return None


def set_user(user: dict[str, Any] | None) -> None:
    """Who was affected: {"id": ..., "email": ..., "username": ...}; None clears it."""
    _on_scope("set_user", user)


def set_tag(key: str, value: Any) -> None:
    """A searchable key and value, like ("plan", "pro"); None removes the tag."""
    _on_scope("set_tag", key, value)


def set_tags(tags: dict[str, Any]) -> None:
    _on_scope("set_tags", tags)


def set_context(name: str, value: dict[str, Any] | None) -> None:
    """Structured data shown on the event, like ("cart", {"items": 3}); None removes it."""
    _on_scope("set_context", name, value)


def add_breadcrumb(
    message: str | None = None,
    category: str | None = None,
    level: str = "info",
    data: dict[str, Any] | None = None,
    type: str = "default",
) -> None:
    """Something that happened; the latest ones are sent with the next error."""
    _on_scope("add_breadcrumb", message, category, level, data, type)


@contextmanager
def scope() -> Iterator[Scope]:
    """Data set inside the block stays inside it:

        with zapfault.scope() as scope:
            scope.set_tag("job", "nightly-sync")
    """
    if _client is None:
        yield Scope()
        return
    with _scope.fork() as active:
        yield active


def flush(timeout: float = 2.0) -> bool:
    """Waits until everything captured so far is sent, at most timeout seconds.
    Returns False if time ran out."""
    client = _client
    if client is None:
        return True
    try:
        return client.transport.flush(timeout)
    except Exception as e:
        _debug.debug(f"flush failed: {e!r}")
        return False


def close(timeout: float = 2.0) -> bool:
    """Flushes, then turns the SDK off."""
    global _client
    try:
        with _lock:
            client, _client = _client, None
        return client.transport.close(timeout) if client is not None else True
    except Exception as e:
        _debug.debug(f"close failed: {e!r}")
        return False


def is_enabled() -> bool:
    return _client is not None


def _create(options: Options) -> Client | None:
    _debug.enabled = options.debug
    if not options.enabled:
        _debug.debug("enabled=False, the SDK is off")
        return None
    dsn = None
    if options.dsn:
        try:
            dsn = parse_dsn(options.dsn)
        except ValueError as e:
            _debug.warn_once(f"the DSN is invalid, the SDK is off: {e}")
            return None
    elif options.transport != "console":
        _debug.debug("no DSN, the SDK is off")
        return None
    client = Client(options, dsn)
    _debug.debug(f"on, transport={options.transport}, environment={options.environment}")
    return client


def _capture_unhandled(error: BaseException, mechanism: str) -> None:
    client = _client
    if client is None:
        return
    try:
        client.capture_exception(error, mechanism, handled=False)
    except Exception as e:
        _debug.debug(f"capturing an uncaught exception failed: {e!r}")


def _on_scope(method: str, *args: Any) -> None:
    """Calls a setter on the active scope; does nothing while the SDK is off."""
    if _client is None:
        return
    try:
        getattr(_scope.current(), method)(*args)
    except Exception as e:
        _debug.debug(f"{method} failed: {e!r}")


def _log_breadcrumb(record: logging.LogRecord) -> None:
    client = _client
    if client is None or not client.options.logging_breadcrumbs or record.levelno < logging.INFO:
        return
    try:
        _scope.current().add_breadcrumb(
            message=record.getMessage(), category=record.name, level=_logging.level(record.levelno), type="log"
        )
    except Exception as e:
        _debug.debug(f"logging breadcrumb failed: {e!r}")


def _at_exit() -> None:
    client = _client
    if client is not None and not close(client.options.shutdown_timeout):
        _debug.debug("exiting before every event was sent (shutdown_timeout)")
