---
title: Examples
description: Runnable examples from the examples/ directory of the repository.
---

# Examples

Complete programs from [`examples/`](https://github.com/TimurSeyidov/jodit-python/tree/main/examples).
Run them from the repository root, e.g. `uv run python examples/basic.py`;
each module docstring lists `curl` commands to try. Every example is
type-checked and covered by the test suite.

## Basic

Standalone connector configured from a JSON file.

=== "basic.py"

    ```python
    --8<-- "examples/basic.py"
    ```

=== "basic.json"

    ```json
    --8<-- "examples/config/basic.json"
    ```

## Cookie authentication

Role taken from a cookie on every request.

=== "cookie_auth.py"

    ```python
    --8<-- "examples/cookie_auth.py"
    ```

=== "roles.json"

    ```json
    --8<-- "examples/config/roles.json"
    ```

## JWT authentication

Role from a signed JWT (PyJWT); bad tokens get `401`.

=== "jwt_auth.py"

    ```python
    --8<-- "examples/jwt_auth.py"
    ```

=== "roles.json"

    ```json
    --8<-- "examples/config/roles.json"
    ```

## Session authentication

Role kept in a signed Starlette session, with login and logout routes; the closest analog of PHP `$_SESSION` and express-session.

=== "session_auth.py"

    ```python
    --8<-- "examples/session_auth.py"
    ```

=== "roles.json"

    ```json
    --8<-- "examples/config/roles.json"
    ```

## Custom SVG icons

Thumbnails of folders and non-image files drawn by your function.

=== "custom_svg.py"

    ```python
    --8<-- "examples/custom_svg.py"
    ```

=== "svg.json"

    ```json
    --8<-- "examples/config/svg.json"
    ```

## Several instances

A public read-only connector and an admin one in the same application.

```python
--8<-- "examples/multi_instance.py"
```

## S3

Files in an S3 bucket.

=== "s3.py"

    ```python
    --8<-- "examples/s3.py"
    ```

=== "s3.json"

    ```json
    --8<-- "examples/config/s3.json"
    ```

## Multi-tenant

Sources picked per request from a header.

=== "multi_tenant.py"

    ```python
    --8<-- "examples/multi_tenant.py"
    ```

=== "tenants.json"

    ```json
    --8<-- "examples/config/tenants.json"
    ```

## Custom storage adapter

An in-memory adapter registered by name.

=== "custom_storage.py"

    ```python
    --8<-- "examples/custom_storage.py"
    ```

=== "memory.json"

    ```json
    --8<-- "examples/config/memory.json"
    ```
