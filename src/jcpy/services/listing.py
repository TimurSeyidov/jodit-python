"""Directory listings: ``files`` and ``folders``."""

import math
import posixpath
from dataclasses import dataclass
from functools import cmp_to_key
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.helpers.js import (
    format_bytes,
    format_datetime,
    js_slice,
    js_string_key,
    js_truthy,
)
from jcpy.services.thumbs import ThumbCounter, make_thumb
from jcpy.sources import PATH_NOT_FOUND

if TYPE_CHECKING:
    from collections.abc import Callable

    from jcpy.sources import Source
    from jcpy.storage.base import StatEntry
    from jcpy.types import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class ListOptions:
    """Modifiers of the ``files`` action (``mods[...]``).

    Attributes:
        with_folders: Include folders (JavaScript truthiness).
        only_images: Keep only images (JavaScript truthiness).
        offset: First item to return.
        limit: Number of items to return.
        sort_by: ``name-asc``, ``name-desc``, ``changed-asc``,
            ``changed-desc``, ``size-asc`` or ``size-desc``; anything
            else sorts by name descending.
        folders_position: ``default``, ``top`` or ``bottom``.
        filter_word: Case-insensitive substring of the names to keep.
    """

    with_folders: JsonValue = False
    only_images: JsonValue = False
    offset: JsonValue = 0
    limit: JsonValue = 1_000_000
    sort_by: str = "changed-desc"
    folders_position: str = "default"
    filter_word: str = ""


@dataclass(frozen=True, slots=True)
class _Item:
    entry: StatEntry
    name: str
    size: int
    mtime: float
    is_image: bool


def _display_path(full_path: str, root: str) -> str:
    relative = full_path.removeprefix(root)
    if len(relative) > 1 and relative.startswith("/"):
        relative = relative[1:]
    return relative


async def _require_directory(source: Source, relative: str) -> None:
    if relative and not await source.storage.directory_exists(relative):
        raise HttpError.not_found(PATH_NOT_FOUND)


async def _to_item(
    source: Source, entry: StatEntry, options: ListOptions
) -> _Item | None:
    try:
        stat = await source.storage.stat(entry.path)
    except Exception:
        return None
    name = posixpath.basename(entry.path)
    mtime = stat.last_modified_ms or 0
    if stat.is_directory:
        if js_truthy(options.with_folders):
            return _Item(entry, name, 0, mtime, is_image=False)
        return None
    is_image = source.is_image(entry.path)
    if source.is_good_file(entry.path) and (
        not js_truthy(options.only_images) or is_image
    ):
        return _Item(entry, name, stat.size or 0, mtime, is_image)
    return None


def _compare_names(a: _Item, b: _Item, reverse: int) -> int:
    key_a, key_b = js_string_key(a.name), js_string_key(b.name)
    if key_a < key_b:
        return -reverse
    if key_a > key_b:
        return reverse
    return 0


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _comparator(sort_by: str) -> Callable[[_Item, _Item], int]:
    ascending = sort_by.endswith("-asc")

    def by_changed(a: _Item, b: _Item) -> int:
        if a.mtime == b.mtime:
            sign = 1 if ascending else -1
            greater = js_string_key(a.name) > js_string_key(b.name)
            return sign if greater else -sign
        return _sign(a.mtime - b.mtime if ascending else b.mtime - a.mtime)

    def by_size(a: _Item, b: _Item) -> int:
        return _sign(a.size - b.size if ascending else b.size - a.size)

    def by_name(a: _Item, b: _Item) -> int:
        return _compare_names(a, b, 1 if sort_by == "name-asc" else -1)

    if sort_by in {"changed-asc", "changed-desc"}:
        return by_changed
    if sort_by in {"size-asc", "size-desc"}:
        return by_size
    return by_name


