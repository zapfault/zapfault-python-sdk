"""The client exists while the SDK is on. It holds the options, the facts about
this process (the resource) and the transport, and turns a capture into an
envelope."""

from __future__ import annotations

import platform
import random
import socket
import uuid

from ._debug import debug
from ._dsn import Dsn
from ._event import exception_values, truncate
from ._options import Options, git_release
from ._transport import ConsoleTransport, HttpTransport, utc_now
from ._version import __version__

LEVELS = ("fatal", "error", "warning", "info", "debug")
MAX_MESSAGE = 8192


class Client:
    def __init__(self, options: Options, dsn: Dsn | None) -> None:
        self.options = options
        if options.transport == "console" or dsn is None:
            self.transport = ConsoleTransport()
        else:
            self.transport = HttpTransport(dsn, options.max_queue_size)
        self._head = {
            "protocol": 1,
            "sdk": {"name": "zapfault.python", "version": __version__},
            "resource": _resource(options),
        }

    def capture_message(self, message: str, level: str) -> str | None:
        if not self._sampled():
            return None
        if level not in LEVELS:
            debug(f"unknown level {level!r}, using 'info'")
            level = "info"
        item = _item(level)
        item["message"] = truncate(message, MAX_MESSAGE)
        if len(message) > MAX_MESSAGE:
            item["_meta"] = {"message": {"truncated_from": len(message)}}
        return self._send(item)

    def capture_exception(self, error: BaseException, mechanism: str, handled: bool) -> str | None:
        # The same exception object is sent once: capture_exception() then
        # `raise` would otherwise be reported again by the excepthook.
        if getattr(error, "__zapfault_captured__", False):
            debug("exception already captured")
            return None
        try:
            setattr(error, "__zapfault_captured__", True)
        except Exception:
            pass
        if not self._sampled():
            return None
        values = exception_values(error, self.options)
        values[-1]["mechanism"] = {"type": mechanism, "handled": handled}
        item = _item("error")
        item["exception"] = {"values": values}
        return self._send(item)

    def _sampled(self) -> bool:
        if random.random() < self.options.sample_rate:
            return True
        debug("event dropped by sample_rate")
        return False

    def _send(self, item: dict) -> str:
        self.transport.send({**self._head, "items": [item]})
        return item["event_id"]


def _item(level: str) -> dict:
    return {
        "type": "error",
        "event_id": uuid.uuid4().hex,
        "timestamp": utc_now(),
        "level": level,
        "platform": "python",
    }


def _resource(options: Options) -> dict:
    """What is the same for every event from this process; sent once per envelope."""
    resource = {
        "service": options.service,
        "release": options.release or git_release(),
        "environment": options.environment,
        "host": socket.gethostname(),
        "runtime": {"name": platform.python_implementation(), "version": platform.python_version()},
        "os": {"name": platform.system(), "version": platform.release()},
    }
    return {k: v for k, v in resource.items() if v}
