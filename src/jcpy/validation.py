"""Request parameter checks producing zod 4 style issues."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jcpy.errors import HttpError

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
        message: zod-compatible message.
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
    """Name a value's type as zod reports it.

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
    """Accept one of the given strings (zod ``enum``/``literal``).

    Args:
        allowed: Accepted values.

    Returns:
        Check.
    """
    return lambda value: isinstance(value, str) and value in allowed


def any_of(*checks: Check) -> Check:
    """Accept a value any check accepts (zod ``union``).

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
