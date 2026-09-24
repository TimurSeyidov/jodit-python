---
title: Python API
description: create_app, create_router, the callbacks they accept and the Connector class.
---

# Python API

Everything below is importable from `jcpy`.

## `create_app()`

Builds a standalone FastAPI application with the connector mounted at
`/` and the `X-App-version` response header.

```python
from jcpy import create_app

app = create_app("config.json")
```

## `create_router()`

Builds one connector instance as an `APIRouter`, to mount into your own
application (see [FastAPI Integration](integration.md)):

```python
from fastapi import FastAPI

from jcpy import create_router

app = FastAPI()
app.include_router(create_router("config.json"), prefix="/connector")
```

Every call creates an independent instance: its own configuration,
callbacks, access rules, sources and caches.

## Arguments

Both functions take the same arguments; only `config_file` is
positional.

| Argument | Type | Meaning |
|---|---|---|
| `config_file` | `str \| Path \| None` | JSON configuration; when omitted `CONFIG` and `CONFIG_FILE` are read ([details](installation.md#configuration-sources)) |
| `check_authentication` | `AuthCallback` | Returns the role of the request's user; without it every request gets `defaultRole` ([Authentication](authentication.md)) |
| `allowed_origins` | `OriginPredicate` | Decides CORS origins; replaces the `allowedOrigins` list |
| `access_control` | `RulesProvider` | Loads access rules on every check; replaces the `accessControl` list ([Access Control](access-control.md#rules-loaded-at-runtime)) |
| `access_control_instance` | `AccessControlProtocol` | Custom access control; replaces both rule sources ([details](access-control.md#custom-implementation)) |
| `svg_generator` | `SvgGenerator` | Renders icons of folders and non-image files ([details](config.md#svg-icons)) |
| `resolve_sources` | `SourcesResolver` | Picks sources per request ([Dynamic Sources](dynamic-sources.md)) |

Every callback may be a plain function or a coroutine function (except
`svg_generator`, which is always synchronous):

```python
from collections.abc import Awaitable, Callable

from starlette.requests import Request

type AuthCallback = Callable[[Request], str | Awaitable[str]]
type OriginPredicate = Callable[[str, Request], bool | Awaitable[bool]]
type RulesProvider = Callable[
    [], Sequence[AccessControlRule] | Awaitable[Sequence[AccessControlRule]]
]
type SvgGenerator = Callable[[StatEntry, int, int], str]
type SourcesResolver = Callable[
    [Request], ResolvedSources | None | Awaitable[ResolvedSources | None]
]
```

!!! warning "Open by default"
    Without `check_authentication` and without access rules every
    client may run every action, as in jodit-nodejs. The connector logs
    a warning at start in that case.

## Errors

Raise `HttpError` from any callback to answer with that status and the
connector's error envelope:

```python
from http import HTTPStatus

from jcpy import HttpError

raise HttpError(HTTPStatus.UNAUTHORIZED, "Invalid or expired token")
raise HttpError.forbidden("Unknown tenant")  # 403
raise HttpError.not_found("No such project")  # 404
raise HttpError.bad_request("Bad header")  # 400
```

```json
{"success": false, "data": {"code": 401, "messages": ["Invalid or expired token"]}}
```

Any other exception becomes `500` with the exception text as the
message; with `debug: true` the traceback is logged to the `jcpy`
logger.

## Configuration objects

- `load_config(config_file=None) -> AppConfig` reads the configuration
  the way `create_app()` does.
- `AppConfig` and `SourceConfig` are the validated (frozen) Pydantic
  models; attributes are snake_case (`config.max_upload_file_size`),
  JSON keys camelCase.
- `AccessControlRule` is one access rule.

## `Connector`

The class behind both factories, for code that needs the instance
itself:

```python
from jcpy import Connector, load_config

connector = Connector(load_config("config.json"), check_authentication=auth)
app.include_router(connector.build_router(), prefix="/files")

# Later, e.g. after tenant credentials were rotated:
connector.clear_dynamic_sources()
```

It takes the configuration model and the same keyword arguments as
`create_router()`.

## Logging

Messages go to the standard `logging` logger `jcpy`: the open-access
warning at start, failed requests when `debug` is on, sources skipped by
access rules.

```python
import logging

logging.getLogger("jcpy").setLevel(logging.WARNING)
```
