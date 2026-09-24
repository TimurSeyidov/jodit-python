"""OpenAPI document of the connector API."""

from dataclasses import dataclass, field
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Literal

from pydantic.json_schema import models_json_schema

from jcpy.openapi import models as m

if TYPE_CHECKING:
    from pydantic import BaseModel

REF = "#/components/schemas/{model}"
DOCX_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
ERROR_DESCRIPTIONS = {
    400: "Invalid parameters or request",
    403: "Access denied",
    404: "Source, path or file not found",
    405: "Method not allowed",
    413: "Request body too large",
    422: "Non-numeric paging parameters",
    500: "Internal error",
}


@dataclass(frozen=True, slots=True)
class ActionDoc:
    """Documentation of one action.

    Attributes:
        name: Action name, also the path (``/<name>``).
        summary: One-line summary.
        description: Longer description.
        tag: Group in the documentation.
        method: Documented HTTP method (both GET and POST work unless
            the action requires POST).
        query: Model of the query parameters.
        body: Media type and model of the request body.
        response: Model of the successful JSON answer (ignored when
            ``binary`` is set).
        binary: Media type of a file answer instead of JSON.
        errors: Documented error statuses.
    """

    name: str
    summary: str
    description: str
    tag: str
    method: Literal["get", "post"] = "get"
    query: type[BaseModel] | None = None
    body: tuple[str, type[BaseModel]] | None = None
    response: type[BaseModel] = m.DoneResponse
    binary: str | None = None
    errors: tuple[int, ...] = field(default=(400, 403, 404, 500))


ACTIONS: tuple[ActionDoc, ...] = (
    ActionDoc(
        "files",
        "Get list of files",
        "Lists files (and optionally folders) of a directory in the "
        "requested source or in every source.",
        "Files",
        query=m.FilesQuery,
        response=m.FilesResponse,
        errors=(400, 403, 404, 422, 500),
    ),
    ActionDoc(
        "fileUpload",
        "Upload files",
        "Uploads one or more files into a directory via multipart/form-data.",
        "Files",
        method="post",
        body=("multipart/form-data", m.UploadForm),
        response=m.UploadResponse,
    ),
    ActionDoc(
        "fileUploadRemote",
        "Upload file from remote URL",
        "Downloads a file from a public http(s) URL into a directory. "
        "Private and local addresses are refused unless "
        "allowPrivateNetworkUploads is on.",
        "Files",
        query=m.RemoteUploadQuery,
        response=m.RemoteUploadResponse,
    ),
    ActionDoc(
        "fileRemove",
        "Remove file",
        "Removes a file from a directory.",
        "Files",
        query=m.NameQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "fileMove",
        "Move file or folder",
        "Moves a file or folder (`from`, relative to the root) into the "
        "directory `path`.",
        "Files",
        query=m.MoveQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "fileCopy",
        "Copy file",
        'Copies a file; a taken name gets a " (N)" suffix, so copying '
        "into the same folder duplicates the file.",
        "Files",
        query=m.MoveQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "fileRename",
        "Rename file or folder",
        "Renames an entry of a directory; files keep their extension.",
        "Files",
        query=m.RenameQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "fileDownload",
        "Download file",
        "Sends a file as an attachment.",
        "Files",
        query=m.NameQuery,
        binary="application/octet-stream",
    ),
    ActionDoc(
        "getLocalFileByUrl",
        "Resolve local file by URL",
        "Finds which source file a public URL points to.",
        "Files",
        query=m.UrlQuery,
        response=m.LocalFileResponse,
        errors=(400, 403, 500),
    ),
    ActionDoc(
        "folders",
        "Get folders list",
        "Lists the sub-folders of a directory in the requested source or "
        "in every source.",
        "Folders",
        query=m.FoldersQuery,
        response=m.FoldersResponse,
    ),
    ActionDoc(
        "folderCreate",
        "Create new folder",
        "Creates a folder; unsafe characters of the name become `_`.",
        "Folders",
        query=m.FolderCreateQuery,
        response=m.MessagesResponse,
    ),
    ActionDoc(
        "folderRemove",
        "Remove folder",
        "Removes a folder with everything in it.",
        "Folders",
        query=m.NameQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "folderMove",
        "Move folder",
        "Moves a folder (`from`, relative to the root) into `path`.",
        "Folders",
        query=m.MoveQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "folderCopy",
        "Copy folder",
        'Copies a folder recursively; a taken name gets a " (N)" suffix. '
        "Copying a folder into itself is refused.",
        "Folders",
        query=m.MoveQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "folderRename",
        "Rename folder",
        "Renames a folder of a directory.",
        "Folders",
        query=m.RenameQuery,
        response=m.DoneResponse,
    ),
    ActionDoc(
        "imageResize",
        "Resize image",
        "Scales an image to `box[w]` x `box[h]` in place or as `newname`.",
        "Images",
        query=m.ImageResizeQuery,
        response=m.ImageResponse,
    ),
    ActionDoc(
        "imageCrop",
        "Crop image",
        "Cuts the `box` region out of an image in place or as `newname`.",
        "Images",
        query=m.ImageCropQuery,
        response=m.ImageResponse,
    ),
    ActionDoc(
        "imageSave",
        "Save an edited image",
        "Stores the image produced by the client-side image editor as "
        "`newname` or over `name`. POST only.",
        "Images",
        method="post",
        body=("multipart/form-data", m.ImageSaveForm),
        response=m.ImageSaveResponse,
        errors=(400, 403, 404, 405, 500),
    ),
    ActionDoc(
        "imageLoad",
        "Read an image as a base64 data URL",
        "Returns an image through the CORS-enabled API, for browsers that "
        "cannot read the file host directly. POST only.",
        "Images",
        method="post",
        body=("application/json", m.ImageLoadBody),
        response=m.ImageLoadResponse,
        errors=(400, 403, 404, 405, 500),
    ),
    ActionDoc(
        "generatePdf",
        "Generate PDF document",
        "Renders HTML as a PDF attachment. Remote resources are loaded "
        "only from public hosts (see pdf.isRemoteEnabled).",
        "Documents",
        query=m.GeneratePdfQuery,
        binary="application/pdf",
        errors=(400, 403, 500),
    ),
    ActionDoc(
        "generateDocx",
        "Generate DOCX document",
        "Converts HTML into a Word document attachment.",
        "Documents",
        query=m.GenerateDocxQuery,
        binary=DOCX_TYPE,
        errors=(400, 403, 500),
    ),
    ActionDoc(
        "permissions",
        "Get permissions",
        "Reports which actions the user may run in a directory.",
        "System",
        query=m.SourceQuery,
        response=m.PermissionsResponse,
    ),
)


