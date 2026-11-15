"""The request part of an event, read from a WSGI environ (Flask, and Django's
request.META). Secrets stay out: no body, cookies or client IP, credential
headers dropped, and values whose names look secret are filtered."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from .._event import SENSITIVE, truncate

# Credentials, and the client's IP as proxies forward it.
DROPPED_HEADERS = (
    "cookie", "authorization", "proxy-authorization", "x-api-key",
    "x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip", "true-client-ip",
)
MAX_HEADER = 1024
MAX_HEADERS = 100


def request_data(environ: dict[str, Any]) -> dict[str, Any]:
    scheme = environ.get("wsgi.url_scheme", "http")
    path = _text(environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
    data: dict[str, Any] = {
        "method": environ.get("REQUEST_METHOD", "GET"),
        "url": truncate(f"{scheme}://{_host(environ, scheme)}{quote(path, safe='/:@!$&()*+,;=~-._')}"),
    }
    query = environ.get("QUERY_STRING", "")
    if query:
        data["query_string"] = truncate(_filter_query(query))
    headers = _headers(environ)
    if headers:
        data["headers"] = headers
    return data


def _host(environ: dict[str, Any], scheme: str) -> str:
    if environ.get("HTTP_HOST"):
        return environ["HTTP_HOST"]
    host, port = environ.get("SERVER_NAME", ""), str(environ.get("SERVER_PORT", ""))
    return host if port in ("", {"http": "80", "https": "443"}.get(scheme)) else f"{host}:{port}"


def _text(value: str) -> str:
    """WSGI gives paths as latin-1 decoded bytes; browsers send UTF-8."""
    try:
        return value.encode("latin-1").decode("utf-8", "replace")
    except UnicodeEncodeError:
        return value


def _headers(environ: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            key = key[5:]
        elif key not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            continue
        if not value or len(out) == MAX_HEADERS:
            continue
        name = key.replace("_", "-").title()
        lower = name.lower()
        if lower in DROPPED_HEADERS:
            continue
        out[name] = "[Filtered]" if _sensitive(lower) else truncate(_text(str(value)), MAX_HEADER)
    return out


def _filter_query(query: str) -> str:
    parts = []
    for part in query.split("&"):
        key, sep, _ = part.partition("=")
        parts.append(f"{key}=[Filtered]" if sep and _sensitive(unquote(key).lower()) else part)
    return "&".join(parts)


def _sensitive(lower_name: str) -> bool:
    return any(s in lower_name for s in SENSITIVE)
