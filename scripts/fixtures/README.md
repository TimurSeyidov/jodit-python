# Fixture generators

Parts of jodit-python reproduce JavaScript libraries whose results
clients see: how `qs` parses `box[w]=1&mods[sortBy]=...`, how `bytes`
and Day.js format `size` and `changed`, how uploaded names are made
safe, the zod error texts, Node's `path` handling, the sort order and
the SVG icons of jodit-nodejs.

These scripts run the **original** packages (or jodit-nodejs code) on
many inputs and store the results in `tests/fixtures/*.json`; the
Python tests compare the port with them.

Node.js is only needed to regenerate a fixture, e.g. after moving to a
new version of the library. Running the tests, `make check` and CI use
the committed JSON files and do not need Node.

Each script's header shows how to run it: which package version to
install (`npm install --no-save ...`, in a scratch directory) and where
the output goes. Run them from the repository root.

| Script | Reproduces | Fixture | Test |
|---|---|---|---|
| `generate_qs_fixtures.cjs` | `qs` 6.16 (query and urlencoded parsing) | `qs_cases.json` | `test_qs.py` |
| `generate_append_field_fixtures.cjs` | `append-field` 1.0 (multipart field names) | `append_field_cases.json` | `test_append_field.py` |
| `generate_format_fixtures.mjs` | `bytes`, Day.js, `slugify`, zod messages | `format_cases.json` | `test_formatting.py` |
| `generate_upload_fixtures.cjs` | `sanitize-filename`, `bytes.parse` | `upload_cases.json` | `test_upload_helpers.py` |
| `generate_extname_fixtures.cjs` | Node `path.extname` / `basename` | `extname_cases.json` | `test_upload_helpers.py` |
| `generate_path_fixtures.cjs` | Node `path` in sources, flystorage path normalizer | `path_cases.json` | `test_paths.py` |
| `generate_url_fixtures.cjs` | WHATWG `new URL()` | `url_cases.json` | `test_listing_helpers.py` |
| `generate_case_fixtures.mjs` | `change-case` 5.4 | `case_cases.json` | `test_case.py` |
| `generate_sort_fixtures.mjs` | jodit-nodejs `sortByMode` | `sort_cases.json` | `test_listing_helpers.py` |
| `generate_icon_fixtures.mjs` | jodit-nodejs `generateIcon` | `icon_cases.json` | `test_formatting.py` |
| `generate_image_schema_fixtures.mjs` | jodit-nodejs image schemas (zod 4) | `image_schema_cases.json` | `test_image_validation.py` |
| `generate_document_schema_fixtures.mjs` | jodit-nodejs PDF/DOCX schemas (zod 4) | `document_schema_cases.json` | `test_documents.py` |

`.cjs` files are CommonJS (`require`), for packages published that way
and Node built-ins; `.mjs` files are ES modules (`import`), for
ESM-only packages (`change-case` 5) and for importing jodit-nodejs
TypeScript sources with `node --experimental-strip-types`.
