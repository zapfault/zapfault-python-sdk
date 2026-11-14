"""What the app tells the SDK about the moment an error happens: the user, the
tags, structured contexts, and the breadcrumbs that led up to it.

One scope is active at a time in each thread and asyncio task (a ContextVar);
until something opens another, that is the process-wide scope. scope() works
on a copy of the active one, so nothing set inside it leaks out. Integrations
open such a copy for every request, which keeps requests apart."""

from __future__ import annotations

import contextvars
import math
import re
import threading
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from ._debug import debug
from ._event import truncate
from ._transport import utc_now

MAX_TAGS = 50
MAX_TAG_VALUE = 200
MAX_DEPTH = 10
MAX_ITEMS = 100
TAG_KEY = re.compile(r"^[a-zA-Z0-9_.:-]{1,32}$")
USER_FIELDS = ("id", "email", "username", "ip_address")
LEVELS = ("fatal", "error", "warning", "info", "debug")
BREADCRUMB_TYPES = ("default", "http", "navigation", "ui", "query", "log")


class Scope:
    def __init__(self, max_breadcrumbs: int = 100) -> None:
        self._lock = threading.Lock()
        self._user: dict[str, Any] = {}
        self._tags: dict[str, str] = {}
        self._contexts: dict[str, Any] = {}
        self._breadcrumbs: deque = deque(maxlen=max_breadcrumbs)

    def copy(self) -> Scope:
        new = Scope(self._breadcrumbs.maxlen or 100)
        with self._lock:
            new._user, new._tags, new._contexts = dict(self._user), dict(self._tags), dict(self._contexts)
            new._breadcrumbs.extend(self._breadcrumbs)
        return new

    def set_user(self, user: dict[str, Any] | None) -> None:
        """id, email, username and ip_address as given, other keys as attributes; None clears it."""
        if user is None:
            with self._lock:
                self._user = {}
            return
        if not isinstance(user, dict):
            debug(f"set_user: expected a dict or None, got {type(user).__name__}")
            return
        out: dict[str, Any] = {}
        attributes = {}
        for key, value in user.items():
            if value is None:
                continue
            if key in USER_FIELDS:
                out[key] = truncate(str(value), MAX_TAG_VALUE)
            else:
                attributes[str(key)] = value
        if attributes:
            out["attributes"] = json_safe(attributes)
        with self._lock:
            self._user = out

    def set_tag(self, key: str, value: Any) -> None:
        """A searchable key and value; None removes the tag."""
        key = str(key)
        if value is None:
            with self._lock:
                self._tags.pop(key, None)
            return
        if not TAG_KEY.match(key):
            debug(f"tag {key!r} dropped: keys are 1 to 32 letters, digits, _ . : or -")
            return
        with self._lock:
            if key not in self._tags and len(self._tags) >= MAX_TAGS:
                debug(f"tag {key!r} dropped: at most {MAX_TAGS} tags")
                return
            self._tags[key] = truncate(str(value), MAX_TAG_VALUE)

    def set_tags(self, tags: dict[str, Any]) -> None:
        for key, value in tags.items():
            self.set_tag(key, value)

    def set_context(self, name: str, value: dict[str, Any] | None) -> None:
        """Structured data shown on the event, not searchable; None removes it."""
        with self._lock:
            if value is None:
                self._contexts.pop(str(name), None)
            else:
                self._contexts[str(name)] = json_safe(value)

    def add_breadcrumb(
        self,
        message: str | None = None,
        category: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
        type: str = "default",
    ) -> None:
        crumb: dict[str, Any] = {
            "timestamp": utc_now(),
            "type": type if type in BREADCRUMB_TYPES else "default",
            "level": level if level in LEVELS else "info",
        }
        if message is not None:
            crumb["message"] = truncate(str(message))
        if category is not None:
            crumb["category"] = truncate(str(category), MAX_TAG_VALUE)
        if data:
            crumb["data"] = json_safe(data)
        self._breadcrumbs.append(crumb)  # a full deque drops the oldest

    def apply(self, item: dict) -> None:
        """Copies the scope's data into an event item."""
        with self._lock:
            if self._user:
                item["user"] = dict(self._user)
            if self._tags:
                item["tags"] = dict(self._tags)
            if self._contexts:
                item["contexts"] = dict(self._contexts)
            if self._breadcrumbs:
                item["breadcrumbs"] = list(self._breadcrumbs)


_global = Scope()
_active: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("zapfault_scope", default=None)


def current() -> Scope:
    return _active.get() or _global


def reset(tags: dict[str, Any], max_breadcrumbs: int) -> None:
    """init starts the process-wide scope over with its options."""
    global _global
    _global = Scope(max_breadcrumbs)
    _global.set_tags(tags)


@contextmanager
def fork() -> Iterator[Scope]:
    """A copy of the active scope for the block. An exception leaving the block
    keeps the copy, so it is reported with the block's data even when it's
    only caught (or not) after the block ends."""
    scope = current().copy()
    token = _active.set(scope)
    try:
        yield scope
    except BaseException as error:
        if not hasattr(error, "__zapfault_scope__"):
            try:
                setattr(error, "__zapfault_scope__", scope)
            except Exception:
                pass
        raise
    finally:
        try:
            _active.reset(token)
        except ValueError:  # exited in another context than it was entered in
            _active.set(None)


def for_error(error: BaseException) -> Scope:
    """The scope an exception was raised in, if it left a scope() block."""
    scope = getattr(error, "__zapfault_scope__", None)
    return scope if isinstance(scope, Scope) else current()


def json_safe(value: Any, depth: int = 0) -> Any:
    """Data the JSON encoder can always handle: other objects become their repr,
    and deep or long structures are cut."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)  # JSON has no NaN or Infinity
    if isinstance(value, str):
        return truncate(value)
    if depth >= MAX_DEPTH:
        return "[depth exceeded]"
    if isinstance(value, dict):
        return {str(k): json_safe(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
    try:
        return truncate(repr(value), 256)
    except Exception:
        return "<unrepresentable>"
