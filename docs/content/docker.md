---
title: Docker
description: Building and running the jodit-python image, configuration and reverse proxy.
---

# Docker

## Quick start

```bash
docker run --rm -p 8081:8081 -v $(pwd)/files:/app/files w2fb/jodit-python
curl http://localhost:8081/ping
```

The image is published on Docker Hub as [`w2fb/jodit-python`](https://hub.docker.com/r/w2fb/jodit-python) for `linux/amd64` and `linux/arm64`, tagged `latest`, `<major>.<minor>` (e.g. `0.4`) and the full version (e.g. `0.4.1`). To build it from the repository instead: `docker build --target prod -t jodit-python .`

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
  w2fb/jodit-python
```

With `root` in the file pointing to `/app/files` (or wherever the files are mounted).

### Environment variables

```bash
docker run --rm -p 8081:8081 \
  -e SOURCE_NAME="My Files" \
  -e SOURCE_ROOT=/app/files \
  -e SOURCE_BASEURL=https://cdn.example.com/uploads/ \
  -v /var/www/uploads:/app/files \
  w2fb/jodit-python
```

### Inline JSON

```bash
docker run --rm -p 8081:8081 \
  -e CONFIG='{"debug": false, "sources": {"files": {"title": "Files", "root": "/app/files", "baseurl": "https://cdn.example.com/files/"}}}' \
  -v /var/www/uploads:/app/files \
  w2fb/jodit-python
```

### S3

```bash
docker run --rm -p 8081:8081 \
  -v $(pwd)/s3.json:/app/config.json:ro -e CONFIG_FILE=/app/config.json \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  w2fb/jodit-python
```

See [AWS S3](aws-s3.md) for `s3.json`.

### Your own `main.py`

Callbacks (authentication, tenants...) live in code, so an application with them gets a small derived image:

```dockerfile
FROM w2fb/jodit-python:0.1
COPY main.py config.json /app/
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
```

Priority of the configuration: the argument of `create_app()`, then `CONFIG`, then `CONFIG_FILE`, then defaults ([details](installation.md#configuration-sources)).

## Image

| | |
|---|---|
| Base | `python:3.14-slim` |
| User | `app` (non-root, uid and gid `1000`), home and workdir `/app` |
| Init | `tini` |
| Port | `8081` (`PORT`, `HOST` change it) |
| Files | `/app/files` (default source root) |
| Health check | `GET /ping` every 30 s |
| Extras | All Python extras (`[all]`: PDF, DOCX, S3, SFTP, Azure, GCS), Pango, DejaVu and Liberation fonts |
| Size | about 330 MB |

## Mounted folders

The connector writes into `/app/files` (or wherever source roots point), so a folder mounted there must be writable by the user the container runs as. The image runs as uid `1000`, which is the first user on most Linux hosts and in WSL: a folder you created yourself usually just works.

```yaml
services:
  jodit:
    image: w2fb/jodit-python:latest
    user: "1000:1000"          # your `id -u`:`id -g`, if not 1000
    ports:
      - "8081:8081"
    environment:
      CONFIG_FILE: /app/config.json
    volumes:
      - ./config.json:/app/config.json:ro
      - ./upload:/app/files
```

When uploads fail with `Unable to write the file. Reason: Permission denied`:

- **Another uid on the host.** Check `id -u` and `id -g` and put them in `user:` (or `--user $(id -u):$(id -g)` with `docker run`).
- **The setting did not apply.** `docker compose restart` keeps the old container; run `docker compose up -d --force-recreate`, then `docker exec <container> id` must show your uid.
- **Docker created the folder.** A folder that did not exist before the first start is created by Docker as `root`. Create it yourself first, or `sudo chown -R $(id -u):$(id -g) ./upload`.
- **WSL with the project on a Windows drive** (`/mnt/c/...`). Linux permissions do not apply there, and Windows may lock fresh files. Keep the project inside the WSL file system (`~/...`).
- **SELinux** (Fedora, RHEL). Add `:z` to the volume: `./upload:/app/files:z`.

Every write goes to a temporary `.<random>.tmp` file in the target folder first and is then renamed over the target, so the container needs write access to the folder itself, not just to the files in it.

Images before 0.5.0 ran as uid `999`. A folder given to that uid with `chown` needs `chown -R 1000:1000` (or `user: "999:999"`) after upgrading. Build with `--build-arg APP_UID=... --build-arg APP_GID=...` for another fixed uid.

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

Point Jodit to `/jodit/connector/` and set each source's `baseurl` to the public URL of its files (`https://example.com/uploads/`).
