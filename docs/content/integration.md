---
title: FastAPI Integration
description: Standalone mode, mounting into an existing application, path prefixes and several isolated instances.
---

# FastAPI Integration

## 1. Standalone application

```python
from jcpy import create_app

app = create_app("config.json")
```

Routes: `GET /ping`, and `GET`/`POST`/`OPTIONS` on `/` (action in the
`action` parameter) and `/{action}`.

## 2. Inside an existing application

```python
from fastapi import FastAPI

from jcpy import create_router

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


# Your routes first: the connector answers every other /{name}.
app.include_router(create_router("config.json"))
```

Now `GET /health` is yours, `GET /?action=files` and `GET /files` are
the connector's.

!!! warning "Route order"
    The connector's `/{action}` route matches any single path segment.
    Register your own routes before including the router, or mount the
    connector under a prefix.

FastAPI's own `/docs` and `/openapi.json` also collide with
`/{action}`; `create_app()` disables them. In your application either
keep them and mount the connector under a prefix, or disable them:
`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`. The
connector's documented API is the [OpenAPI document](api-swagger/index.md)
generated from its schemas.

## 3. Under a path prefix

```python
app.include_router(create_router("config.json"), prefix="/api/files")
```

```text
GET  /api/files/ping
GET  /api/files/?action=files     or  GET /api/files/files
POST /api/files/?action=fileUpload
```

## 4. Middleware and sessions

Middleware of your application runs for the connector too, so the
authentication callback can use what it prepared: a session, a user
loaded by an auth middleware, request state. With Starlette sessions:

```python
--8<-- "examples/session_auth.py:build"
```

The whole program is [`examples/session_auth.py`](examples.md).

## 5. Several instances

Each `create_router()` call is an isolated instance with its own
configuration, authentication and caches:

```python
--8<-- "examples/multi_instance.py:build"
```

`public.json` denies every modifying action; `admin.json` gives nothing
to the `anonymous` default role and everything to `admin`:

=== "public.json"

    ```json
    --8<-- "examples/config/public.json"
    ```

=== "admin.json"

    ```json
    --8<-- "examples/config/admin.json"
    ```

Instances never share state, which a test checks under concurrent
requests to both.

## Key points

- Every instance has its own configuration, sources, access rules and
  callbacks.
- Middleware of the host application applies to all instances.
- Unlike jodit-nodejs (where the callback is set on the Express app),
  callbacks are arguments of `create_router()`, so instances in one
  application can authenticate differently.