def sort_items(
    items: list[_Item], sort_by: str, folders_position: str
) -> None:
    """Sort listing items in place exactly like jodit-nodejs.

    The comparators, including their inconsistencies, are the original
    ones; Python's ``list.sort`` is the algorithm V8 ports, so equal
    inputs give equal orders.

    Args:
        items: Items to sort.
        sort_by: Sort mode.
        folders_position: ``top``/``bottom`` moves folders, anything
            else keeps the order.
    """
    items.sort(key=cmp_to_key(_comparator(sort_by)))
    if folders_position == "default":
        return
    top = folders_position == "top"

    def by_kind(a: _Item, b: _Item) -> int:
        a_dir, b_dir = a.entry.is_directory, b.entry.is_directory
        if a_dir and not b_dir:
            return -1 if top else 1
        if not a_dir and b_dir:
            return 1 if top else -1
        # The original compares two objects here, which is always false.
        return -1 if a_dir and b_dir else 0

    items.sort(key=cmp_to_key(by_kind))


async def list_items(
    source: Source, relative_path: str, options: ListOptions
) -> JsonObject:
    """List files (and optionally folders) of a directory.

    Args:
        source: Source to list.
        relative_path: Directory relative to the source root.
        options: Listing modifiers.

    Returns:
        ``{name, title, baseurl, path, files}`` for the source.

    Raises:
        HttpError: ``404 Path does not exist`` for a missing or foreign
            directory, ``422`` for a non-numeric offset or limit.
    """
    full_path = await source.get_path(relative_path)
    root = source.get_root()
    display_path = _display_path(full_path, root)

    offset = _paging(options.offset, "Offset is not numeric")
    limit = _paging(options.limit, "limit is not numeric")

    storage_path = "" if display_path == "/" else display_path
    await _require_directory(source, storage_path)

    items: list[_Item] = []
    word = options.filter_word.lower()
    async for entry in source.storage.list(storage_path):
        if source.is_excluded(entry.path):
            continue
        item = await _to_item(source, entry, options)
        if item is None or (word and word not in item.name.lower()):
            continue
        items.append(item)

    sort_items(items, options.sort_by, options.folders_position)
    page = js_slice(items, offset, offset + limit)

    counter = ThumbCounter()
    config = source.config
    files: list[JsonValue] = []
    for item in page:
        thumb: str | None = None
        if (
            config.create_thumb
            and counter.count <= config.safe_thumbs_count_in_one_time
        ):
            thumb = posixpath.relpath(
                await make_thumb(source, item.entry, counter), full_path
            )
        data: JsonObject = {"file": item.name, "name": item.name}
        if item.entry.is_directory:
            data["type"] = "folder"
        else:
            data["type"] = "image" if item.is_image else "file"
            data["isImage"] = item.is_image
            data["size"] = format_bytes(item.size)
            data["changed"] = format_datetime(
                item.mtime, config.datetime_format
            )
        if thumb is not None:
            data["thumb"] = thumb
        files.append(data)

    return {
        "name": source.name,
        "title": source.settings.title,
        "baseurl": source.settings.baseurl,
        "path": display_path or "/",
        "files": files,
    }


def _paging(value: JsonValue, message: str) -> float:
    """Require a number, as ``isNaN`` does for validated parameters.

    Numeric strings are already converted by ``prepare_value`` and
    other types are rejected by validation, so anything but a real
    number here is ``NaN`` in JavaScript.
    """
    if isinstance(value, (int, float)) and not math.isnan(value):
        return value
    raise HttpError(422, message)


async def list_folders(
    source: Source, relative_path: str, *, dots: JsonValue
) -> JsonObject:
    """List the sub-folders of a directory.

    Args:
        source: Source to list.
        relative_path: Directory relative to the source root.
        dots: Unless ``False``, start with ``.`` at the root or ``..``
            elsewhere.

    Returns:
        ``{name, title, baseurl, path, folders}`` for the source.

    Raises:
        HttpError: ``404 Path does not exist`` for a missing, foreign or
            unreadable directory.
    """
    full_path = await source.get_path(relative_path)
    root = source.get_root()
    display_path = _display_path(full_path, root)
    folders: list[JsonValue] = []
    if dots is not False:
        folders.append("." if full_path == root else "..")

    storage_path = "" if display_path == "/" else display_path
    await _require_directory(source, storage_path)
    try:
        async for entry in source.storage.list(storage_path):
            if entry.is_directory and not source.is_excluded(entry.path):
                folders.append(posixpath.basename(entry.path))
    except Exception:
        raise HttpError.not_found(PATH_NOT_FOUND) from None

    return {
        "name": source.name,
        "title": source.settings.title,
        "baseurl": source.settings.baseurl,
        "path": display_path or "/",
        "folders": folders,
    }
