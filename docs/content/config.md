---
title: Configuration Reference
description: Every configuration setting of jodit-python with its type, default and effect, and per-source overrides.
---

# Configuration Reference

## Format

The configuration is a JSON object with camelCase keys. Defaults live in code; a configuration file only lists what differs from them. See [Installation](installation.md#configuration-sources) for where it is read from.

```json
{
  "debug": false,
  "allowCrossOrigin": true,
  "allowedOrigins": ["https://app.example.com"],
  "maxUploadFileSize": "20mb",
  "sources": {
    "uploads": {
      "title": "Uploads",
      "root": "/var/www/uploads",
      "baseurl": "https://cdn.example.com/uploads/"
    }
  }
}
```

Merging rules: nested objects (`pdf`, `dynamicSourcesCache`) are merged key by key, lists replace the default list, `null` keeps the default, and `sources` replaces the default source as a whole. Unknown keys and invalid values stop the start with a `ConfigError`.

In Python the validated settings are `AppConfig` attributes in snake_case (`config.max_upload_file_size`).

## General

### `debug` {#debug}
`boolean` · default `true`

Log failed requests with tracebacks to the `jcpy` logger. Set `false` in production to log less; answers are the same either way.

### `title` {#title}
`string` · default `""`

Not used (kept for configuration compatibility).

### `defaultFilesKey` {#defaultFilesKey}
`string` · default `"default"`

Form field that holds an uploaded file besides `files[0]`, `files[1]`... Used by `fileUpload` and `imageSave`.

## Sources

### `sources` {#sources}
`object` · default: one source named `default`

File locations shown by the browser, keyed by name. Without `sources` the default source is built from `SOURCE_NAME`, `SOURCE_ROOT` and `SOURCE_BASEURL` ([details](installation.md#environment-variables)).

```json
{
  "sources": {
    "uploads": {
      "title": "User Uploads",
      "root": "/var/www/uploads",
      "baseurl": "https://cdn.example.com/uploads/"
    },
    "media": {
      "title": "Media",
      "baseurl": "https://my-bucket.s3.amazonaws.com/media/",
      "storageAdapter": "s3",
      "s3": {"bucket": "my-bucket", "region": "eu-central-1", "prefix": "media"}
    }
  }
}
```

Source settings:

| Key | Type | Meaning |
|---|---|---|
| `name` | `string` | Name used in requests (`source=...`); defaults to the key |
| `title` | `string` | Required. Name shown in the browser |
| `baseurl` | `string` | Required. Absolute public URL of the source root; file links and thumbnails are built from it |
| `root` | `string` | Directory of the source; required for local storage, a virtual prefix for other adapters |
| `defaultFilesKey` | `string` | Overrides the global [`defaultFilesKey`](#defaultFilesKey) |
| `storageAdapter` | `string` | `local` (default), `s3`, `ftp`, `sftp` or a [registered](storage-adapters.md) name |
| `s3` | `object` | Options of the `s3` adapter, required with it ([AWS S3](aws-s3.md)) |
| `ftp` | `object` | Options of the `ftp` adapter, required with it ([FTP & SFTP](ftp-sftp.md)) |
| `sftp` | `object` | Options of the `sftp` adapter, required with it ([FTP & SFTP](ftp-sftp.md)) |
| *any global setting* | | [Per-source override](#per-source-overrides) |

The connector does not serve the files: `baseurl` must point to a web server or a CDN that does.

### `dynamicSourcesCache` {#dynamicSourcesCache}
`object` · default `{"max": 200, "ttlMs": 60000}`

How many tenants resolved by [`resolve_sources`](dynamic-sources.md) are kept (least recently used first out) and for how long.

### `root`, `baseurl` {#root}
`string`

Not used: sources carry their own `root` and `baseurl`.

### `sourceClassName` {#sourceClassName}
`string` · default `"FileSystem"`

Not used; the storage is chosen with `storageAdapter`.

## File handling

### `extensions` {#extensions}
`string[]` · default: common image, document, archive and media extensions

Allowed file extensions (lower case, without the dot). Uploads of other types get `403`, and listings leave such files out.

<details><summary>Default list</summary>

`jpg png gif jpeg bmp ico jpeg psd svg ttf tif ai txt css html js htm ini xml zip rar 7z gz tar pps ppt pptx odp xls xlsx csv doc docx pdf rtf avi flv 3gp mov mkv mp4 wmv webp`

</details>

!!! warning "Pages and scripts"
    The default list contains `html`, `htm` and `js`. If `baseurl` is served from your site's domain, uploaded pages and scripts run there (stored XSS). List only the types you need, e.g. images and documents:

    ```json
    {"extensions": ["jpg", "jpeg", "png", "gif", "webp", "pdf", "docx", "xlsx"]}
    ```

    The same list governs names saved by `imageSave`. Make sure the file host never executes uploaded files (no PHP or CGI under `baseurl`).

### `maxUploadFileSize` {#maxUploadFileSize}
`string` · default `"8mb"`

Largest accepted upload, as a number with a unit (`b`, `kb`, `mb`, `gb`...; case-insensitive) or plain bytes. Also caps [`fileUploadRemote`](api.md#fileuploadremote) downloads, which stop as soon as they exceed it.

### `maxFileSize` {#maxFileSize}
`string` · default `"8mb"`

Largest remote resource (image, stylesheet, font) loaded while generating [PDF and DOCX](documents.md).

### `saveSameFileNameStrategy` {#saveSameFileNameStrategy}
`string` · default `"addNumber"`

What an upload does when the name is taken:

- `addNumber`: store as `name-1.ext`, `name-2.ext`...
- `replace`: overwrite
- `error`: fail with `400 File ... already exists`

### `datetimeFormat` {#datetimeFormat}
`string` · default `"M/D/YYYY h:mm:ss A"`

Format of `changed` in listings, with [Day.js tokens](https://day.js.org/docs/en/display/format) (`YYYY`, `MM`, `DD`, `HH`, `mm`, `ss`, `A`...), in the server's local time.

### `defaultSortBy` {#defaultSortBy}
`string` · default `"changed-desc"`

Listing order when the request has no `mods[sortBy]`: `name-asc`, `name-desc`, `changed-asc`, `changed-desc`, `size-asc`, `size-desc`.

### `countInChunk` {#countInChunk}
`integer` · default `1000000`

Listing page size when the request has no `mods[limit]`.

### `excludeDirectoryNames` {#excludeDirectoryNames}
`string[]` · default `[".tmb", ".quarantine"]`

Names hidden from listings, folders and files alike (the thumbnail folder is also hidden while thumbnails are on).

### `defaultPermission` {#defaultPermission}
`integer` · default `0o775` (509)

Not used: folders are created with the process umask.

### `allowReplaceSourceFile` {#allowReplaceSourceFile}
`boolean` · default `true`

Not used.

## Images

### `imageExtensions` {#imageExtensions}
`string[]` · default `["jpg", "png", "gif", "jpeg", "bmp", "svg", "ico", "webp"]`

Extensions treated as images: listed with `isImage: true` and given real thumbnails.

### `quality` {#quality}
`integer` · default `90`

JPEG and WebP quality of thumbnails.

### `maxImageWidth`, `maxImageHeight` {#maxImageWidth}
`integer` · default `1900`

Not enforced (kept for configuration compatibility).

## Thumbnails

### `createThumb` {#createThumb}
`boolean` · default `true`

Create thumbnails while listing. Image thumbnails fit into a `thumbSize` square (never enlarged) and keep PNG, GIF and WebP formats; other formats become JPEG. SVG images are their own thumbnails.

### `thumbSize` {#thumbSize}
`integer` · default `250`

Side of the thumbnail square, in pixels.

### `thumbFolderName` {#thumbFolderName}
`string` · default `"_thumbs"`

Folder, inside each listed folder, where thumbnails are stored.

### `safeThumbsCountInOneTime` {#safeThumbsCountInOneTime}
`integer` · default `20`

How many new thumbnails one listing may create. Items after that come without `thumb` and get one on a later listing, so a large folder does not make one request slow.

### SVG icons {#svg-icons}

Folders and non-image files get SVG icons, drawn by the `svg_generator` argument of [`create_app()`](usage.md) (a colored page with the extension by default).

| Key | Type · default | Meaning |
|---|---|---|
| `generateSvgThumbs` | `boolean` · `true` | Draw icons; when `false` such items point to the file itself |
| `svgThumbWidth` | `integer` · `100` | Width passed to the generator |
| `svgThumbHeight` | `integer` · `100` | Height passed to the generator |

A generator takes the entry (`StatEntry` with `path`, `is_file`, `is_directory`, `size`), the width and the height, and returns SVG markup. Escape names you put into the markup:

```python
--8<-- "examples/custom_svg.py:build"
```

The generator is an argument, not a setting, so it is the same for every source of an instance.

## Access and security

### `accessControl` {#accessControl}
`rule[]` · default `[]`

Access rules; see [Access Control](access-control.md). Rules computed in code or loaded at runtime are passed as `access_control=` instead.

### `defaultRole` {#defaultRole}
`string` · default `"guest"`

Role of every request when there is no `check_authentication` callback. See [Authentication](authentication.md).

### `roleSessionVar` {#roleSessionVar}
`string` · default `"JoditUserRole"`

Not used: roles come from `check_authentication`.

### `allowCrossOrigin` {#allowCrossOrigin}
`boolean` · default `false`

Answer cross-origin requests with CORS headers (`Access-Control-Allow-Origin` echoing the origin, `Access-Control-Allow-Credentials: true`) and handle `OPTIONS` preflights.

### `allowedOrigins` {#allowedOrigins}
`string[] | null` · default `null`

Origins accepted when `allowCrossOrigin` is on; `null` accepts every origin. Requests from other origins get no CORS headers and their preflights get `403`. A function deciding per request is passed as `allowed_origins=` to `create_app()`.

### `onlyPOST` {#onlyPOST}
`boolean` · default `false`

Reject every `GET` with `405`, `/ping` included. Links, images and scripts on other sites can only send `GET`, so this blocks cross-site triggering of actions when cookies authenticate requests. Configure Jodit to use POST then:

```javascript
Jodit.make('#editor', {
  uploader: { url: '/connector/?action=fileUpload' },
  filebrowser: { ajax: { url: '/connector/', method: 'POST' } }
});
```

### `allowPrivateNetworkUploads` {#allowPrivateNetworkUploads}
`boolean` · default `false`

Let `fileUploadRemote` fetch from private and local addresses. Keep it off unless the connector runs in a trusted network and must download from internal hosts.

## Limits

### `timeoutLimit` {#timeoutLimit}
`integer` · default `60`

Network timeout, in seconds, of `fileUploadRemote` downloads and of remote resources in PDF/DOCX generation.

### `memoryLimit` {#memoryLimit}
`string` · default `"256M"`

Not used.

## Documents

### `pdf` {#pdf}
`object`

| Key | Default | Meaning |
|---|---|---|
| `isRemoteEnabled` | `true` | Load remote images, styles and fonts (public `http`/`https` only) in PDF and DOCX; `false` blocks all of them |
| `defaultFont` | `"serif"` | Not used |
| `fontDir`, `fontCache`, `tempDir`, `chroot` | temp dir | Not used |
| `paper` | `{"format": "A4", "page_orientation": "portrait"}` | Not used: the page comes from `options[...]` of `generatePdf` |

See [Documents](documents.md).

## Per-source overrides

A source may set any global setting except `sources`; the value applies to that source only.

```json
{
  "extensions": ["txt", "pdf", "doc", "docx"],
  "maxUploadFileSize": "10mb",
  "thumbSize": 250,
  "sources": {
    "images": {
      "title": "Images",
      "root": "/var/www/images",
      "baseurl": "https://cdn.example.com/images/",
      "extensions": ["jpg", "jpeg", "png", "gif", "webp"],
      "maxUploadFileSize": "5mb",
      "thumbSize": 150
    },
    "videos": {
      "title": "Videos",
      "root": "/var/www/videos",
      "baseurl": "https://cdn.example.com/videos/",
      "extensions": ["mp4", "webm", "mov"],
      "maxUploadFileSize": "500mb",
      "createThumb": false
    },
    "temp": {
      "title": "Temporary",
      "root": "/var/www/temp",
      "baseurl": "https://cdn.example.com/temp/",
      "saveSameFileNameStrategy": "replace",
      "datetimeFormat": "DD.MM.YYYY HH:mm"
    }
  }
}
```

Overrides are validated like global settings; an invalid one stops the start with the source name in the message. Settings that act before a source is known (`onlyPOST`, CORS, `accessControl`, `defaultRole`) are read from the global level only.

## Examples

### Minimal

```json
{
  "sources": {
    "default": {
      "title": "Files",
      "root": "/var/www/files",
      "baseurl": "https://example.com/files/"
    }
  }
}
```

### Production

```json
{
  "debug": false,
  "allowCrossOrigin": true,
  "allowedOrigins": ["https://app.example.com"],
  "onlyPOST": true,
  "maxUploadFileSize": "10mb",
  "safeThumbsCountInOneTime": 10,
  "defaultRole": "guest",
  "accessControl": [
    { "role": "guest", "FILE_UPLOAD": false, "FILE_UPLOAD_REMOTE": false,
      "FILE_REMOVE": false, "FILE_MOVE": false, "FILE_RENAME": false,
      "FOLDER_CREATE": false, "FOLDER_REMOVE": false, "FOLDER_MOVE": false,
      "FOLDER_RENAME": false, "IMAGE_RESIZE": false, "IMAGE_CROP": false,
      "IMAGE_SAVE": false },
    { "role": "user", "FILE_UPLOAD": true, "IMAGE_SAVE": true }
  ],
  "sources": {
    "uploads": {
      "title": "Uploads",
      "root": "/var/www/uploads",
      "baseurl": "https://cdn.example.com/uploads/"
    }
  }
}
```

### Fast listings

```json
{
  "debug": false,
  "createThumb": false,
  "countInChunk": 100,
  "excludeDirectoryNames": [".git", "node_modules", ".tmb", ".quarantine"],
  "sources": {
    "archive": {
      "title": "Archive",
      "root": "/srv/archive",
      "baseurl": "https://archive.example.com/"
    }
  }
}
```
