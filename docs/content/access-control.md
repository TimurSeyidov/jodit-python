---
title: Access Control (ACL)
description: Access rules by role, path and extension; rules loaded at runtime; custom implementations.
---

# Access Control (ACL)

Every request is checked against access rules before its action runs,
and actions check again for each directory or file they touch.

## Rules

A rule selects requests by `role`, `path` and `extensions` (a missing
selector matches everything) and sets actions to `true` or `false`:

```json
{
  "defaultRole": "guest",
  "accessControl": [
    { "role": "guest", "FILE_UPLOAD": false, "FILE_REMOVE": false,
      "FOLDER_CREATE": false, "FOLDER_REMOVE": false },
    { "role": "guest", "path": "/private", "FILES": false, "FOLDERS": false },
    { "role": "editor", "extensions": "jpg,png,gif", "FILE_UPLOAD": true },
    { "role": "admin", "FILE_UPLOAD": true, "FILE_REMOVE": true,
      "FOLDER_CREATE": true, "FOLDER_REMOVE": true },
    { "role": "*", "path": "/public", "FILES": true }
  ]
}
```

| Key | Meaning |
|---|---|
| `role` | Role from [`check_authentication`](authentication.md) (or `defaultRole`); `*` matches every role |
| `path` | Directory prefix, relative to the source root and starting with `/` |
| `extensions` | Extensions the rule applies to, as `"jpg,png"` or `["jpg", "png"]`; `*` for all |
| `ACTION_NAME` | `true` allows, `false` denies |

## Matching

For each check (role, action, path, extension):

1. A rule **applies** when its `role` is missing, `*` or equal to the
   role; the path starts with its `path`; and its `extensions` contain
   `*` or the extension of the file.
2. Among the rules that apply and mention the action, **the last one
   decides**. Put general rules first and exceptions after them.
3. When no rule decides, the action is **allowed** (every entry of
   `DEFAULT_RULES` is `true`, as in jodit-nodejs).

