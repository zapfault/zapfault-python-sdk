"""The DSN says where to send events and with which key:
https://<public_key>@<host>[:<port>][/<prefix>]/<project_id>"""

from __future__ import annotations

import re
from typing import NamedTuple
from urllib.parse import urlsplit


class Dsn(NamedTuple):
    public_key: str
    endpoint: str


def parse_dsn(value: str) -> Dsn:
    """Raises ValueError saying what is wrong."""
    url = urlsplit(value.strip())
    if url.scheme not in ("http", "https"):
        raise ValueError("it must start with http:// or https://")
    if not url.hostname:
        raise ValueError("it has no host")
    try:
        url.port
    except ValueError:
        raise ValueError("its port is invalid") from None
    key = url.username or ""
    if not re.fullmatch("[0-9a-f]{32}", key):
        raise ValueError("the public key before @ must be 32 lowercase hex characters")
    prefix, _, project = url.path.rstrip("/").rpartition("/")
    if not re.fullmatch("[0-9]+", project):
        raise ValueError("it must end with the project ID, a number")
    host = url.netloc.rpartition("@")[2]
    return Dsn(key, f"{url.scheme}://{host}{prefix}/ingest/v1/{project}/envelope")
