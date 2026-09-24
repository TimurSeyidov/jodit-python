# jodit-python

Python/FastAPI implementation of the
[Jodit](https://xdsoft.net/jodit/) File Browser and Uploader connector,
API-compatible with [jodit-nodejs](https://github.com/jodit/jodit-nodejs).

> Work in progress.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Quick start

```bash
make sync   # install dependencies
make run    # http://localhost:8081/ping
make menu   # interactive list of commands
```

## Usage

```python
# main.py
from starlette.requests import Request

from jcpy import create_app


async def check_authentication(request: Request) -> str:
    token = request.headers.get("authorization")
    return "admin" if token == "Bearer secret" else "guest"


app = create_app(
    "config.json", check_authentication=check_authentication
)
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

## Development

```bash
make check  # lint + format check + mypy --strict + tests with coverage
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

MIT
