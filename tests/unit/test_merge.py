"""Deep merging helpers."""

from typing import TYPE_CHECKING

from jcpy.helpers.merge import deep_merge, merge_without_nulls, override

if TYPE_CHECKING:
    from jcpy.types import JsonObject


def test_deep_merge_matches_deepmerge_package() -> None:
    # Reference: deepmerge 4 output for the same operands.
    target: JsonObject = {"a": [1], "b": {"c": 1, "d": [1]}, "e": 1}
    source: JsonObject = {"a": [2], "b": {"d": [2], "f": 2}, "e": {"x": 1}}

    assert deep_merge(target, source) == {
        "a": [1, 2],
        "b": {"c": 1, "d": [1, 2], "f": 2},
        "e": {"x": 1},
    }


def test_deep_merge_source_wins_on_type_mismatch() -> None:
    assert deep_merge({"a": {"x": 1}}, {"a": [1]}) == {"a": [1]}
    assert deep_merge({"a": [1]}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_deep_merge_does_not_modify_inputs() -> None:
    target: JsonObject = {"a": {"b": 1}}

    deep_merge(target, {"a": {"c": 2}})

    assert target == {"a": {"b": 1}}


def test_merge_without_nulls_skips_top_level_none() -> None:
    merged = merge_without_nulls(
        {"a": 1, "b": {"c": 1}}, {"a": None, "b": {"c": None}}
    )

    assert merged == {"a": 1, "b": {"c": None}}


def test_override_merges_objects_and_replaces_lists() -> None:
    base: JsonObject = {
        "pdf": {"paper": {"format": "A4", "orientation": "p"}},
        "x": [1],
    }

    result = override(base, {"pdf": {"paper": {"format": "A3"}}, "x": [2]})

    assert result == {
        "pdf": {"paper": {"format": "A3", "orientation": "p"}},
        "x": [2],
    }


def test_override_ignores_none_and_replaces_listed_keys() -> None:
    base: JsonObject = {"sources": {"default": {"a": 1}}, "debug": True}

    result = override(
        base, {"sources": {"mine": {"b": 2}}, "debug": None}, {"sources"}
    )

    assert result == {"sources": {"mine": {"b": 2}}, "debug": True}
