"""Flask: every request runs in its own scope with the request on it, and an
error that a route turns into a 500 is reported as unhandled. Needs Flask 2.3
or newer, the first version that always ships its signals."""

from __future__ import annotations

import functools
import importlib.metadata
import re
from typing import Any

from .. import _api, _scope
from .._debug import debug
from ._wsgi import request_data

NAME = "flask"


def setup_once() -> None:
    version = importlib.metadata.version("flask")
    if tuple(int(n) for n in re.findall(r"\d+", version)[:2]) < (2, 3):
        debug(f"Flask {version} is older than 2.3, the flask integration is off")
        return

    import flask

    original = flask.Flask.__call__

    # Patching __call__, not wsgi_app, keeps middleware like
    # app.wsgi_app = ProxyFix(app.wsgi_app) inside the request's scope.
    @functools.wraps(original)
    def __call__(self: flask.Flask, environ: dict[str, Any], start_response: Any) -> Any:
        if not _api._integration_on(NAME):
            return original(self, environ, start_response)
        with _scope.fork(breadcrumbs=False) as scope:
            try:
                scope.request = request_data(environ)
            except Exception as e:
                debug(f"reading the request failed: {e!r}")
            return original(self, environ, start_response)

    flask.Flask.__call__ = __call__  # type: ignore[method-assign]
    flask.request_started.connect(_on_request_started, weak=False)
    flask.got_request_exception.connect(_on_exception, weak=False)


def _on_request_started(sender: Any, **extra: Any) -> None:
    """The route as written in the app, like GET /orders/<int:order_id>,
    known once Flask has matched the URL."""
    scope = _scope.active()
    if scope is None or not _api._integration_on(NAME):
        return
    try:
        from flask import request

        if request.url_rule is not None:
            scope.route = f"{request.method} {request.url_rule.rule}"
    except Exception as e:
        debug(f"reading the route failed: {e!r}")


def _on_exception(sender: Any, exception: BaseException, **extra: Any) -> None:
    if _api._integration_on(NAME):
        _api._capture_unhandled(exception, NAME)
