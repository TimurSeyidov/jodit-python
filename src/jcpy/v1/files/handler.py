"""File listing: ``action=files``."""

from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.responses import success_response
from jcpy.services.listing import ListOptions, list_items
from jcpy.validation import (
    Issue,
    any_of,
    is_boolean,
    is_number,
    is_string,
    object_of,
    one_of,
    string_field,
    union_field,
)

if TYPE_CHECKING:
    from starlette.responses import Response

    from jcpy.context import ActionContext
    from jcpy.types import JsonObject, JsonValue

_MODS = object_of(
    {
        "withFolders": any_of(is_boolean, is_string),
        "sortBy": one_of(
            "name-asc",
            "name-desc",
            "changed-asc",
            "changed-desc",
            "size-asc",
            "size-desc",
        ),
        "limit": any_of(is_number, is_string),
        "offset": any_of(is_number, is_string),
        "onlyImages": any_of(is_boolean, is_string),
        "foldersPosition": one_of("default", "top", "bottom"),
        "filterWord": is_string,
    }
)


def validate(data: JsonObject) -> list[Issue]:
    """Check ``files`` parameters like the original zod schema.

    Args:
        data: Request parameters.

    Returns:
        Issues, empty when valid.
    """
    return [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *union_field(data, "mods", any_of(is_string, _MODS)),
    ]


def _require_valid(data: JsonObject) -> None:
    issues = validate(data)
    if issues:
        messages = ",".join(issue.message for issue in issues)
        raise HttpError.bad_request(f"Validation failed {messages}")


def _text(value: JsonValue, default: str) -> str:
    return value if isinstance(value, str) else default


async def files_handler(context: ActionContext) -> Response:
    """List files of the requested path in the selected sources.

    Modifiers come from ``mods[...]``: ``withFolders``, ``onlyImages``,
    ``offset``, ``limit``, ``sortBy``, ``foldersPosition`` and
    ``filterWord``.

    Args:
        context: Action context.

    Returns:
        ``{"sources": [{name, title, baseurl, path, files}, ...]}``.

    Raises:
        HttpError: ``400`` for invalid parameters, ``404`` for an
            unknown source or path, ``422`` for a non-numeric offset
            or limit.
    """
    params = context.params
    _require_valid(params.data)
    config = context.config
    options = ListOptions(
        with_folders=params.get_field("mods/withFolders", False),
        only_images=params.get_field("mods/onlyImages", False),
        offset=params.get_field("mods/offset", 0),
        limit=params.get_field("mods/limit", config.count_in_chunk),
        sort_by=_text(
            params.get_field("mods/sortBy", config.default_sort_by),
            config.default_sort_by,
        ),
        folders_position=_text(
            params.get_field("mods/foldersPosition", "default"), "default"
        ),
        filter_word=params.get_str("mods/filterWord", ""),
    )
    sources: list[JsonValue] = [
        await list_items(source, params.path, options)
        for source in await context.get_sources()
    ]
    return success_response({"sources": sources})
