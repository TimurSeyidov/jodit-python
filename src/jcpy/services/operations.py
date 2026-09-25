"""File and folder changes: remove, create, move, copy, rename."""

import posixpath
from functools import partial
from typing import TYPE_CHECKING, Literal

from jcpy.errors import HttpError
from jcpy.helpers.concurrency import gather_limited
from jcpy.helpers.js import node_basename, node_extname, sanitize_filename
from jcpy.sources import PATH_NOT_FOUND, is_path_within_root, node_join

if TYPE_CHECKING:
    from jcpy.context import ActionContext
    from jcpy.sources import Source


async def _exists(source: Source, storage_path: str) -> bool:
    """File or directory check where any failure means "missing"."""
    for check in (source.storage.file_exists, source.storage.directory_exists):
        try:
            if await check(storage_path):
                return True
        except Exception:  # noqa: S112 - treated as missing
            continue
    return False


async def _is_directory(source: Source, storage_path: str) -> bool:
    try:
        return await source.storage.directory_exists(storage_path)
    except Exception:
        return False


async def _inside_directory(source: Source, directory: str, name: str) -> str:
    """Resolve ``name`` inside ``directory`` without leaving it."""
    target = await source.validate_path(posixpath.join(directory, name))
    if not is_path_within_root(target, directory):
        raise HttpError.not_found(PATH_NOT_FOUND)
    return target


