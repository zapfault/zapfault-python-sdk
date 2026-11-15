"""Integrations hook a framework the app has installed, so its errors and
requests are reported without extra code. A framework that isn't installed is
never imported."""

from __future__ import annotations

import importlib
import importlib.util

from .._debug import debug

# Integration name -> the package it needs.
AVAILABLE = {"flask": "flask"}

_done: set[str] = set()


def setup(disabled: tuple[str, ...]) -> None:
    """Sets up every installed integration once per process; init calls it."""
    for name, package in AVAILABLE.items():
        if name in disabled or name in _done:
            continue
        try:
            if importlib.util.find_spec(package) is None:
                continue
        except (ImportError, ValueError):
            continue
        _done.add(name)
        try:
            importlib.import_module(f"{__name__}.{name}").setup_once()
        except Exception as e:
            debug(f"the {name} integration failed to start: {e!r}")
