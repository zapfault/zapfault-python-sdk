"""The SDK's own messages, printed to stderr as "[zapfault] ..."."""

import sys

enabled = False
_warned = set()


def debug(message: str) -> None:
    """Prints only with debug=True."""
    if enabled:
        _print(message)


def warn_once(message: str) -> None:
    """Prints even without debug, but each message only once."""
    if message not in _warned:
        _warned.add(message)
        _print("warning: " + message)


def _print(message: str) -> None:
    try:
        print("[zapfault] " + message, file=sys.stderr)
    except Exception:
        pass