async def remove_file(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> None:
    """Delete a file of the current directory.

    Args:
        context: Action context (role and access control).
        source: Source holding the file.
        name: File name.
        relative_path: Directory relative to the source root.

    Raises:
        HttpError: ``404`` for a missing file or a name leaving the
            directory, ``400 It is not a file!``, ``403`` without
            ``FILE_REMOVE`` for the extension.
    """
    directory = await source.get_path(relative_path)
    target = await _inside_directory(source, directory, name)
    storage_path = source.storage_path(target)
    try:
        stat = await source.storage.stat(storage_path)
        if not stat.is_file:
            raise HttpError.bad_request("It is not a file!")
        await context.access.check_permission(
            context.role,
            "FILE_REMOVE",
            directory,
            source.get_extension(target),
        )
        await source.storage.delete_file(storage_path)
    except HttpError:
        raise
    except Exception:
        raise HttpError.not_found("File or directory not exists") from None


async def remove_folder(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> None:
    """Delete a sub-folder of the current directory with its contents.

    Args:
        context: Action context (role and access control).
        source: Source holding the folder.
        name: Folder name.
        relative_path: Directory relative to the source root.

    Raises:
        HttpError: ``403`` without ``FOLDER_REMOVE``, ``404`` for a
            missing folder or a name leaving (or naming) the current
            directory, ``400 It is not a directory!``.
    """
    directory = await source.get_path(relative_path)
    await context.access.check_permission(
        context.role, "FOLDER_REMOVE", directory
    )
    target = await _inside_directory(source, directory, name)
    if target == directory:
        raise HttpError.not_found(PATH_NOT_FOUND)
    storage_path = source.storage_path(target)
    try:
        stat = await source.storage.stat(storage_path)
        if not stat.is_directory:
            raise HttpError.bad_request("It is not a directory!")
        await source.storage.delete_directory(storage_path)
    except HttpError:
        raise
    except Exception:
        raise HttpError.not_found("Directory not exists") from None


async def make_folder(
    context: ActionContext, source: Source, name: str, relative_path: str
) -> None:
    """Create a sub-folder in the current directory.

    Args:
        context: Action context (role and access control).
        source: Source to change.
        name: Folder name; unsafe characters become ``_``.
        relative_path: Parent directory relative to the source root.

    Raises:
        HttpError: ``400`` for an empty name or an existing folder,
            ``404`` for a missing parent, ``403`` without
            ``FOLDER_CREATE``.
    """
    folder_name = sanitize_filename(name, "_")
    if not folder_name:
        raise HttpError.bad_request("Folder name is required")

    parent = source.storage_path(node_join(source.get_root(), relative_path))
    if not await _is_directory(source, parent):
        raise HttpError.not_found("Directory not found")

    directory = await source.get_path(relative_path)
    folder = posixpath.join(directory, folder_name)
    await context.access.check_permission(
        context.role, "FOLDER_CREATE", folder
    )
    storage_path = source.storage_path(folder)
    try:
        exists = await source.storage.directory_exists(storage_path)
    except Exception:
        exists = False
    if exists:
        raise HttpError.bad_request("Directory already exists")
    await source.storage.create_directory(storage_path)


async def _source_and_destination(
    source: Source, from_path: str, to_path: str
) -> tuple[str, str]:
    """Resolve the ``from`` item and the destination directory."""
    root = source.get_root()
    source_path = await source.validate_path(node_join(root, from_path))
    if to_path:
        destination = source.storage_path(node_join(root, to_path))
        if not await _is_directory(source, destination):
            raise HttpError.not_found("Destination directory not found")
    destination_path = await source.get_path(to_path)
    if not await _exists(source, source.storage_path(source_path)):
        raise HttpError.not_found("Folder or directory not exists")
    return source_path, destination_path


async def move_path(
    context: ActionContext, source: Source, from_path: str, to_path: str
) -> None:
    """Move a file or folder into another directory.

    Args:
        context: Action context (role and access control).
        source: Source to change.
        from_path: Item path relative to the source root.
        to_path: Destination directory relative to the source root.

    Raises:
        HttpError: ``404`` for a missing item or destination, ``403``
            without ``FILE_MOVE``/``FOLDER_MOVE`` for either side,
            ``400`` when the name is taken or the move fails.
    """
    source_path, destination_path = await _source_and_destination(
        source, from_path, to_path
    )
    is_folder = await _is_directory(source, source.storage_path(source_path))
    action = "FOLDER_MOVE" if is_folder else "FILE_MOVE"
    await context.access.check_permission(
        context.role, action, destination_path
    )
    await context.access.check_permission(context.role, action, source_path)

    target = source.storage_path(
        posixpath.join(destination_path, posixpath.basename(source_path))
    )
    if await _exists(source, target):
        kind = "Folder" if is_folder else "File"
        msg = f"{kind} with same name already exists in destination"
        raise HttpError.bad_request(msg)
    try:
        await source.storage.move_file(
            source.storage_path(source_path), target
        )
    except Exception as error:
        raise HttpError.bad_request(f"Unable to move: {error}") from None


async def _unique_target(
    source: Source, destination_path: str, base_name: str
) -> str:
    """``name.txt``, then ``name (1).txt``, ``name (2).txt`` ..."""
    extension = node_extname(base_name)
    stem = node_basename(base_name, extension)
    attempt = 0
    while True:
        name = base_name if attempt == 0 else f"{stem} ({attempt}){extension}"
        target = source.storage_path(posixpath.join(destination_path, name))
        if not await _exists(source, target):
            return target
        attempt += 1


async def copy_path(
    context: ActionContext, source: Source, from_path: str, to_path: str
) -> None:
    """Copy a file or folder into another directory.

    A taken name gets a `` (N)`` suffix, so copying into the same
    directory duplicates the item.

    Args:
        context: Action context (role and access control).
        source: Source to change.
        from_path: Item path relative to the source root.
        to_path: Destination directory relative to the source root.

    Raises:
        HttpError: ``404`` for a missing item or destination, ``400``
            for copying a folder into itself or a failed copy, ``403``
            without ``FILE_COPY``/``FOLDER_COPY`` for either side.
    """
    source_path, destination_path = await _source_and_destination(
        source, from_path, to_path
    )
    source_storage = source.storage_path(source_path)
    is_folder = await _is_directory(source, source_storage)
    if is_folder and (
        destination_path == source_path
        or destination_path.startswith(f"{source_path.rstrip('/')}/")
    ):
        raise HttpError.bad_request("Unable to copy folder into itself")

    action = "FOLDER_COPY" if is_folder else "FILE_COPY"
    await context.access.check_permission(
        context.role, action, destination_path
    )
    await context.access.check_permission(context.role, action, source_path)

    target = await _unique_target(
        source, destination_path, posixpath.basename(source_path)
    )
    try:
        if not is_folder:
            await source.storage.copy_file(source_storage, target)
            return
        await source.storage.create_directory(target)
        entries = [
            entry
            async for entry in source.storage.list(source_storage, deep=True)
        ]
        copies = []
        for entry in entries:
            suffix = entry.path[len(source_storage) :]
            entry_target = posixpath.normpath(f"{target}/{suffix}")
            if entry.is_directory:
                await source.storage.create_directory(entry_target)
            else:
                copies.append(
                    partial(source.storage.copy_file, entry.path, entry_target)
                )
        # Folders exist now; files are copied concurrently.
        await gather_limited(copies)
    except Exception as error:
        raise HttpError.bad_request(f"Unable to copy: {error}") from None


async def rename_path(
    context: ActionContext,
    source: Source,
    name: str,
    new_name: str,
    relative_path: str,
    expect: Literal["file", "folder"],
) -> None:
    """Rename a file or folder inside the current directory.

    Files keep their extension: a new name with another extension gets
    the original (lower-cased) one appended.

    Args:
        context: Action context (role and access control).
        source: Source to change.
        name: Current name.
        new_name: New name.
        relative_path: Directory relative to the source root.
        expect: Kind the client works with; only changes the message
            for a missing item.

    Raises:
        HttpError: ``404`` for a missing item or names leaving the
            directory, ``403`` without ``FILE_RENAME``/``FOLDER_RENAME``
            for either name, ``400`` when the new name is taken or the
            rename fails.
    """
    directory = await source.get_path(relative_path)
    from_path = await _inside_directory(source, directory, name)
    from_storage = source.storage_path(from_path)
    if not await _exists(source, from_storage):
        message = (
            "Folder or directory not exists"
            if expect == "folder"
            else "Path not exists"
        )
        raise HttpError.not_found(message)

    is_file = (await source.storage.stat(from_storage)).is_file
    action = "FILE_RENAME" if is_file else "FOLDER_RENAME"
    await context.access.check_permission(context.role, action, from_path)

    destination = await _inside_directory(source, directory, new_name)
    await context.access.check_permission(context.role, action, destination)
    if is_file:
        extension = node_extname(from_path).lower()
        if node_extname(destination).lower() != extension:
            destination += extension

    destination_storage = source.storage_path(destination)
    if await _exists(source, destination_storage):
        if is_file:
            msg = f"New {posixpath.basename(destination)} already exists"
        else:
            msg = "Folder with new name already exists"
        raise HttpError.bad_request(msg)
    try:
        await source.storage.move_file(from_storage, destination_storage)
    except Exception as error:
        raise HttpError.bad_request(f"Unable to rename: {error}") from None
