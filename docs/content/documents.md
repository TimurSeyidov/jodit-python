---
title: Documents (PDF & DOCX)
description: How generatePdf and generateDocx render HTML, what they load and their limits.
---

# Documents (PDF & DOCX)

Jodit's "Export" buttons send the editor's HTML to `generatePdf` and
`generateDocx`; the connector answers with the file as an attachment.

## PDF

`generatePdf` renders with [WeasyPrint](https://weasyprint.org/):

- Page: `options[format]` (`A4`, `A3`, `Letter`, `Legal`, `Tabloid`)
  and `options[page_orientation]` (`portrait`, `landscape`), 1 cm
  margins; backgrounds are printed.
- CSS from `<style>` blocks, inline styles and allowed stylesheets
  applies, with WeasyPrint's print-oriented CSS support (flexbox and
  grid included).
- JavaScript is **not** run. The editor's HTML is static, so this rarely
  matters; content that scripts would create does not appear.
- Fonts are those installed on the server. The Docker image ships
  DejaVu and Liberation (Latin, Cyrillic, Greek). For Chinese,
  Japanese, Korean and other scripts install more fonts in a derived
  image, e.g. `apt install fonts-noto-cjk`.

jodit-nodejs renders with headless Chromium; layouts can differ in
details from Chrome's print output.

## DOCX

`generateDocx` converts with
[html-for-docx](https://pypi.org/project/html-for-docx/)
(python-docx):

- Supported: headings, paragraphs, bold/italic/underline, lists,
  tables, links, images and basic inline styles; margins are 0.5".
- `<style>`, `<script>` and `<link>` elements are dropped: use inline
  styles.
- Images are embedded; formats Word does not store (WebP...) are
  converted to PNG, undecodable images are left out.

Complex layouts can come out simpler than in the editor.

## Remote resources

Images, stylesheets and fonts referenced by URL are loaded by the
connector itself, with the same protection as
[`fileUploadRemote`](api.md#fileuploadremote):

- only `http`/`https` URLs on public addresses (private, loopback and
  link-local hosts are refused, redirects re-checked);
- at most [`maxFileSize`](config.md#maxFileSize) per resource,
  [`timeoutLimit`](config.md#timeoutLimit) seconds;
- `data:` URIs work; `file:` URLs and local paths are refused;
- `pdf.isRemoteEnabled: false` refuses every remote resource, for both
  PDF and DOCX.

A resource that cannot be loaded is left out; the document is still
produced.

## Request size

The HTML travels in the `html` parameter:

| Encoding | Limit |
|---|---|
| query string | what the proxy and server accept for a URL (a few KB is safe) |
| `application/x-www-form-urlencoded` or JSON body | 100 KB (`413` above) |
| `multipart/form-data` field | 1 MB (`400` above) |

Jodit posts the export as a form, so documents with large embedded
(`data:`) images may need multipart or links to hosted images instead.

```bash
curl -o document.pdf -F "html=<report.html" \
  "http://localhost:8081/generatePdf?options[format]=A4"
```
