"""Port of ``qs.parse`` (qs 6.16) used by Express for query strings.

Supported options are the ones Express uses: ``depth``,
``arrayLimit``, ``parameterLimit``, ``allowPrototypes`` and
``strictDepth``; the rest keep their ``qs`` defaults (``&`` delimiter,
UTF-8, no dot notation, no comma arrays, ``duplicates: 'combine'``).
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from jcpy.types import JsonObject, JsonValue


class _Hole:
    """Missing element of a sparse JavaScript array."""


_HOLE = _Hole()

type _Value = str | list[_Value | _Hole] | dict[str, _Value]
type _Container = list[_Value | _Hole] | dict[str, _Value]


class _Overflow(dict[str, _Value]):
    """Object built from an array that exceeded ``arrayLimit``."""

    max_index: int


class QsDepthError(ValueError):
    """Key nesting exceeds ``depth`` while ``strict_depth`` is on."""


@dataclass(frozen=True, slots=True)
class QsOptions:
    """Parsing options, named after their ``qs`` counterparts.

    Attributes:
        depth: Maximum number of bracket segments per key.
        array_limit: Highest index (exclusive) still parsed as a list.
        parameter_limit: Maximum number of ``&``-separated parts.
        allow_prototypes: Keep keys named like ``Object.prototype``
            members (``toString``, ``constructor`` ...).
        strict_depth: Raise ``QsDepthError`` instead of keeping the
            deeper part of a key as a literal segment.
    """

    depth: int = 5
    array_limit: int = 20
    parameter_limit: int = 1000
    allow_prototypes: bool = False
    strict_depth: bool = False


_PROTOTYPE_KEYS = frozenset(
    {
        "__defineGetter__",
        "__defineSetter__",
        "__lookupGetter__",
        "__lookupSetter__",
        "__proto__",
        "constructor",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "toLocaleString",
        "toString",
        "valueOf",
    }
)
_ENCODED_BRACKET = re.compile(r"%5[BD]", re.IGNORECASE)
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_MAX_ARRAY_INDEX = 2**32 - 2


def _decode(text: str) -> str:
    """Mirror ``decodeURIComponent`` with the raw fallback of ``qs``."""
    text = text.replace("+", " ")
    if _BAD_ESCAPE.search(text):
        return text
    try:
        return unquote(text, errors="strict")
    except UnicodeDecodeError:
        return text


def _array_index(key: str) -> int | None:
    """Return the index a key denotes on a JavaScript array."""
    if key.isdigit() and str(int(key)) == key:
        index = int(key)
        if index <= _MAX_ARRAY_INDEX:
            return index
    return None


def _js_keys(obj: dict[str, _Value]) -> list[str]:
    """List keys in ``Object.keys`` order: indices first, ascending."""
    indices = sorted(
        (key for key in obj if _array_index(key) is not None), key=int
    )
    return indices + [key for key in obj if _array_index(key) is None]


def _is_object(value: _Value | _Hole) -> bool:
    return isinstance(value, (list, dict))


def _set_index(
    target: list[_Value | _Hole], index: int, value: _Value
) -> None:
    if index >= len(target):
        target.extend([_HOLE] * (index - len(target) + 1))
    target[index] = value


def _array_to_object(source: list[_Value | _Hole]) -> dict[str, _Value]:
    return {
        str(index): item
        for index, item in enumerate(source)
        if not isinstance(item, _Hole)
    }


def _mark_overflow(obj: dict[str, _Value], max_index: int) -> _Overflow:
    overflow = obj if isinstance(obj, _Overflow) else _Overflow(obj)
    overflow.max_index = max_index
    return overflow


def _concat(*parts: _Value | _Hole) -> list[_Value | _Hole]:
    """Mirror ``[].concat(...parts)``: lists are spread one level."""
    result: list[_Value | _Hole] = []
    for part in parts:
        if isinstance(part, list):
            result.extend(part)
        else:
            result.append(part)
    return result


def _combine(a: _Value, b: _Value, array_limit: int) -> _Value:
    if isinstance(a, _Overflow) and isinstance(b, str):
        # Only flat duplicates reach an overflow object, one string each.
        a.max_index += 1
        a[str(a.max_index)] = b
        return a
    result = _concat(a, b)
    if len(result) > array_limit:
        return _mark_overflow(_array_to_object(result), len(result) - 1)
    return result


def _merge(target: _Value, source: _Value, options: QsOptions) -> _Value:
    """Mirror ``utils.merge`` of ``qs``."""
    if source == "":
        return target

    if isinstance(source, str):
        if isinstance(target, list):
            next_index = len(target)
            if next_index >= options.array_limit:
                return _mark_overflow(
                    _array_to_object([*target, source]), next_index
                )
            target.append(source)
            return target
        if isinstance(target, _Overflow):
            target.max_index += 1
            target[str(target.max_index)] = source
            return target
        # ``strictMerge`` (on by default when parsing) keeps both values.
        return [target, source]

    if isinstance(target, str):
        if isinstance(source, _Overflow):
            shifted = _Overflow({"0": target})
            for key, value in source.items():
                shifted[str(int(key) + 1)] = value
            return _mark_overflow(shifted, source.max_index + 1)
        combined = _concat(target, source)
        if len(combined) > options.array_limit:
            return _mark_overflow(
                _array_to_object(combined), len(combined) - 1
            )
        return combined

    if isinstance(target, list) and isinstance(source, list):
        for index, item in enumerate(source):
            if isinstance(item, _Hole):
                continue
            current = target[index] if index < len(target) else _HOLE
            if isinstance(current, (list, dict)) and _is_object(item):
                target[index] = _merge(current, item, options)
            elif not isinstance(current, _Hole):
                target.append(item)
            else:
                _set_index(target, index, item)
        if len(target) > options.array_limit:
            return _mark_overflow(_array_to_object(target), len(target) - 1)
        return target

    return _merge_objects(target, source, options)


def _merge_objects(
    target: _Container, source: _Container, options: QsOptions
) -> dict[str, _Value]:
    """Merge key by key, turning list operands into objects."""
    merge_target = (
        _array_to_object(target) if isinstance(target, list) else target
    )
    if isinstance(source, list):
        source = _array_to_object(source)
    for key in _js_keys(source):
        value = source[key]
        if key in merge_target:
            merge_target[key] = _merge(merge_target[key], value, options)
        else:
            merge_target[key] = value
        if isinstance(source, _Overflow) and not isinstance(
            merge_target, _Overflow
        ):
            merge_target = _mark_overflow(merge_target, source.max_index)
        if isinstance(merge_target, _Overflow):
            index = _parse_int(key)
            if index is not None and index > merge_target.max_index:
                merge_target.max_index = index
    return merge_target


def _split_key(key: str, options: QsOptions) -> list[str] | None:
    """Mirror ``splitKeyIntoSegments``; ``None`` drops the key."""
    guard = not options.allow_prototypes
    if options.depth <= 0:
        if guard and key in _PROTOTYPE_KEYS:
            return None
        return [key]

    segments: list[str] = []
    first = key.find("[")
    parent = key[:first] if first >= 0 else key
    if parent:
        if guard and parent in _PROTOTYPE_KEYS:
            return None
        segments.append(parent)

    length = len(key)
    open_at = first
    collected = 0
    while open_at >= 0 and collected < options.depth:
        level = 1
        position = open_at + 1
        close = -1
        while position < length and close < 0:
            char = key[position]
            if char == "[":
                level += 1
            elif char == "]":
                level -= 1
                if level == 0:
                    close = position
            position += 1
        if close < 0:
            segments.append(f"[{key[open_at:]}]")
            return segments
        segment = key[open_at : close + 1]
        if guard and segment[1:-1] in _PROTOTYPE_KEYS:
            return None
        segments.append(segment)
        collected += 1
        open_at = key.find("[", close + 1)

    if open_at >= 0:
        if options.strict_depth:
            msg = (
                "Input depth exceeded depth option of "
                f"{options.depth} and strictDepth is true"
            )
            raise QsDepthError(msg)
        segments.append(f"[{key[open_at:]}]")
    return segments


def _parse_int(text: str) -> int | None:
    """Return ``parseInt(text)`` when it round-trips to ``text``."""
    if text.isdigit() and str(int(text)) == text:
        return int(text)
    return None


def _parse_object(
    chain: list[str], value: _Value, options: QsOptions
) -> _Container:
    """Mirror ``parseObject``: build the value for one key chain."""
    leaf = value
    obj: _Container = {}
    for root in reversed(chain):
        if root == "[]":
            # Leaves are overflow objects, strings or lists that already
            # fit within arrayLimit.
            obj = leaf if isinstance(leaf, _Overflow) else _concat(leaf)
        else:
            clean = (
                root[1:-1]
                if root.startswith("[") and root.endswith("]")
                else root
            )
            index = _parse_int(clean)
            if index is not None and root != clean:
                if index < options.array_limit:
                    array: list[_Value | _Hole] = []
                    _set_index(array, index, leaf)
                    obj = array
                else:
                    obj = _mark_overflow({clean: leaf}, index)
            elif clean != "__proto__":
                obj = {clean: leaf}
            else:
                obj = {}
        leaf = obj
    return obj


def _parse_values(text: str, options: QsOptions) -> dict[str, _Value]:
    """Mirror ``parseValues``: flat ``key -> value`` with duplicates."""
    flat: dict[str, _Value] = {}
    text = _ENCODED_BRACKET.sub(
        lambda match: "[" if match.group(0)[-1] in "bB" else "]", text
    )
    for part in text.split("&")[: options.parameter_limit]:
        bracket_equals = part.find("]=")
        position = (
            part.find("=") if bracket_equals == -1 else bracket_equals + 1
        )
        if position == -1:
            key, value = _decode(part), ""
        else:
            key, value = (
                _decode(part[:position]),
                _decode(part[position + 1 :]),
            )
        if key in flat:
            flat[key] = _combine(flat[key], value, options.array_limit)
        else:
            flat[key] = value
    return flat


def _to_json(value: _Value) -> JsonValue:
    if isinstance(value, list):
        return [
            _to_json(item) for item in value if not isinstance(item, _Hole)
        ]
    if isinstance(value, dict):
        return _object_to_json(value)
    return value


def _object_to_json(value: dict[str, _Value]) -> JsonObject:
    return {key: _to_json(value[key]) for key in _js_keys(value)}


def parse(text: str, options: QsOptions | None = None) -> JsonObject:
    """Parse a query string or an urlencoded body like ``qs.parse``.

    Args:
        text: Raw string without the leading ``?``.
        options: Parsing options; ``qs`` defaults when omitted.

    Returns:
        Nested object with string leaves.

    Raises:
        QsDepthError: A key is nested deeper than ``options.depth``
            while ``options.strict_depth`` is on.
    """
    options = options or QsOptions()
    if not text:
        return {}
    result: dict[str, _Value] = {}
    flat = _parse_values(text, options)
    for key in _js_keys(flat):
        chain = _split_key(key, options) if key else None
        if chain is None:
            continue
        result = _merge_objects(
            result, _parse_object(chain, flat[key], options), options
        )
    return _object_to_json(result)
