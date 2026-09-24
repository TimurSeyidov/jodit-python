"""Deep merging of JSON-like data."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    from jcpy.types import JsonObject, JsonValue


def deep_merge(target: JsonValue, source: JsonValue) -> JsonValue:
    """Merge ``source`` into ``target`` like the Node.js ``deepmerge``.

    Objects are merged key by key, lists are concatenated, any other
    combination is resolved in favour of ``source``. Inputs are not
    modified.

    Args:
        target: Base value.
        source: Value merged on top.

    Returns:
        Merged value.
    """
    if isinstance(target, dict) and isinstance(source, dict):
        merged = dict(target)
        for key, value in source.items():
            merged[key] = (
                deep_merge(merged[key], value) if key in merged else value
            )
        return merged
    if isinstance(target, list) and isinstance(source, list):
        return [*target, *source]
    return source


def merge_without_nulls(target: JsonObject, source: JsonObject) -> JsonObject:
    """Deep-merge ``source`` into ``target``, skipping its ``None`` keys.

    Args:
        target: Base object.
        source: Object merged on top; top-level ``None`` values are
            ignored.

    Returns:
        Merged object.
    """
    filtered: JsonObject = {
        key: value for key, value in source.items() if value is not None
    }
    merged = deep_merge(target, filtered)
    assert isinstance(merged, dict)  # noqa: S101 - dict + dict is a dict
    return merged


def override(
    base: JsonObject,
    overrides: JsonObject,
    replace: Collection[str] = (),
) -> JsonObject:
    """Apply configuration overrides on top of defaults.

    Nested objects are merged recursively, every other value (lists
    included) replaces the default, ``None`` never replaces anything.

    Args:
        base: Defaults.
        overrides: User values.
        replace: Top-level keys whose objects replace the default
            instead of being merged.

    Returns:
        New object with the overrides applied.
    """
    result = dict(base)
    for key, value in overrides.items():
        if value is None:
            continue
        current = result.get(key)
        if (
            key not in replace
            and isinstance(current, dict)
            and isinstance(value, dict)
        ):
            result[key] = override(current, value)
        else:
            result[key] = value
    return result
