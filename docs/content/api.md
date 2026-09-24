---
title: API Endpoints
description: Every connector action with its parameters, answers and errors.
---

# API Endpoints

The interactive version of this page, generated from the schemas, is the
[API Reference](api-swagger/index.md).

## Calling convention

An action is named either in the path or in the `action` parameter:

```text
GET  /files?source=default&path=photos
GET  /?action=files&source=default&path=photos
POST /                      (body: action=files&source=default&path=photos)
```

- Parameters come from the query string, a form body
  (`application/x-www-form-urlencoded` or `multipart/form-data`) or a
  JSON body. When a name is in several places the path wins over the
  query string, and the query string over the body.
- Nested values use brackets, as the `qs` package parses them:
  `box[w]=100&box[h]=50`, `mods[withFolders]=true`, `files[0]=...`.
- Every action accepts `GET` and `POST`, except `imageSave` and
  `imageLoad` (POST only). With [`onlyPOST`](config.md#onlyPOST) every
  `GET` gets `405`.
- `source` selects a source; without it listings (`files`, `folders`)
  cover every source (and fail with `404` if `path` is missing in any
  of them) and other actions use the first one. `path` is a directory
  inside the source (the root when omitted).

### Answers

```json
{"success": true, "data": {"code": 220, "...": "..."}}
```

Errors carry the HTTP status in the status line and in `data.code`:

```json
{"success": false, "data": {"code": 404, "messages": ["File or directory not exists"]}}
```

| Status | When |
|---|---|
| `400` | Invalid or missing parameters (`messages` lists every problem), unsafe names |
| `403` | Denied by [access rules](access-control.md), file type not allowed, file too large, private address in `fileUploadRemote` |
| `404` | Unknown action, source, path or file |
| `405` | `GET` with `onlyPOST`, or `GET` to a POST-only action |
| `413` | JSON or urlencoded body over 100 KB (as in Express; multipart uploads are limited by `maxUploadFileSize` instead) |
| `422` | Non-numeric `mods[offset]` / `mods[limit]` |
| `500` | Storage or processing failure |

## System

### `GET /ping`

Health check. Needs no token or tenant (it answers before
authentication and `resolve_sources`, after `onlyPOST`); CORS headers are
added for allowed origins.

```json
{"success": true}
```

### `permissions`

What the current user may do in `path` of the first (or given) source.

```bash
curl "http://localhost:8081/permissions?path=photos"
```

```json
{
  "success": true,
  "data": {
    "code": 220,
    "permissions": {
      "allowFiles": true,
      "allowFileMove": true,
      "allowFileCopy": true,
      "allowFileUpload": true,
      "allowFileUploadRemote": true,
      "allowFileRemove": true,
      "allowFileRename": true,
      "allowFileDownload": true,
      "allowFolders": true,
      "allowFolderMove": true,
      "allowFolderCopy": true,
      "allowFolderCreate": true,
      "allowFolderRemove": true,
      "allowFolderRename": true,
      "allowFolderTree": true,
      "allowImageResize": true,
      "allowImageCrop": true,
      "allowImageSave": true,
      "allowImageLoad": true,
      "allowGeneratePdf": true,
      "allowGenerateDocx": true
    }
  }
}
```

## Files

### `files`

Lists a directory of one or every source.

| Parameter | Meaning |
|---|---|
| `source`, `path` | Where to list |
| `mods[withFolders]` | Include folders |
| `mods[onlyImages]` | Only image files |
| `mods[sortBy]` | `name-asc`, `name-desc`, `changed-asc`, `changed-desc` (default, see `defaultSortBy`), `size-asc`, `size-desc` |
| `mods[foldersPosition]` | `default`, `top`, `bottom` |
| `mods[filterWord]` | Keep names containing it (case-insensitive) |
| `mods[offset]`, `mods[limit]` | Page of the list |

```bash
curl "http://localhost:8081/files?path=photos&mods[sortBy]=name-asc"
```

```json
{
  "success": true,
  "data": {
    "code": 220,
    "sources": [
      {
        "name": "default",
        "title": "Files",
        "baseurl": "http://localhost:8080/files/",
        "path": "photos",
        "files": [
          {
            "file": "photo.jpg",
            "name": "photo.jpg",
            "type": "image",
            "isImage": true,
            "size": "5.3KB",
            "changed": "9/24/2026 4:41:56 PM",
            "thumb": "_thumbs/photo.jpg"
          }
        ]
      }
    ]
  }
}
```

Folders (with `mods[withFolders]`) have only `file`, `name`,
`type: "folder"` and `thumb`. `thumb` and `file` are relative to
`baseurl` + `path`. Thumbnails of images are created on first listing
(see [Thumbnails](config.md#thumbnails)); folders and other files get
SVG icons.

### `fileUpload` (POST, multipart)

Uploads files into `path`. Files are sent as `files[0]`, `files[1]`, ...
or in the field named by [`defaultFilesKey`](config.md#defaultFilesKey)
(`default` unless configured); other file fields are ignored.

```bash
curl -F "path=photos" -F "files[0]=@a.png" -F "files[1]=@b.jpg" \
  http://localhost:8081/fileUpload
```

```json
{
  "success": true,
  "data": {
    "code": 220,
    "baseurl": "http://localhost:8080/files/",
    "messages": ["File a.png was uploaded", "File b.jpg was uploaded"],
    "files": ["photos/a.png", "photos/b.jpg"],
    "isImages": [true, true]
  }
}
```

Names are made safe (`sanitize-filename` rules); the extension must be in
`extensions` and the size within `maxUploadFileSize`; an existing name is
handled by `saveSameFileNameStrategy`.

### `fileUploadRemote`

Downloads `url` into `path`.

```bash
curl "http://localhost:8081/fileUploadRemote?url=https://example.com/a.png&path=photos"
```

```json
{"success": true, "data": {"code": 220, "baseurl": "http://localhost:8080/files/", "newfilename": "a.png", "isImage": true}}
```

!!! info "SSRF protection"
    Only `http`/`https` URLs whose host resolves to public addresses
    are fetched; loopback, private, link-local, reserved ranges and
    their IPv6 forms (mapped, NAT64, 6to4, Teredo) get `403`. The
    connection goes to the checked address, each redirect (at most 5)
    is checked again, and the download stops as soon as it exceeds
    `maxUploadFileSize` (network timeout: `timeoutLimit` seconds).
    `allowPrivateNetworkUploads: true` lifts the address check for
    trusted internal setups.

### `fileRemove`

Removes file `name` from `path`.

```bash
curl "http://localhost:8081/fileRemove?path=photos&name=a.png"
```

```json
{"success": true, "data": {"code": 220}}
```

### `fileMove`, `fileCopy`

Move or copy the entry `from` (path from the source root) into the
directory `path` (the root when omitted). A copy into a folder that
already has the name gets a ` (1)`, ` (2)`... suffix, so copying into
the same folder duplicates the file. `fileMove` moves folders too.

```bash
curl "http://localhost:8081/fileMove?from=photos/a.png&path=archive"
curl "http://localhost:8081/fileCopy?from=photos/a.png&path=photos"
```

Answer: `{"success": true, "data": {"code": 220}}`.

### `fileRename`

Renames `name` in `path` to `newname`; a file keeps its extension
(`newname=notes` turns `readme.txt` into `notes.txt`).

```bash
curl "http://localhost:8081/fileRename?name=readme.txt&newname=notes"
```

### `fileDownload`

Sends file `name` from `path` as an attachment
(`application/octet-stream`).

```bash
curl -OJ "http://localhost:8081/fileDownload?path=docs&name=report.pdf"
```

### `getLocalFileByUrl`

Finds which source file a public URL points to.

```bash
curl "http://localhost:8081/getLocalFileByUrl?url=http://localhost:8080/files/photos/photo.jpg"
```

```json
{"success": true, "data": {"code": 220, "path": "/photos", "name": "photo.jpg", "source": "default"}}
```

## Folders

### `folders`

Lists sub-folders of `path` in one or every source. The list starts
with `.` at the root and `..` below it (`dots=false` omits them).

```json
{
  "success": true,
  "data": {
    "sources": [
      {
        "name": "default",
        "title": "Files",
        "baseurl": "http://localhost:8080/files/",
        "path": "/",
        "folders": [".", "photos"]
      }
    ],
    "code": 220
  }
}
```

### `folderCreate`

Creates folder `name` in `path`.

```json
{"success": true, "data": {"code": 220, "messages": ["Directory successfully created"]}}
```

### `folderRemove`

Removes folder `name` from `path` with its contents.

### `folderMove`, `folderCopy`

Like `fileMove` / `fileCopy` for folders; copying or moving a folder
into itself fails with `400`.

### `folderRename`

Renames folder `name` in `path` to `newname`.

## Images

### `imageResize`

Scales image `name` in `path` to `box[w]` x `box[h]` pixels, over the
original or as `newname`.

```bash
curl "http://localhost:8081/imageResize?path=photos&name=photo.jpg&box[w]=320&box[h]=240&newname=small.jpg"
```

```json
{"success": true, "data": {"code": 220, "newPath": "http://localhost:8080/files/photos/small.jpg"}}
```

### `imageCrop`

Cuts the region `box[x]`, `box[y]`, `box[w]`, `box[h]` out of image
`name`; same answer as `imageResize`.

### `imageSave` (POST, multipart)

Stores the image produced by Jodit's image editor (the final bytes, with
crop and filters applied) as `newname`, or over `name`. The image is the first file of the form
(`files[0]` or the `defaultFilesKey` field).

```bash
curl -F "path=photos" -F "newname=photo-edited.png" \
  -F "files[0]=@edited.png;type=image/png" \
  http://localhost:8081/imageSave
```

```json
{"success": true, "data": {"code": 220, "newPath": "http://localhost:8080/files/photos/photo-edited.png", "name": "photo-edited.png"}}
```

### `imageLoad` (POST)

Returns image `name` from `path` as a base64 data URL, for pages that
cannot read the file host directly (no CORS there).

```bash
curl -H "Content-Type: application/json" \
  -d '{"path": "photos", "name": "photo.jpg"}' \
  http://localhost:8081/imageLoad
```

```json
{"success": true, "data": {"code": 220, "content": "data:image/jpeg;base64,/9j/4AAQ...", "name": "photo.jpg"}}
```

## Documents

See [Documents](documents.md) for rendering details.

### `generatePdf`

Renders `html` as `document.pdf`. `options[format]`: `A4` (default),
`A3`, `Letter`, `Legal`, `Tabloid`; `options[page_orientation]`:
`portrait` (default) or `landscape`.

```bash
curl -o document.pdf --data-urlencode "html=<h1>Hello</h1>" \
  "http://localhost:8081/generatePdf?options[format]=Letter"
```

### `generateDocx`

Converts `html` into `document.docx`.

```bash
curl -o document.docx --data-urlencode "html=<h1>Hello</h1>" \
  http://localhost:8081/generateDocx
```
