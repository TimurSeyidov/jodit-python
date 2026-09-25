# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-25

### Added

- `ftp` storage adapter for FTP and FTPS (explicit TLS, certificate checked) servers, with no extra dependency: `MLST`/`MLSD` or `SIZE`/`MDTM`/`LIST` (Unix and Windows formats), atomic writes, pooled connections reopened when they drop.
- `sftp` storage adapter (extra `[sftp]`, paramiko): the server's host key is always checked (`hostKey`, `knownHostsFile` or the system `known_hosts`), password or private key login, atomic writes (`posix-rename` when available), pooled connections.
- `webdav` storage adapter with no extra dependency (httpx): Basic, Digest or bearer-token login, atomic writes, server-side copies and moves that never replace a folder, deletes that never remove a folder by mistake, works behind reverse proxies that rewrite paths.
- S3 options `serverSideEncryption`, `sseKmsKeyId`, `storageClass` and `cacheControl`, applied to uploads, copies and moves; folder markers get the encryption.
- Optional adapter methods `write_file(path, file)` and `iter_file(path)` (`jcpy.storage.StreamingStorageAdapter`) to move contents without holding them in memory.

### Changed

- `fileDownload` streams the file in 64 KiB chunks instead of reading it into memory.
- Uploads and `fileUploadRemote` write to storage from a temporary file (at most 1 MB in memory); S3 receives them in parts.
- The built-in adapters run transfers (reads, writes, copies) in a thread pool of their own, 16 threads per adapter, apart from quick operations.
- Folder checks (parent of an upload or a new folder, move and copy targets, thumbnail folders) take one S3 request instead of two.

## [0.1.1] - 2026-09-25

### Added

- S3 options `connectTimeout` (10 s), `readTimeout` (60 s) and `maxAttempts` (3 attempts in total, standard retry mode).
- The Docker Hub page is published from the README.

### Changed

- Listings take size and modification time from the storage listing and call `stat` only when they are missing, concurrently: an S3 folder is listed with one request instead of one per entry.
- Folder copies (every storage) and S3 folder moves run concurrently, 16 operations at a time; an S3 folder move deletes the source only after every copy succeeded.
- Local listings skip symlinks, FIFOs and sockets (with a warning) instead of failing.

### Fixed

- S3: objects over 5 GB can be copied, renamed and moved (multipart copy); metadata such as `Content-Type` is kept.
- S3: deleting a folder reports objects that could not be deleted instead of succeeding silently, and no longer loops on them.
- Local storage: writes and copies are atomic; a failed write leaves the previous file intact.

## [0.1.0] - 2026-09-25

First release.

### Added

- HTTP connector for the Jodit File Browser and Uploader: 22 actions (`files`, `folders`, `permissions`, `fileUpload`, `fileUploadRemote`, `fileRemove`, `fileMove`, `fileCopy`, `fileRename`, `fileDownload`, `getLocalFileByUrl`, `folderCreate`, `folderRemove`, `folderMove`, `folderCopy`, `folderRename`, `imageResize`, `imageCrop`, `imageSave`, `imageLoad`, `generatePdf`, `generateDocx`) and `/ping`; actions are called as `/?action=<name>` or `/<name>`, with GET or POST.
- JSON configuration over built-in defaults (`config_file`, `CONFIG`, `CONFIG_FILE`), per-source overrides, callbacks passed in code.
- `create_app()` for a standalone application and `create_router()` for mounting into FastAPI; several isolated instances in one application.
- Authentication callback per request and access rules by role, path and extension (static, computed or loaded at runtime).
- Thumbnails for images and SVG icons for folders and other files, with a pluggable icon generator.
- Storage adapters: local filesystem, AWS S3 and S3-compatible services, custom adapters registered by name.
- Sources resolved per request (multi-tenant) with a cache.
- Optional extras: `[pdf]` (WeasyPrint), `[docx]` (html-for-docx), `[s3]` (boto3), `[all]`; without an extra its actions answer `501`.
- OpenAPI 3.1 document and Swagger UI generated from the schemas; MkDocs documentation site.
- Docker image (multi-stage, non-root, `linux/amd64` and `linux/arm64`), Dev Container, `make demo` with the Jodit PRO file browser.

### Security

- Remote downloads (`fileUploadRemote`, resources of PDF and DOCX) connect only to public addresses: the checked address is pinned, every redirect is checked, IPv6 forms of private IPv4 addresses are refused, the size is limited while streaming.
- Paths are confined to the source root, symlinks included; access rules match the normalized requested path.
- A rejected upload never overwrites an existing file; `imageSave` obeys the `extensions` list.
- Error messages do not reveal absolute server paths.

[0.2.0]: https://github.com/TimurSeyidov/jodit-python/releases/tag/v0.2.0
[0.1.1]: https://github.com/TimurSeyidov/jodit-python/releases/tag/v0.1.1
[0.1.0]: https://github.com/TimurSeyidov/jodit-python/releases/tag/v0.1.0
