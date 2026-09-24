---
title: Getting Started
description: Quick start for jodit-python - installation, first run and key features.
---

# Getting Started

jodit-python is a Python/FastAPI implementation of the
[Jodit](https://xdsoft.net/jodit/) File Browser and Uploader connector.
Its HTTP API is the same as that of
[jodit-nodejs](https://github.com/jodit/jodit-nodejs): routes,
parameters, response format and status codes. Jodit Editor works with it
without any change on the client side.

## Overview

- **File operations**: browse, upload (from the browser or from a URL),
  download, rename, move, copy, delete
- **Folder management**: create, rename, move, copy, delete, tree view
- **Image processing**: resize, crop, save from the image editor,
  thumbnails
- **Document generation**: PDF and DOCX from HTML
- **Authentication and ACL**: role per request, rules by role, path and
  extension, static or loaded at runtime
- **FastAPI integration**: standalone app or a router mounted into your
  application, several isolated instances side by side
- **Storage**: local filesystem or [AWS S3 / S3-compatible](aws-s3.md)
  out of the box, [custom adapters](storage-adapters.md) for anything
  else
- **Multi-tenant**: [sources resolved per request](dynamic-sources.md)

## Installation

```bash
uv add jodit-python        # or: pip install jodit-python
```

!!! note "Release status"
    The PyPI package and the Docker Hub image are not published yet.
    Until then install from the repository:
    `uv add git+https://github.com/TimurSeyidov/jodit-python` and build
    the image locally (see [Docker](docker.md)).

Python 3.14+ is required. PDF export uses WeasyPrint, which needs Pango:
`brew install pango` on macOS,
`apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0` on
Debian/Ubuntu (already included in the Docker image).

## Quick Start

### Standalone server

```bash
SOURCE_ROOT=/var/www/uploads \
SOURCE_BASEURL=https://example.com/uploads/ \
jcpy
```

The `jcpy` command serves the connector on `http://0.0.0.0:8081`
(`HOST` and `PORT` change it):

```bash
curl http://localhost:8081/ping
# {"success":true}
curl "http://localhost:8081/?action=files"
```

### From Python

Settings live in a JSON file; only what differs from the
[defaults](config.md) needs to be there:

```json title="config.json"
{
  "sources": {
    "uploads": {
      "title": "Uploads",
      "root": "/var/www/uploads",
      "baseurl": "https://example.com/uploads/"
    }
  }
}
```

Callbacks (authentication, dynamic rules, custom icons...) are passed in
code:

```python title="main.py"
from starlette.requests import Request

from jcpy import create_app


async def check_authentication(request: Request) -> str:
    token = request.headers.get("authorization")
    return "admin" if token == "Bearer secret" else "guest"


app = create_app("config.json", check_authentication=check_authentication)
```

```bash
uvicorn main:app --port 8081
```

### Serving the files

The connector manages files but does not serve them: thumbnails and
file links point to `baseurl`, which must be served by a web server or
a CDN. With nginx:

```nginx
location /uploads/ {
    alias /var/www/uploads/;
}

location /jodit/connector/ {
    proxy_pass http://127.0.0.1:8081/;
    client_max_body_size 16m;
}
```

### Jodit Editor

```javascript
Jodit.make('#editor', {
  uploader: {
    url: '/jodit/connector/?action=fileUpload'
  },
  filebrowser: {
    ajax: {
      url: '/jodit/connector/'
    }
  }
});
```

### Try it in the browser

From a checkout of the repository:

```bash
make demo
```

Open `http://localhost:8080/demo/`: the free Jodit editor (from a CDN)
with its file browser and uploader connected to jodit-python on port
8081. The page and the files (`./files`) are served on port 8080; the
connector uses `demo/config.json`. Another connector can be tried with
`http://localhost:8080/demo/?connector=https://example.com/connector/`.

Jodit's uploader does not name the action, so its URL carries it:
`uploader: { url: 'https://example.com/connector/?action=fileUpload' }`.

## Next Steps

- **[Installation & Setup](installation.md)**: environment variables and
  configuration sources
- **[Python API](usage.md)**: `create_app`, `create_router`, callbacks
- **[FastAPI Integration](integration.md)**: mounting into an existing
  application, several instances
- **[API Endpoints](api.md)**: every action with parameters and answers
- **[Authentication](authentication.md)** and
  **[Access Control](access-control.md)**
- **[Configuration](config.md)**: every setting
- **[Docker](docker.md)**
