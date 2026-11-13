"""The settings init resolves: an argument wins, then an ZAPFAULT_* environment
variable, then the default."""

from __future__ import annotations

import os
from typing import Any, Callable

from ._debug import warn_once

# Hosting platforms that set the deployed commit for us.
_RELEASE_VARS = (
    "GITHUB_SHA",
    "VERCEL_GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
    "RAILWAY_GIT_COMMIT_SHA",
    "CF_PAGES_COMMIT_SHA",
)


class Options:
    def __init__(self, args: dict[str, Any]) -> None:
        args = dict(args)
        self.dsn = _get(args, "dsn", str)
        self.enabled = _get(args, "enabled", _bool, True)
        self.debug = _get(args, "debug", _bool, False)
        self.environment = _get(args, "environment", str) or _env("APP_ENV", "ENVIRONMENT") or "production"
        self.release = _get(args, "release", str) or _env(*_RELEASE_VARS)
        self.service = _get(args, "service", str)
        self.sample_rate = _get(args, "sample_rate", _rate, 1.0)
        self.transport = _get(args, "transport", _transport, "http")
        self.max_queue_size = _get(args, "max_queue_size", _count, 100, env=False)
        self.shutdown_timeout = _get(args, "shutdown_timeout", _seconds, 2.0, env=False)
        self.include_local_variables = _get(args, "include_local_variables", _bool, True, env=False)
        self.in_app_include = _get(args, "in_app_include", _names, (), env=False)
        self.in_app_exclude = _get(args, "in_app_exclude", _names, (), env=False)
        for name in args:
            warn_once(f"unknown option {name!r} ignored")


def git_release() -> str | None:
    """The commit checked out where the app runs, for apps deployed from git."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=1, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _get(args: dict[str, Any], name: str, convert: Callable[[Any], Any], default: Any = None, env: bool = True) -> Any:
    value = args.pop(name, None)
    if value is None and env:
        value = os.environ.get("ZAPFAULT_" + name.upper()) or None
    if value is None:
        return default
    try:
        return convert(value)
    except (TypeError, ValueError):
        warn_once(f"invalid {name} {value!r}, using {default!r}")
        return default


def _env(*names: str) -> str | None:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError


def _rate(value: Any) -> float:
    rate = float(value)
    if not 0 <= rate <= 1:
        raise ValueError
    return rate


def _count(value: Any) -> int:
    count = int(value)
    if count < 1:
        raise ValueError
    return count


def _seconds(value: Any) -> float:
    seconds = float(value)
    if seconds < 0:
        raise ValueError
    return seconds


def _names(value: Any) -> tuple[str, ...]:
    """Module name prefixes: one string or a list of them."""
    if isinstance(value, str):
        return (value,)
    return tuple(str(name) for name in value)


def _transport(value: Any) -> str:
    if value not in ("http", "console"):
        raise ValueError
    return value
