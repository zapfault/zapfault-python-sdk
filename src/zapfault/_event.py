"""Turns an exception into the protocol's exception values: the chain of
causes, and for each exception its frames with source lines and local
variables."""

from __future__ import annotations

import linecache
import os
import reprlib
from types import FrameType, TracebackType
from typing import Any

from ._options import Options
from ._protocol import ExceptionValue, Frame, Stacktrace

MAX_CHAIN = 10
MAX_FRAMES = 100
MAX_VARS = 50
MAX_REPR = 256
MAX_VALUE = 8192
CONTEXT_LINES = 5

# A variable whose name contains one of these is sent as "[Filtered]".
SENSITIVE = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "auth",
    "cookie",
    "session",
    "csrf",
    "xsrf",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
)

_STDLIB = os.path.dirname(os.__file__)
_STDLIB_REAL = os.path.realpath(_STDLIB)
_repr = reprlib.Repr()
_repr.maxstring = _repr.maxother = MAX_REPR


def exception_values(error: BaseException, options: Options) -> list[ExceptionValue]:
    """The chain ordered root cause first, the raised exception last."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < MAX_CHAIN:
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    cwd = os.getcwd()
    return [_exception(e, cwd, options) for e in reversed(chain)]


def truncate(text: str, limit: int = MAX_VALUE) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _exception(error: BaseException, cwd: str, options: Options) -> ExceptionValue:
    cls = type(error)
    value: ExceptionValue = {"type": cls.__qualname__}
    if cls.__module__ not in ("builtins", "__main__"):
        value["module"] = cls.__module__
    try:
        text = str(error)
    except Exception:
        text = "<unprintable>"
    if text:
        value["value"] = truncate(text)
    if error.__traceback__ is not None:
        value["stacktrace"] = _stacktrace(error.__traceback__, cwd, options)
    return value


def _stacktrace(tb: TracebackType | None, cwd: str, options: Options) -> Stacktrace:
    stack = []
    while tb is not None:
        stack.append((tb.tb_frame, tb.tb_lineno))
        tb = tb.tb_next
    stacktrace: Stacktrace = {}
    if len(stack) > MAX_FRAMES:
        # Keep where it started and where it raised; deep recursion is in between.
        half = MAX_FRAMES // 2
        stacktrace["frames_omitted"] = (half, len(stack) - half)
        stack = stack[:half] + stack[-half:]
    stacktrace["frames"] = [_frame(frame, line, cwd, options) for frame, line in stack]
    return stacktrace


def _frame(frame: FrameType, lineno: int | None, cwd: str, options: Options) -> Frame:
    code = frame.f_code
    path = code.co_filename
    module = frame.f_globals.get("__name__")
    module = module if isinstance(module, str) else None
    in_app = _in_app(path, module, options)
    item: Frame = {
        "filename": _display_path(path, cwd),
        "abs_path": path,
        # co_name ("total"), not co_qualname ("Cart.total", 3.11+ only): the
        # name is part of the grouping, so upgrading Python must not change it.
        "function": code.co_name,
        "in_app": in_app,
    }
    if module:
        item["module"] = module
    if lineno:
        item["lineno"] = lineno
        lines = linecache.getlines(path, frame.f_globals)
        if lineno <= len(lines):
            i = lineno - 1
            item["pre_context"] = [line.rstrip("\r\n") for line in lines[max(0, i - CONTEXT_LINES) : i]]
            item["context_line"] = lines[i].rstrip("\r\n")
            item["post_context"] = [line.rstrip("\r\n") for line in lines[i + 1 : i + 1 + CONTEXT_LINES]]
    # A module's top level has its imports and functions as "variables": noise.
    if in_app and options.include_local_variables and code.co_name != "<module>":
        item["vars"] = _vars(frame.f_locals)
    return item


def _in_app(path: str, module: str | None, options: Options) -> bool:
    """Whether the frame is the developer's own code, not Python's or a library's."""
    if module and module.startswith(options.in_app_include):
        return True
    if module and module.startswith(options.in_app_exclude):
        return False
    if path.startswith("<") or "site-packages" in path or "dist-packages" in path:
        return False
    return not (path.startswith(_STDLIB) or path.startswith(_STDLIB_REAL))


def _display_path(path: str, cwd: str) -> str:
    """Short and the same on every machine: relative to the app or to site-packages."""
    for marker in ("site-packages" + os.sep, "dist-packages" + os.sep):
        if marker in path:
            return path.split(marker, 1)[1]
    if path.startswith(cwd + os.sep):
        return path[len(cwd) + 1 :]
    return path


def _vars(local_vars: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in local_vars.items():
        if name.startswith("__"):
            continue
        if len(out) == MAX_VARS:
            break
        lower = name.lower()
        out[name] = "[Filtered]" if any(s in lower for s in SENSITIVE) else _safe_repr(value)
    return out


def _safe_repr(value: Any) -> str:
    try:
        return truncate(_repr.repr(value), MAX_REPR)
    except Exception:
        return "<unrepresentable>"
