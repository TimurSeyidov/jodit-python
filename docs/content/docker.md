---
title: Docker
description: Building and running the jodit-python image, configuration and reverse proxy.
---

# Docker

## Quick start

```bash
docker build --target prod -t jodit-python .
docker run --rm -p 8081:8081 -v $(pwd)/files:/app/files jodit-python
curl http://localhost:8081/ping
```

Or with Compose (`docker-compose.yml` in the repository):

```bash
make prod-up      # build and start, files in ./files
make prod-logs
make prod-down
```

## Configuration

### Config file (recommended)

```bash
docker run --rm -p 8081:8081 \
  -v $(pwd)/config.json:/app/config.json:ro \
  -e CONFIG_FILE=/app/config.json \
  -v /var/www/uploads:/app/files \
  jodit-python
```

With `root` in the file pointing to `/app/files` (or wherever the files
are mounted).

### Environment variables

```bash
docker run --rm -p 8081:8081 \
  -e SOURCE_NAME="My Files" \
  -e SOURCE_ROOT=/app/files \
  -e SOURCE_BASEURL=https://cdn.example.com/uploads/ \
  -v /var/www/uploads:/app/files \
  jodit-python
```

### Inline JSON

```bash
docker run --rm -p 8081:8081 \
  -e CONFIG='{"debug": false, "sources": {"files": {"title": "Files", "root": "/app/files", "baseurl": "https://cdn.example.com/files/"}}}' \
  -v /var/www/uploads:/app/files \
  jodit-python
```

### S3

```bash
docker run --rm -p 8081:8081 \
  -v $(pwd)/s3.json:/app/config.json:ro -e CONFIG_FILE=/app/config.json \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  jodit-python
```

See [AWS S3](aws-s3.md) for `s3.json`.

### Your own `main.py`

Callbacks (authentication, tenants...) live in code, so an application
with them gets a small derived image:

```dockerfile
FROM jodit-python
COPY main.py config.json /app/
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
```

Priority of the configuration: the argument of `create_app()`, then
`CONFIG`, then `CONFIG_FILE`, then defaults
([details](installation.md#configuration-sources)).

## Image

| | |
|---|---|
| Base | `python:3.14-slim` |
| User | `app` (non-root), home and workdir `/app` |
| Init | `tini` |
| Port | `8081` (`PORT`, `HOST` change it) |
| Files | `/app/files` (default source root) |
| Health check | `GET /ping` every 30 s |
| Extras | Pango for PDF export, DejaVu and Liberation fonts |
| Size | about 330 MB |

Mounted directories must be writable by the `app` user (uid of the
image's `app` account), e.g. `chown` them or run with
`--user $(id -u):$(id -g)`.

## Stages

| Stage | Purpose |
|---|---|
| `builder` | Resolves the locked dependencies with uv into `/app/.venv` |
| `dev` | Toolchain and the full dependency set; used by `docker-compose.dev.yml` and Dev Containers |
| `prod` | Runtime only: the virtualenv from `builder`, system libraries, fonts |

```bash
make dev-up       # dev container with hot reload on http://localhost:8081
make dev-shell    # shell inside it (make check works there)
make dev-down
```

## Behind nginx

```nginx
location /jodit/connector/ {
    proxy_pass http://127.0.0.1:8081/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 16m;   # at least maxUploadFileSize
}

location /uploads/ {
    alias /var/www/uploads/;    # what baseurl points to
}
```

Point Jodit to `/jodit/connector/` and set each source's `baseurl` to
the public URL of its files (`https://example.com/uploads/`).
