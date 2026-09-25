---
title: Installation & Setup
description: Installation, environment variables and configuration sources of jodit-python.
---

# Installation & Setup

## Installation

```bash
uv add "jodit-python[all]"        # or: pip install "jodit-python[all]"
```

Python 3.14+ is required. Heavy or system-dependent features are optional extras:

| Install | Adds |
|---|---|
| `jodit-python` | The connector: files, folders, uploads, images, thumbnails, local storage |
| `jodit-python[pdf]` | `generatePdf` (WeasyPrint; needs the Pango system library) |
| `jodit-python[docx]` | `generateDocx` (html-for-docx) |
| `jodit-python[s3]` | The `s3` storage adapter (boto3) |
| `jodit-python[all]` | Everything above, as in the Docker image |

Without an extra the package still imports and every other action works; the action that needs it answers `501` naming what to install, e.g. `generatePdf requires the pdf extra: pip install 'jodit-python[pdf]'`.

Pango for `[pdf]`: `brew install pango` on macOS, `apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0` on Debian/Ubuntu (already in the Docker image).

## Configuration sources

The configuration is JSON with camelCase keys. Defaults live in code; the JSON only overrides them (nested objects are merged, lists and `sources` are replaced). The first source that is set wins:

1. the `config_file` argument of `create_app()` / `create_router()`;
2. the `CONFIG` environment variable (JSON text);
3. the file named by the `CONFIG_FILE` environment variable;
4. defaults only.

An unknown key or an invalid value stops the start with a `ConfigError` that lists every problem:

```text
jcpy.errors.ConfigError: Invalid connector config:
  sources.uploads.baseurl: Input should be a valid URL, relative URL without a base
```

Functions (authentication, dynamic access rules, icon generator, tenant resolver) are not part of the JSON: they are arguments of [`create_app()`](usage.md).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CONFIG` | | Configuration as JSON text |
| `CONFIG_FILE` | | Path to a JSON configuration file |
| `SOURCE_NAME` | `Test Files` | Title of the default source |
| `SOURCE_ROOT` | `./files` | Directory of the default source |
| `SOURCE_BASEURL` | `http://localhost:$PORT/files/` | Public URL of the default source |
| `HOST` | `0.0.0.0` | Address the `jcpy` command listens on |
| `PORT` | `8081` | Port the `jcpy` command listens on |

`SOURCE_*` only build the default source, which is used when the configuration defines no `sources`.

```bash
# Default source from the environment
SOURCE_NAME="My Files" \
SOURCE_ROOT=/var/www/uploads \
SOURCE_BASEURL=https://cdn.example.com/uploads/ \
PORT=8080 \
jcpy

# Inline JSON
CONFIG='{"debug": false, "allowCrossOrigin": true}' jcpy

# Config file
CONFIG_FILE=/etc/jodit/config.json jcpy
```

## Running

=== "jcpy command"

    ```bash
    jcpy                       # uses CONFIG / CONFIG_FILE / SOURCE_*
    ```

=== "uvicorn"

    ```bash
    uvicorn jcpy.app:create_app --factory --port 8081
    uvicorn main:app --port 8081 --workers 4   # your own main.py
    ```

=== "Docker"

    ```bash
    docker run --rm -p 8081:8081 \
      -v $(pwd)/config.json:/app/config.json:ro \
      -e CONFIG_FILE=/app/config.json \
      -v /var/www/uploads:/app/files \
      w2fb/jodit-python
    ```

    See [Docker](docker.md).

!!! tip "Several workers"
    Every worker keeps its own caches (tenant sources). The state that matters (files, thumbnails) is in the storage, so any number of workers or containers can serve the same sources.

## Next Steps

- **[Python API](usage.md)**
- **[Configuration Reference](config.md)**
- **[Authentication](authentication.md)**
