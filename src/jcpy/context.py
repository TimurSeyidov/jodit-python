"""Request parameters and the context passed to action handlers."""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from jcpy.errors import HttpError
from jcpy.helpers import append_field, qs
from jcpy.helpers.js import is_js_numeric, js_parse_float
from jcpy.helpers.merge import merge_without_nulls

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    from jcpy.acl import AccessControlProtocol
    from jcpy.config.models import AppConfig
    from jcpy.sources import Source, SourcePool
    from jcpy.types import JsonObject, JsonValue

BODY_LIMIT = 100 * 1024
"""Size limit of JSON and urlencoded bodies, as in Express."""

_JSON_TYPE = "application/json"
_FORM_TYPE = "application/x-www-form-urlencoded"
_MULTIPART_TYPE = "multipart/form-data"


def prepare_value(value: JsonValue) -> JsonValue:
    """Convert a raw parameter the way jodit-nodejs does.

    ``"true"``/``"false"`` become booleans, numeric strings become
    numbers (``parseFloat`` semantics), anything else is unchanged.

    Args:
        value: Raw parameter value.

    Returns:
        Converted value.
    """
    if not isinstance(value, str):
        return value
    if value in {"true", "false"}:
        return value == "true"
    if value and is_js_numeric(value):
        return js_parse_float(value)
    return value


def _child(data: JsonValue, key: str) -> JsonValue:
    if isinstance(data, dict):
        return data.get(key)
    if isinstance(data, list) and key.isdigit() and int(key) < len(data):
        return data[int(key)]
    return None


class RequestContext:
    """Parameters of one connector request.

    Body, query string and the ``/{action}`` path parameter are merged
    in that order of increasing priority; ``None`` never replaces a
    value.

    Args:
        data: Merged parameters.
        files: Uploaded files, in the order they were sent.
    """

    def __init__(
        self, data: JsonObject, files: list[UploadedFile] | None = None
    ) -> None:
        self.data = data
        self.files = files if files is not None else []

    @classmethod
    async def from_request(cls, request: Request) -> RequestContext:
        """Collect the parameters of an HTTP request.

        Args:
            request: Incoming request.

        Returns:
            Context with merged parameters and uploaded files.

        Raises:
            HttpError: The body is malformed (``400``) or too large
                (``413``).
        """
        body, files = await _read_body(request)
        raw_query = request.url.query.split("?", 1)[0]
        query = qs.parse(raw_query)
        params: JsonObject = dict(request.path_params)
        data = merge_without_nulls(merge_without_nulls(body, query), params)
        return cls(data, files)

    def get_field(self, key: str, default: JsonValue = None) -> JsonValue:
        """Read a parameter by its ``/``-separated path.

        ``mods/sortBy`` reads ``data["mods[sortBy]"]`` when present,
        otherwise ``data["mods"]["sortBy"]``.

        Args:
            key: Parameter path.
            default: Value used when the parameter is missing.

        Returns:
            Converted parameter (see ``prepare_value``) or ``default``.
        """
        parts = key.split("/")
        flat_key = parts[0] + "".join(f"[{part}]" for part in parts[1:])
        if self.data.get(flat_key) is not None:
            return prepare_value(self.data[flat_key])

        node: JsonValue = self.data
        for part in parts[:-1]:
            node = _child(node, part)
            if not isinstance(node, (dict, list)):
                return prepare_value(default)
        value = prepare_value(_child(node, parts[-1]))
        return default if value is None else value

    def get_str(self, key: str, default: str) -> str:
        """Read a string parameter without numeric/boolean conversion.

        Args:
            key: Parameter path.
            default: Value used when the parameter is missing or not
                a scalar.

        Returns:
            Parameter as sent by the client.
        """
        parts = key.split("/")
        flat_key = parts[0] + "".join(f"[{part}]" for part in parts[1:])
        node: JsonValue = self.data.get(flat_key)
        if node is None:
            node = self.data
            for part in parts:
                node = _child(node, part)
        if isinstance(node, str):
            return node
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return str(node)
        return default

    @property
    def action(self) -> str:
        """Requested action, ``"default"`` when missing."""
        return self.get_str("action", "default")

    @property
    def source(self) -> str:
        """Requested source name, empty when missing."""
        return self.get_str("source", "")

    @property
    def path(self) -> str:
        """Requested path inside the source, ``"/"`` when missing."""
        return self.get_str("path", "/")


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip()


async def _read_limited(request: Request) -> bytes:
    body = await request.body()
    if len(body) > BODY_LIMIT:
        raise HttpError(413, "request entity too large")
    return body


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """File sent in a multipart request.

    Attributes:
        field: Form field name, e.g. ``files[0]``.
        file: Uploaded file.
    """

    field: str
    file: UploadFile


async def _read_body(
    request: Request,
) -> tuple[JsonObject, list[UploadedFile]]:
    media_type = _media_type(request).lower()

    if media_type == _JSON_TYPE:
        raw = await _read_limited(request)
        if not raw.strip():
            return {}, []
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise HttpError.bad_request(
                f"Invalid JSON body: {error}"
            ) from None
        if not isinstance(data, (dict, list)):
            raise HttpError.bad_request("Invalid JSON body")
        return (data if isinstance(data, dict) else {}), []

    if media_type == _FORM_TYPE:
        raw = await _read_limited(request)
        text = raw.decode("utf-8", errors="replace")
        count = text.count("&") + 1
        if count > qs.QsOptions().parameter_limit:
            raise HttpError(413, "too many parameters")
        options = qs.QsOptions(
            allow_prototypes=True,
            array_limit=max(100, count),
            depth=32,
            strict_depth=True,
        )
        try:
            return qs.parse(text, options), []
        except qs.QsDepthError:
            raise HttpError.bad_request(
                "The input exceeded the depth"
            ) from None

    if media_type == _MULTIPART_TYPE and request.method == "POST":
        try:
            form = await request.form()
        except HTTPException as error:
            # Malformed multipart or a field over the parser's limits.
            raise HttpError(error.status_code, error.detail) from None
        fields: list[tuple[str, str]] = []
        files: list[UploadedFile] = []
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                files.append(UploadedFile(key, value))
            else:
                fields.append((key, value))
        return append_field.build(fields), files

    return {}, []


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Everything an action handler needs to serve one request.

    Attributes:
        request: Incoming request.
        config: Configuration of the connector instance.
        role: Role of the user, resolved by the authentication callback
            or ``defaultRole``.
        params: Request parameters.
        access: Access control of the connector instance.
        sources: Sources of the connector instance.
    """

    request: Request
    config: AppConfig
    role: str
    params: RequestContext = field(repr=False)
    access: AccessControlProtocol = field(repr=False)
    sources: SourcePool = field(repr=False)

    async def get_sources(self) -> list[Source]:
        """Select the sources named by the ``source`` parameter.

        Returns:
            All sources when the parameter is empty, otherwise the one
            with that name.

        Raises:
            HttpError: ``404 Source not found`` for an unknown name.
        """
        return await self.sources.get_sources(
            self.params.source, self.role, self.params.action, self.access
        )


type ActionHandler = Callable[[ActionContext], Awaitable[Response]]
"""Coroutine serving one connector action."""
