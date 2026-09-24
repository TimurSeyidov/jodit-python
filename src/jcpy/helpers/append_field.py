"""Build nested data from multipart form field names.

``mods[sortBy]`` becomes ``{"mods": {"sortBy": ...}}``, ``files[0]``
builds a list, ``tags[]`` appends and repeated scalar keys collect
into a list.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jcpy.types import JsonObject, JsonValue


class _Hole:
    """Missing element of a sparse JavaScript array."""


_HOLE = _Hole()

type _Value = str | list[_Value | _Hole] | dict[str, _Value]
type _Container = list[_Value | _Hole] | dict[str, _Value]

_FIRST_KEY = re.compile(r"^[^\[]*")
_DIGIT_PATH = re.compile(r"^\[(\d+)\]")
_NORMAL_PATH = re.compile(r"^\[([^\]]+)\]")


@dataclass(slots=True)
class _Step:
    kind: str
    key: str | int
    last: bool = False
    append: bool = False
    next_kind: str = field(default="object")


def _parse_path(key: str) -> list[_Step]:
    """Mirror ``parse-path``: split a field name into steps."""
    failure = [_Step("object", key, last=True)]
    first = _FIRST_KEY.match(key)
    first_key = first.group(0) if first else ""
    if not first_key:
        return failure

    position = len(first_key)
    tail = _Step("object", first_key)
    steps = [tail]
    while position < len(key):
        if key[position : position + 2] == "[]":
            position += 2
            tail.append = True
            if position != len(key):
                return failure
            continue
        rest = key[position:]
        if digit := _DIGIT_PATH.match(rest):
            position += len(digit.group(0))
            tail.next_kind = "array"
            tail = _Step("array", int(digit.group(1)))
            steps.append(tail)
            continue
        if normal := _NORMAL_PATH.match(rest):
            position += len(normal.group(0))
            tail.next_kind = "object"
            tail = _Step("object", normal.group(1))
            steps.append(tail)
            continue
        return failure

    tail.last = True
    return steps


def _get(context: _Container, key: str | int) -> _Value | _Hole:
    if isinstance(context, list):
        if isinstance(key, int) and key < len(context):
            return context[key]
        return _HOLE
    return context.get(str(key), _HOLE)


def _put(context: _Container, key: str | int, value: _Value) -> None:
    if isinstance(context, dict):
        context[str(key)] = value
        return
    # Lists are only created for numeric steps, so ``key`` is an index.
    index = int(key)
    if index >= len(context):
        context.extend([_HOLE] * (index - len(context) + 1))
    context[index] = value


def _set_last(
    context: _Container, step: _Step, current: _Value | _Hole, value: str
) -> None:
    if isinstance(current, _Hole):
        _put(context, step.key, [value] if step.append else value)
    elif isinstance(current, list):
        current.append(value)
    elif isinstance(current, dict):
        _set_last(
            current, _Step("object", "", last=True), _get(current, ""), value
        )
    else:
        _put(context, step.key, [current, value])


def _set(
    context: _Container, step: _Step, current: _Value | _Hole, value: str
) -> _Container:
    if step.last:
        _set_last(context, step, current, value)
        return context

    container: _Container
    if isinstance(current, _Hole):
        container = [] if step.next_kind == "array" else {}
        _put(context, step.key, container)
        return container
    if isinstance(current, dict):
        return current
    if isinstance(current, list):
        if step.next_kind == "array":
            return current
        container = {
            str(index): item
            for index, item in enumerate(current)
            if not isinstance(item, _Hole)
        }
        _put(context, step.key, container)
        return container
    container = {"": current}
    _put(context, step.key, container)
    return container


def _to_json(value: _Value | _Hole) -> JsonValue:
    if isinstance(value, _Hole):
        return None
    if isinstance(value, list):
        return [_to_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json(item) for key, item in value.items()}
    return value


def build(fields: list[tuple[str, str]]) -> JsonObject:
    """Build a nested object from multipart fields.

    Args:
        fields: Field names and values in their original order.

    Returns:
        Nested parameters; holes of sparse lists become ``None``
        (``null`` in JSON).
    """
    store: dict[str, _Value] = {}
    for key, value in fields:
        context: _Container = store
        for step in _parse_path(key):
            context = _set(context, step, _get(context, step.key), value)
    return {key: _to_json(item) for key, item in store.items()}
