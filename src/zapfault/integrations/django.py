"""Django: every request runs in its own scope, and an error that becomes a 500
is reported as unhandled, through Django's got_request_exception signal. The
route, request and signed-in user are read only when an event is sent."""

from __future__ import annotations

import functools
import sys
from typing import Any

from django.core.handlers.base import BaseHandler
from django.core.signals import got_request_exception

from .._debug import debug
from .._protocol import Event
from . import capture, request_scope
from ._request import from_environ

NAME = "django"


def setup_once() -> None:
    # Every request passes through one of these, under WSGI (runserver,
    # gunicorn), ASGI (uvicorn, daphne) and the test clients alike.
    sync, asynchronous = BaseHandler.get_response, BaseHandler.get_response_async

    @functools.wraps(sync)
    def get_response(self: BaseHandler, request: Any) -> Any:
        with request_scope(NAME, functools.partial(_fill, request)):
            return sync(self, request)

    @functools.wraps(asynchronous)
    async def get_response_async(self: BaseHandler, request: Any) -> Any:
        with request_scope(NAME, functools.partial(_fill, request)):
            return await asynchronous(self, request)

    BaseHandler.get_response = get_response
    BaseHandler.get_response_async = get_response_async
    got_request_exception.connect(_on_exception, weak=False, dispatch_uid="zapfault")


def _on_exception(sender: Any, **extra: Any) -> None:
    """Sent inside Django's except block (under ASGI too: asgiref raises the
    error again in its worker thread), so sys.exc_info() has it."""
    error = sys.exc_info()[1]
    if error is not None:
        capture(error, NAME)


def _fill(request: Any, item: Event) -> None:
    match = getattr(request, "resolver_match", None)
    if "route" not in item and match is not None and match.route:
        item["route"] = f"{request.method} /{match.route}"
    if "request" not in item:
        item["request"] = from_environ(request.META, scheme=request.scheme, path=request.path)
    if "user" not in item:
        try:
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                item["user"] = {"id": str(user.pk)}
        except Exception as e:  # a broken database, or an async view that never loaded the user
            debug(f"reading the signed-in user failed: {e!r}")
