"""Sending envelopes. HttpTransport posts them from a background thread, so a
capture never waits on the network, over one connection it keeps open while
events keep coming (no new TLS handshake per event); ConsoleTransport prints
them instead."""

from __future__ import annotations

import base64
import gzip
import json
import os
import queue
import random
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from ._debug import debug, warn_once
from ._dsn import Dsn
from ._protocol import Envelope
from ._version import __version__

USER_AGENT = f"zapfault.python/{__version__}"
ATTEMPTS = 3
DEFAULT_PAUSE = 60.0
TIMEOUT = 5.0
IDLE_CLOSE = 30.0  # close the connection after this long without events (the server waits 60 s)
MAX_AGE = 300.0  # and open a new one at least this often, so it follows DNS and load balancers


class Transport(Protocol):
    def send(self, envelope: Envelope) -> None: ...
    def flush(self, timeout: float) -> bool: ...
    def close(self, timeout: float) -> bool: ...


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
        self._queue: queue.Queue[Envelope | None] = queue.Queue(self._max_queue_size)
        self._thread: threading.Thread | None = None
        # Used by the sender thread only: the connection, the path to post to,
        # headers a proxy needs, and when it was opened.
        self._conn: Any = None
        self._path: str = ""
        self._extra: dict[str, str] = {}
        self._opened = 0.0

    def send(self, envelope: Envelope) -> None:
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
            try:
                envelope = self._queue.get(timeout=IDLE_CLOSE if self._conn else None)
            except queue.Empty:
                self._disconnect("idle")  # the next event opens a new one
                continue
            try:
                if envelope is None:
                    self._disconnect("closing")
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

    def _deliver(self, envelope: Envelope) -> None:
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

    def _post(self, envelope: Envelope) -> tuple[int | None, float]:
        """Returns the status (None for a network error) and Retry-After."""
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
        # A kept-open connection the server closed meanwhile fails before the
        # request gets there; that one is sent again at once on a new connection.
        for stale_retry in (True, False):
            reused = self._conn is not None
            try:
                status, retry_after, detail = self._request(body, headers)
            except Exception as e:
                self._disconnect("failed")
                if reused and stale_retry and isinstance(e, ConnectionError):
                    continue
                debug(f"could not reach the server: {e!r}")
                return None, 0
            if status >= 300:
                debug(f"the server answered {status}: {detail[:500].decode(errors='replace')}")
                return status, _retry_after(retry_after)
            debug(f"sent, the server answered {status}")
            return status, 0
        return None, 0

    def _request(self, body: bytes, headers: dict[str, str]) -> tuple[int, str | None, bytes]:
        if self._conn is not None and time.monotonic() - self._opened > MAX_AGE:
            self._disconnect("too old")
        if self._conn is None:
            self._conn, self._path, self._extra = _connect(self._dsn.endpoint)
            self._opened = time.monotonic()
        self._conn.request("POST", self._path, body, {**headers, **self._extra})
        response = self._conn.getresponse()
        detail = response.read()  # all of it, or the connection can't be used again
        return response.status, response.getheader("Retry-After"), detail

    def _disconnect(self, why: str) -> None:
        if self._conn is not None:
            debug(f"connection closed ({why})")
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def _connect(endpoint: str) -> tuple[Any, str, dict[str, str]]:
    """A connection to the server, or through the proxy that HTTPS_PROXY,
    HTTP_PROXY or the system names for it; the path to post to; and headers
    for the proxy."""
    import http.client
    from urllib.request import getproxies, proxy_bypass

    url = urlsplit(endpoint)
    host = url.hostname or ""
    https = url.scheme == "https"
    connection = http.client.HTTPSConnection if https else http.client.HTTPConnection
    proxy = None if proxy_bypass(host) else getproxies().get(url.scheme)
    if not proxy:
        debug(f"connecting to {url.netloc}")
        return connection(host, url.port, timeout=TIMEOUT), url.path, {}
    p = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    auth = {}
    if p.username:
        token = base64.b64encode(f"{unquote(p.username)}:{unquote(p.password or '')}".encode()).decode()
        auth = {"Proxy-Authorization": f"Basic {token}"}
    debug(f"connecting to {url.netloc} through the proxy {p.hostname}")
    conn = connection(p.hostname or "", p.port or 8080, timeout=TIMEOUT)
    if https:  # a CONNECT tunnel, with TLS to the server inside it
        conn.set_tunnel(host, url.port or 443, headers=auth)
        return conn, url.path, {}
    return conn, endpoint, auth  # plain HTTP: the proxy gets the full URL


def _retry_after(value: str | None) -> float:
    try:
        seconds = float(value or "")
    except ValueError:
        return DEFAULT_PAUSE
    return seconds if seconds > 0 else DEFAULT_PAUSE


class ConsoleTransport:
    """transport="console": prints each envelope to stderr, for development."""

    def send(self, envelope: Envelope) -> None:
        envelope["sent_at"] = utc_now()
        print(json.dumps(envelope, indent=2, default=str), file=sys.stderr)

    def flush(self, timeout: float) -> bool:
        return True

    def close(self, timeout: float) -> bool:
        return True
