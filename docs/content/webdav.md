---
title: WebDAV storage
description: Keeping a source on a WebDAV server such as Apache, nginx or Nextcloud.
---

# WebDAV storage

The built-in `webdav` adapter keeps a source in a collection (folder) on a WebDAV server: Apache `mod_dav`, nginx with the DAV modules, Nextcloud and ownCloud, rclone, file-sharing appliances. It speaks HTTP through httpx, which the connector already uses, so it needs no extra.

The editor loads files from `baseurl`, not through the connector. Point `baseurl` at a URL that serves the same folder to the readers of your content. The WebDAV URL itself usually needs a login and does not work for them.

## Quick start

```json
--8<-- "examples/config/webdav.json"
```

For Nextcloud, use an app password (Settings → Security) and the URL `https://<host>/remote.php/dav/files/<user>/<folder>/`.

## Options

All options live under `sources.<name>.webdav`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `url` | `string` | required | `http://` or `https://` URL of the collection acting as the source root |
| `username` | `string` | none | Login |
| `password` | `string` | none | Password |
| `token` | `string` | none | Bearer token sent as `Authorization: Bearer ...`; not together with `username` |
| `auth` | `string` | `basic` | `basic` or `digest` |
| `verifyCertificate` | `boolean` | `true` | Check the server certificate with the system CAs; turn off only for self-signed certificates on a trusted network |
| `timeout` | `number` | `30` | Seconds to wait for the server |
| `connections` | `integer` | `8` | Most HTTP connections open at once (1–64) |

Without `username` and `token`, requests are anonymous. Basic authentication sends the password with every request: use `https://`.

## How files are handled

- **Writes.** Uploads and generated files are sent (`PUT`) to a temporary `.<random>.tmp` file in the target folder and then moved (`MOVE`) over the target. Readers never see a partial file, and a failed upload leaves the previous file in place and removes the temporary one. Missing parent folders are created (`MKCOL`).
- **Copies and moves** run on the server (`COPY`, `MOVE`), so the file never passes through the connector. They are sent with `Overwrite: F` first. An existing target is replaced only when it is a file: WebDAV would otherwise delete a whole folder to make room.
- **Deleting a file** checks first that it is not a folder, because a WebDAV `DELETE` removes folders recursively.
- **Streaming.** Downloads are streamed in 64 KiB chunks. Uploads are sent from the request's temporary file with a known length, since some servers refuse chunked uploads.
- **Listings** take one `PROPFIND` (`Depth: 1`) per folder, with sizes and times. `Depth: infinity` is not used, because many servers disable it.
- **Reverse proxies.** The paths the server reports are matched against what it reports for the root, not against `url`. A share published under another path (`/dav/` in front of `/remote.php/dav/files/...`) still lists correctly.
- **Errors** name the storage path (`GET /photos/a.jpg failed: 403 Forbidden`), never the server URL, so the address of an internal server does not reach browser clients.
- **Redirects** are followed. The `Authorization` header is dropped when a redirect leads to another host.

## Limits

- Locks (`LOCK`/`UNLOCK`) are not used. Two editors saving the same file at once: the last write wins.
- A server that answers `PROPFIND` without `getlastmodified` or `getcontentlength` shows files without a time or size.

## Troubleshooting

`PROPFIND / failed: 401`
:   Wrong login, or the server wants `digest`. Nextcloud with two-factor authentication needs an app password.

`PROPFIND / failed: 405`
:   The URL is not a WebDAV collection. Check the path, and that DAV is enabled for it (`Dav On` in Apache).

`PUT ... failed: 411` or `413`
:   A proxy in front of the server refuses the upload: its body size limit (`client_max_body_size` in nginx) is too low.

Listings are empty but files exist
:   The URL points at the wrong folder, often the account root instead of the folder you meant. Open it with any WebDAV client to compare.
