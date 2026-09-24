---
title: Development & Testing
description: Working on jodit-python - tooling, checks, tests, documentation and CI.
---

# Development & Testing

## Setup

```bash
git clone https://github.com/TimurSeyidov/jodit-python
cd jodit-python
make sync        # uv sync --all-groups
make menu        # interactive list of every command
```

Or open the folder in VS Code (or another IDE with Dev Containers) and
choose **Reopen in Container**; everything below works inside.

All caches (uv, ruff, mypy, pytest, coverage, bytecode) live in
`.cache/`. On macOS the Makefile points WeasyPrint to Homebrew's
libraries (`DYLD_FALLBACK_LIBRARY_PATH`); export it yourself when
running `uv run ...` directly.

## Commands

| Command | What it does |
|---|---|
| `make run` / `make dev` | Serve on port 8081 / with auto-reload |
| `make lint` / `make lint-fix` | ruff check |
| `make format` / `make format-check` | ruff format |
| `make typecheck` | mypy `--strict` over `src`, `tests`, `scripts`, `examples` |
| `make test` / `make coverage` | pytest / with branch coverage (fails under 90%) |
| `make openapi` / `make openapi-check` | Regenerate / verify `docs/content/api-swagger/openapi.{json,yaml}` |
| `make docs` / `make docs-build` | Serve / build this site (`--strict`) |
| `make check` | Everything CI runs |

Code style: 79-character lines, Google-style docstrings stating what a
function does and its contract (`Args`, `Returns`, `Raises`).

## Tests

```text
tests/
├── unit/          # helpers, config, ACL, storage, SSRF guard, ...
├── integration/   # HTTP requests through the ASGI app
├── fixtures/      # expected values generated from the npm packages
└── conftest.py    # app/client factories, temporary sources
```

- Requests go through the real application in-process
  (`httpx.ASGITransport`), with sources in `tmp_path`.
- Ported JavaScript behaviour (`qs` parsing, `bytes`, Day.js formats,
  slugify, change-case, Node's `path`, sorting, the SVG icon...) is
  checked against fixtures produced by the original npm packages; the
  generators are in `scripts/`.
- S3 tests run against MinIO in Docker (Testcontainers) and are skipped
  when no Docker daemon is reachable; unit tests of the adapter use
  botocore's `Stubber`.
- Unclosed files and sockets fail the test that leaks them
  (`ResourceWarning` is an error).
- Every program in `examples/` is imported and exercised.

```bash
make test
uv run pytest tests/integration/test_files.py -k sort -v
```

### Writing a test

```python
from typing import TYPE_CHECKING

from tests.conftest import source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ClientFactory


async def test_lists_uploaded_file(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    write_file(tmp_path, "a.txt", "hello")

    async with connector_client(source_config(tmp_path)) as http:
        response = await http.get("/files", params={"source": "test"})

    (source,) = response.json()["data"]["sources"]
    assert [item["file"] for item in source["files"]] == ["a.txt"]
```

## Documentation

The site is built with MkDocs Material from `docs/`:

```text
docs/
├── mkdocs.yml
└── content/        # pages; api-swagger/openapi.{json,yaml} are generated
```

Code on the pages is included from `examples/` (snippets between
`# --8<-- [start:build]` and `# --8<-- [end:build]`), so it is the
tested code. `make docs-build` fails on broken links and missing
snippets, and runs in CI.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes to `main` and on pull
requests: lint, format check, mypy, the OpenAPI check, the documentation
build and the tests with coverage, then builds the production image and
checks that it answers `/ping`.
