# owlbeam

Error tracking for Python apps. Sends events to [Owlbeam](https://owlbeam.dev).
Python 3.9+, no dependencies.

```sh
pip install owlbeam
```

## Usage

Call `init` once, as early as possible when your app starts. The DSN is on your
project's setup page in Owlbeam.

```python
import owlbeam

owlbeam.init(dsn="https://<public_key>@ingest.owlbeam.dev/<project_id>")
```

From then on, an exception nobody catches is reported, in the main thread or
any other thread. Python still prints the traceback and exits as before.

To report an error you handle yourself, or just a message:

```python
try:
    charge(order)
except PaymentError:
    owlbeam.capture_exception()

owlbeam.capture_message("Payment provider is slow", level="warning")
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

## Options

Each option can be passed to `init` or set in the environment. An argument wins
over the environment variable.

| Option | Environment variable | Default |
|---|---|---|
| `dsn` | `OWLBEAM_DSN` | none: the SDK is off |
| `enabled` | `OWLBEAM_ENABLED` | `True` |
| `environment` | `OWLBEAM_ENVIRONMENT`, then `APP_ENV`, `ENVIRONMENT` | `"production"` |
| `release` | `OWLBEAM_RELEASE`, then your host's commit variable (`GITHUB_SHA`, `VERCEL_GIT_COMMIT_SHA`, …), then `git rev-parse HEAD` | none |
| `service` | `OWLBEAM_SERVICE` | none |
| `debug` | `OWLBEAM_DEBUG` | `False`: prints what the SDK does |
| `sample_rate` | `OWLBEAM_SAMPLE_RATE` | `1.0`: the share of events sent |
| `transport` | `OWLBEAM_TRANSPORT` | `"http"`; `"console"` prints events instead of sending them |
| `max_queue_size` | | `100`: events waiting to be sent; more are dropped |
| `shutdown_timeout` | | `2.0` seconds |
| `include_local_variables` | | `True`: send your own frames' local variables |
| `in_app_include` | | Module prefixes that count as your code, such as a library you wrote |
| `in_app_exclude` | | Module prefixes that don't count as your code |

## Functions

| Function | |
|---|---|
| `init(dsn=None, **options)` | Turns the SDK on. Calling it again replaces the earlier setup. |
| `capture_exception(error=None)` | Sends an exception; without one, the exception being handled in the current `except` block. Returns the event ID. |
| `capture_message(message, level="info")` | Sends a message. `level` is `fatal`, `error`, `warning`, `info` or `debug`. Returns the event ID. |
| `flush(timeout=2.0)` | Waits until everything captured so far is sent. Use it before a short script or a serverless function ends. |
| `close(timeout=2.0)` | Flushes, then turns the SDK off. |
| `is_enabled()` | Whether the SDK is on. |