!!! warning "Allowed unless denied"
    Without rules everything is allowed. To deny by default, start
    with a rule that denies every action for every role and allow what
    each role needs after it (see [deny by default](#deny-by-default)).

The requested `path` is normalized before matching: `private`,
`./private`, `//private` and `/public/../private` are all checked as
`/private`. The path test is a plain prefix test (as in jodit-nodejs),
so a rule for `/private` also covers `/private-2`; name folders
accordingly. Extensions are only known when a file
is involved (uploads, for instance); checks of whole directories use
`*`, which a rule with a narrower `extensions` list does not match.

## Actions

Rule keys are action names in CONSTANT_CASE:

| Rule key | Action | | Rule key | Action |
|---|---|---|---|---|
| `FILES` | `files` | | `FOLDERS` | `folders` |
| `FILE_UPLOAD` | `fileUpload` | | `FOLDER_CREATE` | `folderCreate` |
| `FILE_UPLOAD_REMOTE` | `fileUploadRemote` | | `FOLDER_REMOVE` | `folderRemove` |
| `FILE_REMOVE` | `fileRemove` | | `FOLDER_MOVE` | `folderMove` |
| `FILE_MOVE` | `fileMove` | | `FOLDER_COPY` | `folderCopy` |
| `FILE_COPY` | `fileCopy` | | `FOLDER_RENAME` | `folderRename` |
| `FILE_RENAME` | `fileRename` | | `IMAGE_RESIZE` | `imageResize` |
| `FILE_DOWNLOAD` | `fileDownload` | | `IMAGE_CROP` | `imageCrop` |
| `GET_LOCAL_FILE_BY_URL` | `getLocalFileByUrl` | | `IMAGE_SAVE` | `imageSave` |
| `PERMISSIONS` | `permissions` | | `IMAGE_LOAD` | `imageLoad` |
| `GENERATE_PDF` | `generatePdf` | | `GENERATE_DOCX` | `generateDocx` |

`FOLDER_TREE` is reported by `permissions` for Jodit's folder tree.
The `permissions` action tells the client what the current role may do
in a directory, so Jodit hides buttons of denied actions.

## Deny by default

```json
{
  "defaultRole": "anonymous",
  "accessControl": [
    { "FILES": false, "FOLDERS": false, "FILE_UPLOAD": false,
      "FILE_UPLOAD_REMOTE": false, "FILE_REMOVE": false, "FILE_MOVE": false,
      "FILE_COPY": false, "FILE_RENAME": false, "FILE_DOWNLOAD": false,
      "FOLDER_CREATE": false, "FOLDER_REMOVE": false, "FOLDER_MOVE": false,
      "FOLDER_COPY": false, "FOLDER_RENAME": false, "IMAGE_RESIZE": false,
      "IMAGE_CROP": false, "IMAGE_SAVE": false, "IMAGE_LOAD": false,
      "GENERATE_PDF": false, "GENERATE_DOCX": false,
      "GET_LOCAL_FILE_BY_URL": false, "PERMISSIONS": false },
    { "role": "viewer", "FILES": true, "FOLDERS": true, "PERMISSIONS": true },
    { "role": "editor", "FILES": true, "FOLDERS": true, "PERMISSIONS": true,
      "FILE_UPLOAD": true, "IMAGE_LOAD": true, "IMAGE_SAVE": true }
  ]
}
```

## Rules computed in code

JSON holds flags only. In rules built in code an action may be a
function, and `extensions` may be computed:

```python
from jcpy import AccessControlRule, create_app


def outside_protected(
    action: str, rule: AccessControlRule, path: str, extension: str
) -> bool:
    return not path.startswith("/protected")


def extensions_by_folder(
    action: str, rule: AccessControlRule, path: str, extension: str
) -> list[str]:
    # Upper case, as extensions are compared in upper case.
    return ["JPG", "PNG", "GIF"] if path.startswith("/images") else ["*"]


RULES = [
    AccessControlRule.model_validate(
        {"role": "editor", "FILE_UPLOAD": outside_protected}
    ),
    AccessControlRule.model_validate(
        {
            "role": "editor",
            "extensions": extensions_by_folder,
            "FILE_REMOVE": False,
        }
    ),
]

app = create_app("config.json", access_control=lambda: RULES)
```

Both functions get the action (CONSTANT_CASE), the rule, the path and
the extension (`*` when unknown). A predicate that returns something
other than a boolean allows the action.

## Rules loaded at runtime

`access_control=` takes a function (plain or `async`) called on
**every check**; it replaces the `accessControl` list of the
configuration. Rules can come from a database, a cache or an API and
change without a restart:

```python
from jcpy import AccessControlRule, create_app


async def load_rules() -> list[AccessControlRule]:
    rows = await db.fetch(
        "SELECT role, action, allowed FROM acl_rules "
        "WHERE active ORDER BY priority"
    )
    by_role: dict[str, dict[str, object]] = {}
    for row in rows:
        by_role.setdefault(row["role"], {"role": row["role"]})[
            row["action"]
        ] = row["allowed"]
    return [
        AccessControlRule.model_validate(item) for item in by_role.values()
    ]


app = create_app("config.json", access_control=load_rules)
```

### Caching

A request can run several checks, so cache what is slow to load, and
keep the last good rules when loading fails:

```python
import logging
import time

from jcpy import AccessControlRule

SAFE_DEFAULTS = [
    AccessControlRule.model_validate(
        {"FILE_UPLOAD": False, "FILE_REMOVE": False}
    )
]
TTL = 60.0

_rules: list[AccessControlRule] = SAFE_DEFAULTS
_expires = 0.0


async def cached_rules() -> list[AccessControlRule]:
    global _rules, _expires
    now = time.monotonic()
    if now < _expires:
        return _rules
    try:
        _rules = await load_rules()
    except Exception:
        logging.getLogger(__name__).exception("Cannot load ACL rules")
    _expires = now + TTL
    return _rules
```

## Custom implementation

`access_control_instance=` replaces the rule engine altogether. It is an
object with two async methods (`jcpy.AccessControlProtocol`):

```python
from jcpy import HttpError, create_app


class PolicyServiceAccess:
    async def is_allow(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        return await policy_service.allowed(role, action, path)

    async def check_permission(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        if not await self.is_allow(role, action, path, file_extension):
            raise HttpError.forbidden("Access denied")
        return True


app = create_app("config.json", access_control_instance=PolicyServiceAccess())
```

`action` arrives in the spelling of the call site (`fileUpload` or
`FILE_UPLOAD`); `jcpy.AccessControl` normalizes it with a CONSTANT_CASE
conversion, and so should a custom implementation.

## Per source

Rules are per connector instance, not per source. Different rules for
different sources are made with separate instances
([FastAPI Integration](integration.md#5-several-instances)) or with
[dynamic sources](dynamic-sources.md) together with a role per tenant.
