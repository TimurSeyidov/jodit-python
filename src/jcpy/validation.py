"""Request parameter checks producing ``path: message`` issues."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.helpers.js import js_parse_int

if TYPE_CHECKING:
    from jcpy.types import JsonObject, JsonValue

type Check = Callable[[JsonValue], bool]
"""Accept or reject a present (non-missing) value."""

MISSING: object = object()


@dataclass(frozen=True, slots=True)
class Issue:
    """One validation problem.

    Attributes:
        path: Dotted parameter path.
        message: Human-readable problem.
    """

    path: str
    message: str

    def describe(self) -> str:
        """Render as ``path: message``.

        Returns:
            Issue text used in error responses.
        """
        return f"{self.path}: {self.message}"


def js_type(value: object) -> str:
    """Name a value's type for messages (``received undefined``...).

    Args:
        value: JSON-like value or ``MISSING``.

    Returns:
        ``string``, ``number``, ``boolean``, ``array``, ``object``,
        ``null`` or ``undefined``.
    """
    if value is MISSING:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def is_string(value: JsonValue) -> bool:
    """Accept strings."""
    return isinstance(value, str)


def is_number(value: JsonValue) -> bool:
    """Accept JSON numbers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_boolean(value: JsonValue) -> bool:
    """Accept booleans."""
    return isinstance(value, bool)


def one_of(*allowed: str) -> Check:
    """Accept one of the given strings.

    Args:
        allowed: Accepted values.

    Returns:
        Check.
    """
    return lambda value: isinstance(value, str) and value in allowed


def any_of(*checks: Check) -> Check:
    """Accept a value any check accepts.

    Args:
        checks: Alternatives.

    Returns:
        Check.
    """
    return lambda value: any(check(value) for check in checks)


def object_of(fields: dict[str, Check]) -> Check:
    """Accept an object whose listed fields pass when present.

    Args:
        fields: Optional fields and their checks.

    Returns:
        Check.
    """

    def check(value: JsonValue) -> bool:
        if not isinstance(value, dict):
            return False
        return all(
            name not in value or field(value[name])
            for name, field in fields.items()
        )

    return check


def string_field(
    data: JsonObject, name: str, *, required: bool
) -> list[Issue]:
    """Validate a ``z.string()`` field.

    Args:
        data: Request parameters.
        name: Field name.
        required: Whether the field must be present.

    Returns:
        Issues, empty when valid.
    """
    value: object = data.get(name, MISSING)
    if value is MISSING and not required:
        return []
    if isinstance(value, str):
        return []
    return [
        Issue(
            name, f"Invalid input: expected string, received {js_type(value)}"
        )
    ]


def union_field(data: JsonObject, name: str, check: Check) -> list[Issue]:
    """Validate an optional ``z.union(...)`` field.

    Args:
        data: Request parameters.
        name: Field name.
        check: Accepted alternatives.

    Returns:
        Issues, empty when valid.
    """
    if name not in data or check(data[name]):
        return []
    return [Issue(name, "Invalid input")]


def require_valid(issues: Sequence[Issue]) -> None:
    """Fail with ``400 Validation failed`` listing ``path: message``.

    Args:
        issues: Collected issues.

    Raises:
        HttpError: At least one issue was collected.
    """
    if issues:
        raise HttpError.bad_request(
            "Validation failed", [issue.describe() for issue in issues]
        )


def require_valid_plain(issues: Sequence[Issue]) -> None:
    """Fail with ``400 Validation failed`` listing bare messages.

    Args:
        issues: Collected issues.

    Raises:
        HttpError: At least one issue was collected.
    """
    if issues:
        raise HttpError.bad_request(
            "Validation failed", [issue.message for issue in issues]
        )


_MAX_SAFE_INTEGER = 2**53 - 1


def _box_number(path: str, value: object, *, positive: bool) -> list[Issue]:
    """``z.number().int()`` followed by ``.positive()`` or ``.min(0)``."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and math.isnan(value))
    ):
        received = js_type(value)
        return [
            Issue(path, f"Invalid input: expected number, received {received}")
        ]
    if isinstance(value, float) and not value.is_integer():
        return [Issue(path, "Invalid input: expected int, received number")]
    issues: list[Issue] = []
    if value > _MAX_SAFE_INTEGER:
        issues.append(
            Issue(path, f"Too big: expected int to be <{_MAX_SAFE_INTEGER}")
        )
    elif value < -_MAX_SAFE_INTEGER:
        issues.append(
            Issue(path, f"Too small: expected int to be >-{_MAX_SAFE_INTEGER}")
        )
    if positive and not value > 0:
        issues.append(Issue(path, "Too small: expected number to be >0"))
    elif not positive and not value >= 0:
        issues.append(Issue(path, "Too small: expected number to be >=0"))
    return issues


def _from_text(value: object) -> object:
    return js_parse_int(value) if isinstance(value, str) else value


def box_field(
    data: JsonObject, keys: tuple[str, ...]
) -> tuple[list[Issue], dict[str, int]]:
    """Validate ``box`` like the image schemas' transform and pipe.

    ``box`` is read from ``box[...]`` (object form) or flat
    ``"box[x]"`` keys; when every key is present, strings go through
    ``parseInt``. Offsets (``x``, ``y``) must be integers ``>= 0``,
    sizes (``w``, ``h``) integers ``> 0``.

    Args:
        data: Request parameters.
        keys: Box keys in schema order, e.g. ``("w", "h")``.

    Returns:
        Issues and, when there are none, the integer box.
    """
    raw = data.get("box", MISSING)
    values: dict[str, object]
    if isinstance(raw, dict) and all(key in raw for key in keys):
        values = {key: _from_text(raw[key]) for key in keys}
    elif all(data.get(f"box[{key}]") is not None for key in keys):
        values = {key: _from_text(data[f"box[{key}]"]) for key in keys}
    elif isinstance(raw, dict):
        values = {key: raw.get(key, MISSING) for key in keys}
    else:
        received = js_type(raw)
        return [
            Issue(
                "box", f"Invalid input: expected object, received {received}"
            )
        ], {}
    issues = [
        issue
        for key in keys
        for issue in _box_number(
            f"box.{key}", values[key], positive=key in {"w", "h"}
        )
    ]
    if issues:
        return issues, {}
    return [], {
        key: int(value)
        for key, value in values.items()
        if isinstance(value, (int, float))
    }
