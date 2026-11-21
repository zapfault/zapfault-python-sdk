"""What the SDK sends, as types: the wire format of docs/PROTOCOL.md. Written
with Optional and Union rather than "X | None": TypedDict fields are
evaluated when the module loads, and Python 3.9 has no "|" for types."""

from typing import Any, Callable, Literal, Optional, TypedDict, Union

Level = Literal["fatal", "error", "warning", "info", "debug"]
BreadcrumbType = Literal["default", "http", "navigation", "ui", "query", "log"]
Integration = Literal["flask", "django", "fastapi"]


class Frame(TypedDict, total=False):
    filename: str
    abs_path: str
    function: str
    module: str
    lineno: int
    in_app: bool
    pre_context: list[str]
    context_line: str
    post_context: list[str]
    vars: dict[str, str]


class Mechanism(TypedDict):
    type: str
    handled: bool


class Stacktrace(TypedDict, total=False):
    frames: list[Frame]
    frames_omitted: tuple[int, int]


class _ExceptionType(TypedDict):
    type: str


class ExceptionValue(_ExceptionType, total=False):
    """One exception of the chain: root cause first, the raised one last."""

    module: str
    value: str
    mechanism: Mechanism
    stacktrace: Stacktrace


class Exceptions(TypedDict):
    values: list[ExceptionValue]


class User(TypedDict, total=False):
    """Who was affected."""

    id: Union[str, int]
    email: str
    username: str
    ip_address: str
    attributes: dict[str, Any]
    """Anything else about them, like {"plan": "pro"}."""


class EventUser(TypedDict, total=False):
    id: str
    email: str
    username: str
    ip_address: str
    attributes: dict[str, Any]


class Breadcrumb(TypedDict, total=False):
    """Something that happened; the latest ones are sent with the next error."""

    timestamp: str
    message: str
    category: str
    level: Level
    type: BreadcrumbType
    data: dict[str, Any]


class Request(TypedDict, total=False):
    """The request being handled, without secrets: no body or cookies, credential headers dropped."""

    method: str
    url: str
    """Without the query string."""
    query_string: str
    headers: dict[str, str]


class _EventRequired(TypedDict):
    type: Literal["error"]
    event_id: str
    timestamp: str
    level: Level
    platform: Literal["python"]


class Event(_EventRequired, total=False):
    """One error or message, as before_send sees it."""

    message: str
    exception: Exceptions
    user: EventUser
    tags: dict[str, str]
    contexts: dict[str, Any]
    breadcrumbs: list[Breadcrumb]
    route: str
    """The route or job being handled, as written: "GET /orders/<int:order_id>"."""
    request: Request
    _meta: dict[str, Any]


class Hint(TypedDict):
    """What before_send gets with an event."""

    original_exception: Optional[BaseException]
    """The exception that was captured; None for a message."""


BeforeSend = Callable[[Event, Hint], Optional[Event]]


class Resource(TypedDict, total=False):
    service: str
    release: str
    environment: str
    host: str
    runtime: dict[str, str]
    os: dict[str, str]


class Envelope(TypedDict, total=False):
    protocol: int
    sent_at: str
    sdk: dict[str, str]
    resource: Resource
    items: list[Event]