def _models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = [m.ErrorResponse, m.PingResponse]
    for action in ACTIONS:
        models += [
            model
            for model in (
                action.query,
                action.body[1] if action.body else None,
                None if action.binary else action.response,
            )
            if model is not None
        ]
    return list(dict.fromkeys(models))


def _json(schema: type[BaseModel] | str) -> dict[str, Any]:
    name = schema if isinstance(schema, str) else schema.__name__
    return {"application/json": {"schema": {"$ref": REF.format(model=name)}}}


def _not_null(prop: dict[str, Any]) -> dict[str, Any]:
    options = prop.get("anyOf", [])
    kept = [option for option in options if option != {"type": "null"}]
    if len(kept) != 1 or len(options) != 2:
        return prop
    extra = {
        key: value
        for key, value in prop.items()
        if key not in {"anyOf", "default"}
    }
    return {**kept[0], **extra}


def _parameter(
    name: str, full: dict[str, Any], *, required: bool
) -> dict[str, Any]:
    prop = _not_null(full)
    parameter: dict[str, Any] = {
        "name": name,
        "in": "query",
        "required": required,
        "schema": prop,
    }
    if "description" in prop:
        parameter["description"] = prop["description"]
    return parameter


def _parameters(
    model: type[BaseModel], definitions: dict[str, Any]
) -> list[dict[str, Any]]:
    """Describe the query parameters of a model.

    Nested objects become one parameter per field in bracket notation
    (``box[w]``), as clients send them; unlike ``deepObject`` this lets
    Swagger UI leave out fields the user did not fill in.
    """
    schema = definitions[model.__name__]
    required = set(schema.get("required", []))
    parameters: list[dict[str, Any]] = []
    for name, full in schema["properties"].items():
        prop = _not_null(full)
        if "$ref" not in prop:
            parameters.append(
                _parameter(name, full, required=name in required)
            )
            continue
        nested = definitions[prop["$ref"].rsplit("/", 1)[-1]]
        nested_required = set(nested.get("required", []))
        parameters.extend(
            _parameter(
                f"{name}[{field}]",
                field_schema,
                required=name in required and field in nested_required,
            )
            for field, field_schema in nested["properties"].items()
        )
    return parameters


def _operation(
    action: ActionDoc, definitions: dict[str, Any]
) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    if action.binary is not None:
        responses["200"] = {
            "description": "File",
            "content": {
                action.binary: {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    else:
        responses["200"] = {
            "description": "Success",
            "content": _json(action.response),
        }
    for status in action.errors:
        responses[str(status)] = {
            "description": ERROR_DESCRIPTIONS[status],
            "content": _json("ErrorResponse"),
        }
    operation: dict[str, Any] = {
        "operationId": action.name,
        "summary": action.summary,
        "description": (
            f"{action.description}\n\nAlso available as "
            f"`/?action={action.name}`."
        ),
        "tags": [action.tag],
        "responses": responses,
    }
    if action.query is not None:
        operation["parameters"] = _parameters(action.query, definitions)
    if action.body is not None:
        media_type, model = action.body
        operation["requestBody"] = {
            "required": True,
            "content": {
                media_type: {
                    "schema": {"$ref": REF.format(model=model.__name__)}
                }
            },
        }
    return operation


def build_openapi(
    servers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build the OpenAPI 3.1 document of every connector action.

    Args:
        servers: ``servers`` entries; a local development server by
            default.

    Returns:
        OpenAPI document as a JSON-compatible dict.
    """
    _, schema = models_json_schema(
        [(model, "validation") for model in _models()], ref_template=REF
    )
    definitions: dict[str, Any] = schema["$defs"]
    paths: dict[str, Any] = {
        "/ping": {
            "get": {
                "operationId": "ping",
                "summary": "Health check",
                "description": (
                    "Answers before authentication and tenant "
                    "resolution; adds CORS headers for allowed origins."
                ),
                "tags": ["System"],
                "responses": {
                    "200": {
                        "description": "Service is running",
                        "content": _json(m.PingResponse),
                    }
                },
            }
        }
    }
    for action in ACTIONS:
        paths[f"/{action.name}"] = {
            action.method: _operation(action, definitions)
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Jodit Connector API",
            "version": version("jodit-python"),
            "description": "Jodit FileBrowser and Uploader connector for "
            "Python, API-compatible with jodit-nodejs.",
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "servers": servers
        or [
            {
                "url": "http://localhost:8081/",
                "description": "Local development server",
            }
        ],
        "paths": paths,
        "components": {"schemas": definitions},
    }
