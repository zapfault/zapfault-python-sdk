"""FastAPI, and any Starlette app: every request runs in its own scope, and an
error that becomes a 500 is reported as unhandled. Starlette answers it with
the 500 page, then raises it again for the server to log, which is where it
is caught here."""

from __future__ import annotations

import functools
from typing import Any

from starlette.applications import Starlette

from . import capture, request_scope
from ._request import from_asgi

NAME = "fastapi"


def setup_once() -> None:
    original = Starlette.__call__

    @functools.wraps(original)
    async def __call__(self: Starlette, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":  # websockets and lifespan pass through
            return await original(self, scope, receive, send)
        with request_scope(NAME, functools.partial(_fill, scope)):
            try:
                return await original(self, scope, receive, send)
            except Exception as error:
                capture(error, NAME)
                raise

    Starlette.__call__ = __call__  # type: ignore[method-assign]


def _fill(scope: dict, item: dict) -> None:
    """The route as written, like GET /orders/{order_id}; the router puts the
    matched route in the ASGI scope."""
    path = getattr(scope.get("route"), "path", None)
    if "route" not in item and path:
        item["route"] = f"{scope.get('method', 'GET')} {path}"
    if "request" not in item:
        item["request"] = from_asgi(scope)
