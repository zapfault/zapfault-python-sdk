"""Sending envelopes. HttpTransport posts them from a background thread, so a
capture never waits on the network; ConsoleTransport prints them instead."""

from __future__ import annotations

import gzip
import json
import os
import queue
import random
import sys
import threading
import time
from datetime import datetime, timezone

from ._debug import debug, warn_once
from ._dsn import Dsn
from ._version import __version__

USER_AGENT = f"zapfault.python/{__version__}"
ATTEMPTS = 3
DEFAULT_PAUSE = 60.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class HttpTransport:
    def __init__(self, dsn: Dsn, max_queue_size: int) -> None:
        self._dsn = dsn
        self._max_queue_size = max_queue_size
        self._closed = False
        self._paused_until = 0.0  # set by a 429 or 503 answer
        self._reset()

    def _reset(self) -> None:
        # After a fork the child has a copy of the queue but not the thread
        # (and maybe a copy of a lock held by it), so it starts over.
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(self._max_queue_size)
        self._thread: threading.Thread | None = None

    def send(self, envelope: dict) -> None:
        """Queues the envelope and returns at once; a full queue drops it."""
        if self._closed:
            return
        if self._paused():
            return
        if self._pid != os.getpid():
            self._reset()
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="zapfault-transport", daemon=True)
                self._thread.start()
        try:
            self._queue.put_nowait(envelope)
        except queue.Full:
            debug("the send queue is full, an envelope was dropped")

    def flush(self, timeout: float) -> bool:
        """Waits until the queue is sent, at most timeout seconds."""
        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._queue.all_tasks_done.wait(left)
        return True

    def close(self, timeout: float) -> bool:
        sent = self.flush(timeout)
        self._closed = True
        try:
            self._queue.put_nowait(None)  # tells the thread to stop
        except queue.Full:
            pass
        return sent

    def _run(self) -> None:
        while True:
            envelope = self._queue.get()
            try:
                if envelope is None:
                    return
                self._deliver(envelope)
            except Exception as e:
                debug(f"sending failed: {e!r}")
            finally:
                self._queue.task_done()

    def _paused(self) -> bool:
        if time.monotonic() < self._paused_until:
            debug("the server asked to wait, an envelope was dropped")
            return True
        return False

    def _deliver(self, envelope: dict) -> None:
        """Posts the envelope, trying again after a network error or a 5xx."""
        for attempt in range(ATTEMPTS):
            if self._paused():
                return
            if attempt:
                wait = 2 ** (attempt - 1) + random.random() / 2  # 1 s, then 2 s
                debug(f"trying again in {wait:.1f} s")
                time.sleep(wait)
            status, retry_after = self._post(envelope)
            if status in (429, 503):
                self._paused_until = time.monotonic() + retry_after
                debug(f"pausing for {retry_after:g} s")
                return
            if status == 401:
                warn_once("the server rejected the DSN's public key (401), check the DSN")
                return
            if status is not None and status < 500:
                return  # sent, or a 4xx: sending it again would fail the same way
        debug(f"the envelope was dropped after {ATTEMPTS} attempts")

    def _post(self, envelope: dict) -> tuple[int | None, float]:
        """Returns the status (None for a network error) and Retry-After."""
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        # Set now, not at capture: the server compares it with its own clock
        # to correct events from machines whose clock is wrong.
        envelope["sent_at"] = utc_now()
        body = json.dumps(envelope, separators=(",", ":"), default=str).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Zapfault-Key": self._dsn.public_key,
            "User-Agent": USER_AGENT,
        }
        if len(body) > 1024:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        request = Request(self._dsn.endpoint, body, headers, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                debug(f"sent, the server answered {response.status}")
                return response.status, 0
        except HTTPError as e:
            detail = e.read(500).decode(errors="replace")
            debug(f"the server answered {e.code}: {detail}")
            return e.code, _retry_after(e.headers.get("Retry-After"))
        except OSError as e:
            debug(f"could not reach the server: {e}")
            return None, 0


def _retry_after(value: str | None) -> float:
    try:
        seconds = float(value or "")
    except ValueError:
        return DEFAULT_PAUSE
    return seconds if seconds > 0 else DEFAULT_PAUSE


class ConsoleTransport:
    """transport="console": prints each envelope to stderr, for development."""

    def send(self, envelope: dict) -> None:
        envelope["sent_at"] = utc_now()
        print(json.dumps(envelope, indent=2, default=str), file=sys.stderr)

    def flush(self, timeout: float) -> bool:
        return True

    def close(self, timeout: float) -> bool:
        return True
