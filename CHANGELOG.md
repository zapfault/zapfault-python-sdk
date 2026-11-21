# Changelog

Versions follow [semver](https://semver.org); while they are 0.x, a minor
release may change the API. A function or option that is going away first
warns with a `DeprecationWarning` and keeps working for at least one more
minor release (one more major release from 1.0).

## Unreleased

### Added
- `init`, `capture_exception`, `capture_message`, `set_user`, `set_tag`,
  `set_tags`, `set_context`, `add_breadcrumb`, `scope`, `flush`, `close`,
  `is_enabled`.
- Uncaught exceptions are reported, in the main thread and in other threads,
  and Python still prints the traceback and exits as it would without the SDK.
- Stack traces with exception chains, source lines and your own frames' local
  variables; secret-looking variables are sent as `[Filtered]`.
- `scope()` keeps data to one block, per thread and per asyncio task.
- Log records at `INFO` and above become breadcrumbs.
- Sending tries again after a network error or a 5xx, pauses when the server
  answers 429 or 503, and uses `HTTPS_PROXY` / `HTTP_PROXY`. What is queued is
  sent when the program exits.
- Options `dsn`, `enabled`, `debug`, `environment`, `release`, `service`,
  `sample_rate`, `transport`, `max_queue_size`, `shutdown_timeout`,
  `before_send`, `include_local_variables`, `in_app_include`,
  `in_app_exclude`, `tags`, `max_breadcrumbs`, `logging_breadcrumbs`,
  `disabled_integrations`, each also read from `ZAPFAULT_*` where it has a
  variable. A misspelled option raises `TypeError`.
- Types `Event`, `Hint`, `User`, `Breadcrumb`, `Request`, `Level`,
  `BreadcrumbType` and `Integration`.
- Flask 2.3+, Django 4.2+ and FastAPI / Starlette 0.27+ are set up by `init`:
  each request has its own scope, and 5xx errors are reported with the route
  and the request; secret headers and query values are left out or filtered.
