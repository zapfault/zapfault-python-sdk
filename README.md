# zapfault

Error tracking for Python apps. Sends events to [Zapfault](https://zapfault.com).
Python 3.9+, no dependencies.

```sh
pip install zapfault
```

## Usage

Call `init` once, as early as possible when your app starts. The DSN is on your
project's setup page in Zapfault.

```python
import zapfault

zapfault.init(dsn="https://<public_key>@ingest.zapfault.com/<project_id>")
```

From then on, an exception nobody catches is reported, in the main thread or
any other thread. Python still prints the traceback and exits as before.

To report an error you handle yourself, or just a message:

```python
try:
    charge(order)
except PaymentError:
    zapfault.capture_exception()

zapfault.capture_message("Payment provider is slow", level="warning")
```

Each error comes with its stack trace: the source lines around each call and
the local variables of your own code. A variable whose name looks secret
(`password`, `token`, `api_key`, …) is sent as `[Filtered]`.

Events are sent from a background thread, so capturing never waits on the
network. A failed send is tried again twice; when the server asks the SDK to
wait, it drops events until then. Whatever is still queued is sent when the
program exits (for up to `shutdown_timeout` seconds).

The SDK never raises and never stops your app. With no DSN or `enabled=False`
it does nothing, and with an invalid DSN it prints one warning and does
nothing.

## Adding context

Tell Zapfault who was affected and what was going on. Whatever you set is sent
with every error that follows:

```python
zapfault.set_user({"id": "4821", "email": "asha@example.com"})   # None clears it
zapfault.set_tag("plan", "pro")                                   # searchable; None removes it
zapfault.set_tags({"tenant": "acme", "feature": "checkout"})
zapfault.set_context("cart", {"items": 3, "total": 49.99})        # shown on the event, not searchable
zapfault.add_breadcrumb(message="applied coupon", category="cart", data={"code": "SAVE10"})
```

Set the values where your code knows them, so they can differ per user or per
request. Tags that are the same for the whole process go in `init`:
`zapfault.init(tags={"region": "eu"})`.

Tag keys are 1 to 32 letters, digits, `_`, `.`, `:` or `-`; values are cut at
200 characters, and at most 50 tags are kept.

**Breadcrumbs** are the steps that led up to an error: the last 100 are sent
with it. Besides your own, every log record at `INFO` or above becomes one, as
far as your logging level lets it through (the default level is `WARNING`).

**Data for one block only:** inside `zapfault.scope()`, changes stay in the
block. An error raised in the block keeps its data even when it is caught (or
crashes the program) after the block.

```python
with zapfault.scope() as scope:
    scope.set_tag("job", "nightly-sync")
    run_sync()
```

Each thread and each asyncio task sees its own data inside a `scope()` block,
so concurrent work never mixes. In a web app, every request needs its own
block: the framework integrations below open one per request for you.

## Flask

Flask 2.3 or newer is set up by `init` on its own, before or after you create
the app:

```python
import zapfault
from flask import Flask

zapfault.init(dsn="...")
app = Flask(__name__)


@app.before_request
def identify():
    if current_user.is_authenticated:
        zapfault.set_user({"id": current_user.id})   # for this request only
```

- Every request has its own scope: the user, tags and breadcrumbs set while
  handling it never show on another request's errors.
- An error that a route turns into a 500 is reported as unhandled. HTTP errors
  such as `abort(404)` aren't, and neither are errors your own
  `@app.errorhandler` handles: call `zapfault.capture_exception(error)` there
  to report them.
- Events show the route as written (`GET /orders/<int:order_id>`), the method,
  URL, query string and headers. The body, cookies and the client's IP are
  never sent; `Cookie`, `Authorization` and forwarded-IP headers are left out,
  and headers or query parameters with secret-looking names are sent as
  `[Filtered]`.

Turn it off with `disabled_integrations=["flask"]`.

## Options

Each option can be passed to `init` or set in the environment. An argument wins
over the environment variable.

| Option | Environment variable | Default |
|---|---|---|
| `dsn` | `ZAPFAULT_DSN` | none: the SDK is off |
| `enabled` | `ZAPFAULT_ENABLED` | `True` |
| `environment` | `ZAPFAULT_ENVIRONMENT`, then `APP_ENV`, `ENVIRONMENT` | `"production"` |
| `release` | `ZAPFAULT_RELEASE`, then your host's commit variable (`GITHUB_SHA`, `VERCEL_GIT_COMMIT_SHA`, …), then `git rev-parse HEAD` | none |
| `service` | `ZAPFAULT_SERVICE` | none |
| `debug` | `ZAPFAULT_DEBUG` | `False`: prints what the SDK does |
| `sample_rate` | `ZAPFAULT_SAMPLE_RATE` | `1.0`: the share of events sent |
| `transport` | `ZAPFAULT_TRANSPORT` | `"http"`; `"console"` prints events instead of sending them |
| `max_queue_size` | | `100`: events waiting to be sent; more are dropped |
| `shutdown_timeout` | | `2.0` seconds |
| `include_local_variables` | | `True`: send your own frames' local variables |
| `in_app_include` | | Module prefixes that count as your code, such as a library you wrote |
| `in_app_exclude` | | Module prefixes that don't count as your code |
| `tags` | | Tags sent with every event, like `{"region": "eu"}` |
| `max_breadcrumbs` | | `100`: breadcrumbs kept for the next error (0 to 100) |
| `logging_breadcrumbs` | | `True`: log records at `INFO` and above become breadcrumbs |
| `disabled_integrations` | | Integrations to leave off, like `["flask"]` |

## Functions

| Function | |
|---|---|
| `init(dsn=None, **options)` | Turns the SDK on. Calling it again replaces the earlier setup. |
| `capture_exception(error=None)` | Sends an exception; without one, the exception being handled in the current `except` block. Returns the event ID. |
| `capture_message(message, level="info")` | Sends a message. `level` is `fatal`, `error`, `warning`, `info` or `debug`. Returns the event ID. |
| `flush(timeout=2.0)` | Waits until everything captured so far is sent. Use it before a short script or a serverless function ends. |
| `close(timeout=2.0)` | Flushes, then turns the SDK off. |
| `is_enabled()` | Whether the SDK is on. |
| `set_user(user)` | Who was affected: `id`, `email`, `username`, `ip_address`; other keys are kept as attributes. `None` clears it. |
| `set_tag(key, value)`, `set_tags(tags)` | Searchable key and value pairs. `None` removes a tag. |
| `set_context(name, value)` | A dict shown on the event. `None` removes it. |
| `add_breadcrumb(message=None, category=None, level="info", data=None, type="default")` | Records a step that led up to an error. |
| `scope()` | A `with` block whose changes stay inside it. The scope it gives has the same `set_*` and `add_breadcrumb` methods. |
