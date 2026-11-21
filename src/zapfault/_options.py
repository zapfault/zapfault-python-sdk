"""The settings init resolves: an argument wins, then an ZAPFAULT_* environment
variable, then the default."""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

from ._debug import warn_once
from ._protocol import BeforeSend

T = TypeVar("T")

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
    """init's arguments, None where not given. The types already rule out most
    mistakes; values are still checked, as they also come from the
    environment and from untyped code."""

    def __init__(self, args: dict[str, Any]) -> None:
        self.dsn: str | None = _get(args, "dsn", str, None)
        self.enabled: bool = _get(args, "enabled", _bool, True)
        self.debug: bool = _get(args, "debug", _bool, False)
        self.environment: str = _get(args, "environment", str, None) or _env("APP_ENV", "ENVIRONMENT") or "production"
        self.release: str | None = _get(args, "release", str, None) or _env(*_RELEASE_VARS)
        self.service: str | None = _get(args, "service", str, None)
        self.sample_rate: float = _get(args, "sample_rate", _rate, 1.0)
        self.transport: str = _get(args, "transport", _transport, "http")
        self.max_queue_size: int = _get(args, "max_queue_size", _count, 100, env=False)
        self.shutdown_timeout: float = _get(args, "shutdown_timeout", _seconds, 2.0, env=False)
        self.before_send: BeforeSend | None = _get(args, "before_send", _callable, None, env=False)
        self.include_local_variables: bool = _get(args, "include_local_variables", _bool, True, env=False)
        self.in_app_include: tuple[str, ...] = _get(args, "in_app_include", _names, (), env=False)
        self.in_app_exclude: tuple[str, ...] = _get(args, "in_app_exclude", _names, (), env=False)
        self.tags: dict[str, Any] = _get(args, "tags", dict, {}, env=False)
        self.max_breadcrumbs: int = _get(args, "max_breadcrumbs", _breadcrumbs, 100, env=False)
        self.logging_breadcrumbs: bool = _get(args, "logging_breadcrumbs", _bool, True, env=False)
        self.disabled_integrations: tuple[str, ...] = _get(args, "disabled_integrations", _names, (), env=False)


def git_release() -> str | None:
    """The commit checked out where the app runs, for apps deployed from git."""
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=1, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _get(args: dict[str, Any], name: str, convert: Callable[[Any], T], default: T, env: bool = True) -> T:
    value = args.get(name)
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


def _breadcrumbs(value: Any) -> int:
    count = int(value)
    if not 0 <= count <= 100:
        raise ValueError
    return count


def _names(value: Any) -> tuple[str, ...]:
    """Names or module prefixes: one string or a list of them."""
    if isinstance(value, str):
        return (value,)
    return tuple(str(name) for name in value)


def _callable(value: Any) -> Any:
    if not callable(value):
        raise TypeError
    return value


def _transport(value: Any) -> str:
    if value not in ("http", "console"):
        raise ValueError
    return str(value)
