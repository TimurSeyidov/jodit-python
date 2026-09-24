---
title: Authentication
description: The check_authentication callback, with cookie, JWT and session examples.
---

# Authentication

## Overview

The connector does not log users in. Your application does, and tells the connector the **role** of the user on every request through the `check_authentication` callback. The role then selects the [access rules](access-control.md).

Every request is authenticated on its own, so one connector serves different users with different roles at the same time.

### Request pipeline

1. `onlyPOST` guard
2. `GET /ping` answers here
3. CORS (preflight requests end here)
4. [`resolve_sources`](dynamic-sources.md) (multi-tenant)
5. **`check_authentication`** → role
6. Parameters are parsed
7. Access check of the action for the role
8. Action

## The callback

```python
type AuthCallback = Callable[[Request], str | Awaitable[str]]
```

- Receives the Starlette `Request` (headers, cookies, `request.session`, `request.state`...).
- Returns the role as a string. Plain functions and coroutine functions both work.
- Raise [`HttpError`](usage.md#errors) to reject the request with a status of your choice (`401`, `403`...). Any other exception becomes `500`; so does a non-string result.
- Without the callback every request gets [`defaultRole`](config.md#defaultRole) (`guest`).

```python
from starlette.requests import Request

from jcpy import create_app


async def check_authentication(request: Request) -> str:
    token = request.headers.get("authorization")
    if token is None:
        return "guest"
    user = await users.by_token(token)  # your code
    return user.role


app = create_app("config.json", check_authentication=check_authentication)
```

!!! note "Role only"
    The callback returns a role, not a user. Per-user folders are made with [dynamic sources](dynamic-sources.md), which also receive the request.

## Cookie

The role comes from a cookie. The client can set any cookie, so use this only where the client is trusted, or keep the role server side (sessions, below).

```python
--8<-- "examples/cookie_auth.py:build"
```

```bash
curl "http://localhost:8081/?action=permissions&source=uploads"
curl -H "Cookie: userRole=editor" "http://localhost:8081/?action=permissions&source=uploads"
```

Full program: [`examples/cookie_auth.py`](examples.md#cookie-authentication).

## JWT

The token is verified (signature, expiry, required claims) with [PyJWT](https://pyjwt.readthedocs.io/); a bad token is answered with `401`.

```python
--8<-- "examples/jwt_auth.py:build"
```

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8081/?action=permissions&source=uploads"
```

Full program: [`examples/jwt_auth.py`](examples.md#jwt-authentication).

## Session

The role lives in a session signed by the server, set by your login route. The connector is mounted into the application that owns the middleware:

```python
--8<-- "examples/session_auth.py:build"
```

```bash
curl -c cookies.txt http://localhost:8081/login/editor
curl -b cookies.txt "http://localhost:8081/?action=permissions&source=uploads"
curl -b cookies.txt http://localhost:8081/logout
```

Full program: [`examples/session_auth.py`](examples.md#session-authentication).

## Database lookup

```python
from http import HTTPStatus

from starlette.requests import Request

from jcpy import HttpError


async def check_authentication(request: Request) -> str:
    api_key = request.headers.get("x-api-key")
    if api_key is None:
        return "guest"
    row = await db.fetchrow(
        "SELECT role FROM api_keys WHERE key = $1 AND active", api_key
    )
    if row is None:
        raise HttpError(HTTPStatus.UNAUTHORIZED, "Invalid API key")
    return row["role"]
```

The callback runs on every request; cache lookups that are expensive.

## Security practices

1. **Use HTTPS** so tokens and cookies cannot be read on the way.
2. **Verify, do not decode.** Check signatures and expiry of tokens; never trust a role the client sent in plain form.
3. **Keep secrets out of code**: read signing keys from the environment or a secret store.
4. **Deny by default.** Give `defaultRole` (the role of anonymous requests) as little as possible, and allow more per role; see [Access Control](access-control.md).
5. **Rate-limit** login and upload endpoints at the proxy or with middleware.
6. **Consider [`onlyPOST`](config.md#onlyPOST)** when cookies authenticate requests: it keeps other sites from triggering actions with plain links and images.
7. **Restrict CORS** with [`allowedOrigins`](config.md#allowedOrigins) when `allowCrossOrigin` is on, especially together with cookies (credentials are allowed for accepted origins).
