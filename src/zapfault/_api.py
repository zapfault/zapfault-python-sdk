"""The public functions. Each one catches everything, because the SDK must
never break the app it watches. While the SDK is off, _client is None and
every function does nothing."""

from __future__ import annotations

import atexit
import logging
import sys
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Callable, Literal

from . import _debug, _hooks, _logging, _scope
from ._client import Client
from ._dsn import parse_dsn
from ._options import Options
from ._protocol import BeforeSend, BreadcrumbType, Integration, Level, User
from ._scope import Scope

_client: Client | None = None
_lock = threading.Lock()
_installed = False


def init(
    dsn: str | None = None,
    *,
    enabled: bool | None = None,
    debug: bool | None = None,
    environment: str | None = None,
    release: str | None = None,
    service: str | None = None,
    sample_rate: float | None = None,
    transport: Literal["http", "console"] | None = None,
    max_queue_size: int | None = None,
    shutdown_timeout: float | None = None,
    before_send: BeforeSend | None = None,
    include_local_variables: bool | None = None,
    in_app_include: Sequence[str] | None = None,
    in_app_exclude: Sequence[str] | None = None,
    tags: Mapping[str, str | int | float | bool] | None = None,
    max_breadcrumbs: int | None = None,
    logging_breadcrumbs: bool | None = None,
    disabled_integrations: Sequence[Integration] | None = None,
) -> None:
    """Turns the SDK on; calling it again replaces the earlier setup. An option
    left out is read from its ZAPFAULT_* environment variable, if it has one.

    dsn: where to send events (ZAPFAULT_DSN); without one the SDK is off.
    enabled: False turns the SDK off.
    debug: prints what the SDK does.
    environment: default APP_ENV or ENVIRONMENT, then "production".
    release: the app's version; default the commit your host sets, then `git rev-parse HEAD`.
    service: the name of this app or service.
    sample_rate: the share of events sent, 0 to 1.
    transport: "console" prints events instead of sending them.
    max_queue_size: events waiting to be sent, default 100; more are dropped.
    shutdown_timeout: seconds to keep sending when the program exits, default 2.
    before_send: called with each event and a hint before it is sent; return
        the event (changed or not) to send it, or None to drop it. If it
        raises, the event is dropped. hint["original_exception"] is the
        exception itself, to tell errors apart by class.
    include_local_variables: send your own frames' local variables, default True.
    in_app_include, in_app_exclude: module prefixes that do or don't count as your code.
    tags: tags sent with every event, like {"region": "eu"}.
    max_breadcrumbs: breadcrumbs kept for the next error, 0 to 100, default 100.
    logging_breadcrumbs: log records at INFO and above become breadcrumbs, default True.
    disabled_integrations: integrations to leave off, like ["flask"].
    """
    global _client, _installed
    try:
        options = Options(
            {
                "dsn": dsn,
                "enabled": enabled,
                "debug": debug,
                "environment": environment,
                "release": release,
                "service": service,
                "sample_rate": sample_rate,
                "transport": transport,
                "max_queue_size": max_queue_size,
                "shutdown_timeout": shutdown_timeout,
                "before_send": before_send,
                "include_local_variables": include_local_variables,
                "in_app_include": in_app_include,
                "in_app_exclude": in_app_exclude,
                "tags": tags,
                "max_breadcrumbs": max_breadcrumbs,
                "logging_breadcrumbs": logging_breadcrumbs,
                "disabled_integrations": disabled_integrations,
            }
        )
        with _lock:
            old, _client = _client, None
            if old is not None:
                old.transport.close(old.options.shutdown_timeout)
            _client = _create(options)
            if _client is None:
                return
            _scope.reset(_client.options.tags, _client.options.max_breadcrumbs)
            if not _installed:
                atexit.register(_at_exit)
                _hooks.install(_capture_unhandled)
                _logging.install(_log_breadcrumb)
                _installed = True
            from . import integrations  # imports _api itself, so not at the top

            integrations.setup(_client.options.disabled_integrations)
    except Exception as e:
        _debug.debug(f"init failed: {e!r}")


def capture_message(message: str, level: Level = "info") -> str | None:
    """Sends a message as an event. Returns its event ID, or None when nothing was sent."""
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


def set_user(user: User | None) -> None:
    """Who was affected: {"id": ..., "email": ..., "username": ..., "attributes": {...}}; None clears it."""
    _on_scope("set_user", lambda scope: scope.set_user(user))


def set_tag(key: str, value: str | int | float | bool | None) -> None:
    """A searchable key and value, like ("plan", "pro"); None removes the tag."""
    _on_scope("set_tag", lambda scope: scope.set_tag(key, value))


def set_tags(tags: Mapping[str, str | int | float | bool | None]) -> None:
    """Several tags at once; a None value removes that tag."""
    _on_scope("set_tags", lambda scope: scope.set_tags(tags))


def set_context(name: str, value: Mapping[str, Any] | None) -> None:
    """Structured data shown on the event, like ("cart", {"items": 3}); None removes it."""
    _on_scope("set_context", lambda scope: scope.set_context(name, value))


def add_breadcrumb(
    message: str | None = None,
    category: str | None = None,
    level: Level = "info",
    data: Mapping[str, Any] | None = None,
    type: BreadcrumbType = "default",
) -> None:
    """Something that happened; the latest ones are sent with the next error."""
    _on_scope("add_breadcrumb", lambda scope: scope.add_breadcrumb(message, category, level, data, type))


@contextmanager
def scope() -> Iterator[None]:
    """What is set inside the block stays inside it:

        with zapfault.scope():
            zapfault.set_tag("job", "nightly-sync")
            run_sync()

    An exception leaving the block keeps the block's data.
    """
    if _client is None:
        yield
        return
    with _scope.fork():
        yield


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
    """Whether the SDK is on."""
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


def _on_scope(name: str, change: Callable[[Scope], None]) -> None:
    """Changes the active scope; does nothing while the SDK is off."""
    if _client is None:
        return
    try:
        change(_scope.current())
    except Exception as e:
        _debug.debug(f"{name} failed: {e!r}")


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
