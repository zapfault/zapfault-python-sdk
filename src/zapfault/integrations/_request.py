"""The request part of an event, from a WSGI environ (Flask, Django's
request.META) or an ASGI scope (FastAPI). Secrets stay out: no body, cookies
or client IP, credential headers dropped, and values whose names look secret
are filtered."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote, unquote

from .._event import SENSITIVE, truncate

# Credentials, and the client's IP as proxies forward it.
DROPPED_HEADERS = (
    "cookie", "authorization", "proxy-authorization", "x-api-key",
    "x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip", "true-client-ip",
)
MAX_HEADER = 1024
MAX_HEADERS = 100


def from_environ(environ: dict[str, Any], scheme: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Django passes the scheme and path it already worked out: under ASGI its
    META has no wsgi.url_scheme, and paths aren't latin-1 decoded bytes."""
    scheme = scheme or environ.get("wsgi.url_scheme", "http")
    if path is None:
        path = _utf8(environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
    host = environ.get("HTTP_HOST") or _host(environ.get("SERVER_NAME", ""), environ.get("SERVER_PORT"), scheme)
    headers = (
        (key[5:] if key.startswith("HTTP_") else key, value)
        for key, value in environ.items()
        if key.startswith("HTTP_") or key in ("CONTENT_TYPE", "CONTENT_LENGTH")
    )
    return _request(environ.get("REQUEST_METHOD", "GET"), scheme, host, path, environ.get("QUERY_STRING", ""), headers)


def from_asgi(scope: dict[str, Any]) -> dict[str, Any]:
    scheme = scope.get("scheme", "http")
    headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in scope.get("headers", ())]
    host = next((v for k, v in headers if k.lower() == "host"), None) or _host(*(scope.get("server") or ("", None)), scheme)
    query = scope.get("query_string", b"").decode("latin-1")
    return _request(scope.get("method", "GET"), scheme, host, scope.get("path", ""), query, headers)


def _request(method: str, scheme: str, host: str, path: str, query: str, headers: Iterable[tuple[str, str]]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "method": method,
        "url": truncate(f"{scheme}://{host}{quote(path, safe='/:@!$&()*+,;=~-._')}"),
    }
    if query:
        data["query_string"] = truncate(_filter_query(query))
    out: dict[str, str] = {}
    for key, value in headers:
        name = key.replace("_", "-").title()
        lower = name.lower()
        if value and lower not in DROPPED_HEADERS and len(out) < MAX_HEADERS:
            out[name] = "[Filtered]" if _sensitive(lower) else truncate(_utf8(str(value)), MAX_HEADER)
    if out:
        data["headers"] = out
    return data


def _host(name: str, port: Any, scheme: str) -> str:
    if not port or str(port) == {"http": "80", "https": "443"}.get(scheme):
        return name
    return f"{name}:{port}"


def _utf8(value: str) -> str:
    """Servers hand over paths and headers as latin-1 decoded bytes; browsers send UTF-8."""
    try:
        return value.encode("latin-1").decode("utf-8", "replace")
    except UnicodeEncodeError:
        return value


def _filter_query(query: str) -> str:
    parts = []
    for part in query.split("&"):
        key, sep, _ = part.partition("=")
        parts.append(f"{key}=[Filtered]" if sep and _sensitive(unquote(key).lower()) else part)
    return "&".join(parts)


def _sensitive(lower_name: str) -> bool:
    return any(s in lower_name for s in SENSITIVE)
