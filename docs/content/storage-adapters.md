---
title: Storage Adapters
description: How sources store files, the StorageAdapter interface and registering your own adapter.
---

# Storage Adapters

## Overview

A source keeps its files in a **storage adapter**. Two are built in:

| Name | Storage | Settings |
|---|---|---|
| `local` (default) | Directory on the server | `root` |
| `s3` | AWS S3 or an S3-compatible service | `s3` block ([AWS S3](aws-s3.md)); needs the `s3` extra |

Anything else (a database, another object store, a remote API) plugs
in as a custom adapter registered under a name.

## How it works

```text
action → Source (root confinement, name checks, thumbnails)
       → FileStorage (path normalization, error wrapping)
       → StorageAdapter (your backend)
```

Adapters see **normalized relative paths**: `/` separators, no leading
slash, no `.` or `..`, the empty string for the root. Everything above
them (access checks, confinement to the source, safe names, thumbnail
folders) is the connector's job, and an adapter only stores bytes.

For non-local adapters `root` is a virtual prefix (default `/`); the
real location, e.g. the key prefix of a bucket, belongs to the
adapter's own options.

## Selecting an adapter

```json
{
  "sources": {
    "local": {
      "title": "Local",
      "root": "/var/www/files",
      "baseurl": "https://example.com/files/"
    },
    "media": {
      "title": "Media",
      "baseurl": "https://cdn.example.com/media/",
      "storageAdapter": "s3",
      "s3": {"bucket": "my-bucket", "prefix": "media"}
    },
    "scratch": {
      "title": "Scratch",
      "baseurl": "https://example.com/scratch/",
      "storageAdapter": "memory"
    }
  }
}
```

A name that is not registered fails the request that uses the source
with `400 Unknown storage adapter "..."`, listing the registered names.

## The interface

`jcpy.StorageAdapter` is a `Protocol`: any class with these methods
works, no base class needed.

| Method | Contract |
|---|---|
| `async write(path, contents: bytes)` | Create or replace a file, creating parent directories |
| `async read(path) -> bytes` | Whole file; raise `FileWasNotFoundError(path)` when missing |
| `async delete_file(path)` | Delete a file; missing is not an error |
| `async create_directory(path)` | Create a directory with its parents |
| `async delete_directory(path)` | Delete a directory recursively; missing is not an error |
| `async stat(path) -> StatEntry` | Size and modification time (epoch ms); raise when the path does not exist |
| `list(path, *, deep) -> AsyncIterator[StatEntry]` | Entries of a directory (every level with `deep=True`); size and time may be unknown |
| `async file_exists(path) -> bool` | `True` for a file, not for a directory |
| `async directory_exists(path) -> bool` | `True` for a directory (the root included) |
| `async copy_file(source, destination)` | Copy a file, creating the destination's parents |
| `async move_file(source, destination)` | Move a file **or a directory** |

`StatEntry(path, is_file, size=None, last_modified_ms=None)` is in
`jcpy.storage`, next to `StorageError` and `FileWasNotFoundError`.
Exceptions raised by an adapter are wrapped with the operation
(`Unable to write the file. Reason: ...`) and answered with `500` or
`400` depending on the action.

Blocking libraries should run in threads (`anyio.to_thread.run_sync`),
as the built-in adapters do, to keep the event loop free.

## Registering an adapter

```python
from jcpy import SourceConfig, create_app, register_storage_adapter


def my_adapter(source: SourceConfig) -> StorageAdapter:
    return MyAdapter(source.name)


register_storage_adapter("mine", my_adapter)
app = create_app("config.json")
```

The factory gets the source settings and returns an adapter. Adapters
of all sources are built once, on the first request that needs
sources, and kept for the life of the instance (for
[dynamic sources](dynamic-sources.md): until the tenant leaves the
cache). Register before the first request; the
registry is global to the process.

Settings for your adapter can be read from the source: unknown keys are
rejected, so either keep them in your code (keyed by `source.name`) or
reuse an existing field such as `root`.

## Example: in-memory adapter

A complete adapter, used by [`examples/custom_storage.py`](examples.md#custom-storage-adapter)
and covered by the test suite:

```python
--8<-- "examples/custom_storage.py:build"
```

## Testing an adapter

Run the connector over it and exercise the actions, as the example's
test does:

```python
from httpx import ASGITransport, AsyncClient


async def test_round_trip() -> None:
    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        await http.post("/fileUpload", files={"files[0]": ("a.txt", b"hi")})
        await http.get("/folderCreate", params={"name": "docs"})
        moved = await http.get(
            "/fileMove", params={"from": "a.txt", "path": "docs"}
        )
        listing = await http.get("/files", params={"path": "docs"})
        removed = await http.get("/folderRemove", params={"name": "docs"})

    assert moved.status_code == 200
    assert [
        f["file"] for f in listing.json()["data"]["sources"][0]["files"]
    ] == ["a.txt"]
    assert removed.status_code == 200
```

## Pitfalls

1. **The root is the empty string.** `directory_exists("")` must be
   `True` and `list("")` must list the top level.
2. **Parents appear implicitly.** `write("a/b/c.txt", ...)` must make
   `a` and `a/b` exist, and `list` must report them.
3. **`deep` listings** return every level, with paths relative to the
   root, not to the listed directory.
4. **`move_file` moves directories too** (`fileMove` and `folderMove`
   use it).
5. **Missing is not an error** for `delete_file` and
   `delete_directory`.
