"""Parameter checks shared by the image actions."""

from typing import TYPE_CHECKING

from jcpy.validation import box_field, string_field

if TYPE_CHECKING:
    from jcpy.types import JsonObject
    from jcpy.validation import Issue


def validate_edit(
    data: JsonObject, box_keys: tuple[str, ...]
) -> tuple[list[Issue], dict[str, int]]:
    """Check resize/crop parameters.

    Args:
        data: Request parameters.
        box_keys: Keys ``box`` must provide.

    Returns:
        Issues and, when there are none, the integer box.
    """
    issues = [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *string_field(data, "name", required=True),
        *string_field(data, "newname", required=False),
    ]
    if issues:
        return issues, {}
    return box_field(data, box_keys)


def validate_named(data: JsonObject, *, name_required: bool) -> list[Issue]:
    """Check save/load parameters.

    Args:
        data: Request parameters.
        name_required: Whether ``name`` is mandatory.

    Returns:
        Issues, empty when valid.
    """
    issues = [
        *string_field(data, "source", required=False),
        *string_field(data, "path", required=False),
        *string_field(data, "name", required=name_required),
    ]
    if not name_required:
        issues += string_field(data, "newname", required=False)
    return issues
