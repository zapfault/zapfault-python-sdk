"""Flask: every request runs in its own scope, and an error that a route turns
into a 500 is reported as unhandled, through Flask's got_request_exception
signal."""

from __future__ import annotations

import functools
from typing import Any

import flask

from . import capture, request_scope
from ._request import from_environ

NAME = "flask"


def setup_once() -> None:
    original = flask.Flask.__call__

    # Patching __call__, not wsgi_app, keeps middleware like
    # app.wsgi_app = ProxyFix(app.wsgi_app) inside the request's scope.
    @functools.wraps(original)
    def __call__(self: flask.Flask, environ: dict[str, Any], start_response: Any) -> Any:
        with request_scope(NAME, functools.partial(_fill, environ)):
            return original(self, environ, start_response)

    flask.Flask.__call__ = __call__  # type: ignore[method-assign]
    flask.got_request_exception.connect(_on_exception, weak=False)


def _on_exception(sender: Any, exception: BaseException, **extra: Any) -> None:
    capture(exception, NAME)


def _fill(environ: dict[str, Any], item: dict) -> None:
    """The route as written, like GET /orders/<int:order_id>."""
    if "route" not in item and flask.has_request_context() and flask.request.url_rule is not None:
        item["route"] = f"{flask.request.method} {flask.request.url_rule.rule}"
    if "request" not in item:
        item["request"] = from_environ(environ)
