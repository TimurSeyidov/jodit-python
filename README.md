# jodit-python

[![Version](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2FTimurSeyidov%2Fjodit-python%2Fmain%2Fpyproject.toml&query=%24.project.version&label=version)](pyproject.toml)
[![CI](https://github.com/TimurSeyidov/jodit-python/actions/workflows/ci.yml/badge.svg)](https://github.com/TimurSeyidov/jodit-python/actions/workflows/ci.yml)
[![Docs](https://github.com/TimurSeyidov/jodit-python/actions/workflows/docs.yml/badge.svg)](https://timurseyidov.github.io/jodit-python/)
[![Coverage](https://codecov.io/gh/TimurSeyidov/jodit-python/graph/badge.svg)](https://codecov.io/gh/TimurSeyidov/jodit-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy-lang.org/)

Python/FastAPI implementation of the
[Jodit](https://xdsoft.net/jodit/) File Browser and Uploader connector,
API-compatible with [jodit-nodejs](https://github.com/jodit/jodit-nodejs).

## Installation

```bash
pip install "jodit-python[all]"
```

Python 3.14+. Optional features are extras: `[pdf]` (`generatePdf`,
needs the Pango system library: `brew install pango` on macOS,
`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0` on
Debian/Ubuntu), `[docx]` (`generateDocx`), `[s3]` (S3 storage);
`[all]` installs them all. Without an extra the connector still works
and the action that needs it answers `501` naming what to install.

For development: [uv](https://docs.astral.sh/uv/) (`make sync`
installs everything).

## Quick start

```bash
make sync   # install dependencies
make run    # http://localhost:8081/ping
make menu   # interactive list of commands
```

## Try it with Jodit

```bash
make demo   # opens http://localhost:8080/demo/ (NO_BROWSER=1 to skip)
```

`demo/index.html` is the Jodit PRO file browser (from a CDN, as in the
jodit-nodejs demo) talking to the connector configured by
`demo/config.json` (CORS on, files in `./files`, served by the same
static server as the page). Jodit PRO needs no license key on
`localhost`; on other hosts it shows a "Trial version" notice.

## Usage

```python
# main.py
from starlette.requests import Request

from jcpy import create_app


async def check_authentication(request: Request) -> str:
    token = request.headers.get("authorization")
    return "admin" if token == "Bearer secret" else "guest"


app = create_app("config.json", check_authentication=check_authentication)
```

```bash
uv run uvicorn main:app --port 8081
```

`config.json` overrides only what differs from the built-in defaults
(camelCase keys, as in jodit-nodejs):

```json
{
  "onlyPOST": true,
  "sources": {
    "uploads": {
      "title": "Uploads",
      "root": "/var/www/uploads",
      "baseurl": "https://example.com/uploads/"
    }
  }
}
```

Without an explicit path the configuration is read from the `CONFIG`
environment variable (JSON text) or the file named by `CONFIG_FILE`.

Access rules live in `accessControl` (the last matching rule wins,
unlisted actions are allowed):

```json
{
  "defaultRole": "guest",
  "accessControl": [
    { "role": "guest", "FILE_UPLOAD": false, "FILE_REMOVE": false },
    { "role": "admin", "path": "/private", "FILES": true }
  ]
}
```

They can also be loaded per check from code, e.g. from a database:

```python
from jcpy import AccessControlRule, create_app


async def load_rules() -> list[AccessControlRule]:
    rows = await db.fetch_rules()
    return [AccessControlRule.model_validate(row) for row in rows]


app = create_app("config.json", access_control=load_rules)
```

### S3 and S3-compatible storage

```json
{
  "sources": {
    "media": {
      "title": "Media",
      "baseurl": "https://my-bucket.s3.eu-central-1.amazonaws.com/media/",
      "storageAdapter": "s3",
      "s3": {"bucket": "my-bucket", "region": "eu-central-1", "prefix": "media"}
    }
  }
}
```

Without `credentials` the AWS default chain is used (environment,
profile, instance role). MinIO, Cloudflare R2, Yandex Object Storage and
others work through `endpoint` (plus `forcePathStyle: true` where
needed). Other backends implement `jcpy.StorageAdapter` and are
registered with `register_storage_adapter("name", factory)`.

### Multi-tenant sources

```python
from starlette.requests import Request

from jcpy import ResolvedSources, create_app


async def resolve_sources(request: Request) -> ResolvedSources | None:
    tenant = await find_tenant(request.headers.get("x-tenant-id"))
    if tenant is None:
        return None  # static "sources" apply
    return ResolvedSources(
        id=f"{tenant.id}:{tenant.updated_at}",
        sources={"files": tenant.source_settings},
    )


app = create_app("config.json", resolve_sources=resolve_sources)
```

The resolver runs on every request, before authentication; the built
sources are cached by `id` (`dynamicSourcesCache`: 200 tenants, 60 s by
default). Use `"sources": {}` for an instance that only serves tenants.

Several independent instances can live in one application:

```python
from fastapi import FastAPI

from jcpy import create_router

app = FastAPI()
app.include_router(create_router("public.json"), prefix="/public")
app.include_router(
    create_router("admin.json", check_authentication=admin_auth),
    prefix="/admin",
)
```

## Examples

Runnable programs in [`examples/`](examples) (start them from the
repository root, e.g. `uv run python examples/basic.py`):

| Example | Shows |
|---|---|
| `basic.py` | Standalone connector from a JSON config |
| `cookie_auth.py` | Role from a cookie |
| `jwt_auth.py` | Role from a signed JWT (PyJWT) |
| `session_auth.py` | Role in a server-signed session with login routes |
| `custom_svg.py` | Custom thumbnail icons |
| `multi_instance.py` | Two isolated connectors in one application |
| `s3.py` | Files in an S3 bucket |
| `multi_tenant.py` | Per-request (tenant) sources |
| `custom_storage.py` | Custom storage adapter registered by name |

## Documentation

The full documentation (usage, configuration reference, API endpoints,
Swagger UI) is an MkDocs site in [`docs/`](docs):

```bash
make docs        # http://127.0.0.1:8000
make docs-build  # static site in site/
```

The OpenAPI 3.1 document is generated from Pydantic models into
[`docs/content/api-swagger/`](docs/content/api-swagger)
(`openapi.json`, `openapi.yaml`); `make openapi` regenerates it and CI
fails when it is stale. The connector itself does not serve `/docs` or
`/openapi.json`: like jodit-nodejs, every path is an action name.

## Development

```bash
make check  # lint, format, mypy --strict, OpenAPI and docs checks, tests
```

All caches (uv, ruff, mypy, pytest, coverage, bytecode) live in
`.cache/`. The Makefile and the dev container set
`PYTHONPYCACHEPREFIX=.cache/pycache`; export it yourself when running
`uv run ...` directly.

### Docker

```bash
make dev-up     # dev container with hot reload on http://localhost:8081
make dev-shell  # shell inside it (make check works there too)
make dev-down

make prod-up    # production image (non-root, tini, healthcheck)
make prod-down
```

`PORT` overrides the published host port, e.g. `PORT=9000 make prod-up`.
Files served by the production container live in `./files`.

### Dev Containers

Open the folder in VS Code (or any IDE supporting Dev Containers) and
choose **Reopen in Container**. The container is built from the `dev`
stage of the `Dockerfile`; the virtualenv lives in a named volume, so it
does not clash with a local `.venv`. Start the server with `make dev`.

## License

[MIT](LICENSE)
