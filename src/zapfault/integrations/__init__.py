"""Integrations hook a web framework the app has installed. Each one is a module
whose setup_once() patches the framework so that every request runs as:

    with request_scope(NAME, fill):   # its own scope; fill(item) adds the request
        ...                           # and route to an event when one is sent
    capture(error, NAME)              # for an error the framework turns into a 500

To add a framework: write that module and list it in AVAILABLE. A framework
that isn't installed, or is older than its minimum, is never imported."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import re
from contextlib import contextmanager
from typing import Callable, Iterator

from .. import _api, _scope
from .._debug import debug

# Integration name -> (the package it patches, its oldest supported version).
AVAILABLE = {
    "flask": ("flask", (2, 3)),
    "django": ("django", (4, 2)),
    "fastapi": ("starlette", (0, 27)),
}

_done: set[str] = set()


def setup(disabled: tuple[str, ...]) -> None:
    """Sets up every installed integration once per process; init calls it."""
    for name, (package, minimum) in AVAILABLE.items():
        if name in disabled or name in _done or not _installed(package):
            continue
        _done.add(name)
        try:
            version = importlib.metadata.version(package)
            if tuple(int(n) for n in re.findall(r"\d+", version)[:2]) < minimum:
                debug(f"{package} {version} is too old, the {name} integration needs {'.'.join(map(str, minimum))}+")
                continue
            importlib.import_module(f"{__name__}.{name}").setup_once()
        except Exception as e:
            debug(f"the {name} integration failed to start: {e!r}")


def on(name: str) -> bool:
    client = _api._client
    return client is not None and name not in client.options.disabled_integrations


@contextmanager
def request_scope(name: str, fill: Callable[[dict], None]) -> Iterator[None]:
    """Runs one request in its own scope, which starts without the breadcrumbs
    logged outside it. A request already in one, like an app mounted in
    another, keeps that one."""
    active = _scope.active()
    if not on(name) or (active is not None and active.in_request):
        yield
        return
    with _scope.fork(breadcrumbs=False) as scope:
        scope.in_request = True
        scope.add_processor(fill)
        yield


def capture(error: BaseException, name: str) -> None:
    """Reports the error itself when it comes wrapped in an exception group of
    one, as older Starlette middleware raises it under anyio 4."""
    group = getattr(error, "exceptions", None)
    while isinstance(group, (list, tuple)) and len(group) == 1 and isinstance(group[0], BaseException):
        error = group[0]
        group = getattr(error, "exceptions", None)
    if on(name):
        _api._capture_unhandled(error, name)


def _installed(package: str) -> bool:
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, ValueError):
        return False
