"""File sources: root confinement and per-request selection."""

import logging
import os
import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING

from anyio import to_thread

from jcpy.errors import HttpError
from jcpy.storage.file_storage import FileStorage
from jcpy.storage.registry import (
    create_storage_adapter,
    is_local_storage_source,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.acl import AccessControlProtocol
    from jcpy.config.models import AppConfig, SourceConfig

logger = logging.getLogger("jcpy")

VIRTUAL_ROOT = "/"
PATH_NOT_FOUND = "Path does not exist"
SOURCE_NOT_FOUND = "Source not found"

_SLASHES = re.compile(r"/+")


def _resolve(path: str) -> str:
    """Mirror Node's ``path.resolve`` for a single POSIX path."""
    if not path.startswith("/"):
        path = f"{Path.cwd()}/{path}"
    return posixpath.normpath(_SLASHES.sub("/", path))


def _join(root: str, relative: str) -> str:
    """Mirror Node's ``path.join(root, relative)``."""
    joined = "/".join(part for part in (root, relative) if part)
    return posixpath.normpath(joined) if joined else "."


def is_path_within_root(pathname: str, root: str) -> bool:
    """Tell whether a path is the root or lies inside it.

    ``/var/uploads-evil`` is not inside ``/var/uploads``.

    Args:
        pathname: Absolute normalized path.
        root: Absolute normalized root.

    Returns:
        ``True`` when ``pathname`` is ``root`` or below it.
    """
    base = root if root.endswith("/") else f"{root}/"
    return pathname == root or pathname.startswith(base)


def _real_path_within_root(pathname: str, root: str) -> bool:
    try:
        real_root = os.path.realpath(root)
        real_path = os.path.realpath(pathname)
    except OSError, ValueError:
        return False
    return is_path_within_root(real_path, real_root)


async def verify_real_path(pathname: str, root: str) -> None:
    """Require a path to stay inside the root after resolving symlinks.

    Existing components are resolved, missing ones are kept as they
    are, so a symlinked parent cannot smuggle a new entry out of the
    root either.

    Args:
        pathname: Absolute path inside the logical root.
        root: Absolute root directory.

    Raises:
        HttpError: ``404 Path does not exist`` when the real path
            leaves the root or cannot be resolved.
    """
    inside = await to_thread.run_sync(_real_path_within_root, pathname, root)
    if not inside:
        raise HttpError.not_found(PATH_NOT_FOUND)


class Source:
    """One configured file source.

    Args:
        name: Key of the source in ``sources``.
        settings: Source settings.
        config: Effective configuration of the source (global settings
            with the source overrides applied).
        storage: Storage holding the files.
    """

    def __init__(
        self,
        name: str,
        settings: SourceConfig,
        config: AppConfig,
        storage: FileStorage,
    ) -> None:
        self.name = name
        self.settings = settings
        self.config = config
        self.storage = storage

    @property
    def is_virtual_root(self) -> bool:
        """Whether ``root`` is a virtual path of a remote storage."""
        return not is_local_storage_source(self.settings)

    def get_root(self) -> str:
        """Absolute root directory of the source.

        Returns:
            Resolved ``root``; ``/`` for remote storages without one.

        Raises:
            HttpError: ``501`` for a local source without ``root``.
        """
        if self.settings.root:
            return _resolve(self.settings.root)
        if self.is_virtual_root:
            return VIRTUAL_ROOT
        raise HttpError(501, "Set root directory for source")

    async def get_path(self, relative_path: str | None = None) -> str:
        """Resolve a client path inside the source root.

        Backslashes count as separators, ``..`` is resolved; for local
        sources symlinks must not lead outside the root.

        Args:
            relative_path: Path sent by the client; the root when
                omitted.

        Returns:
            Absolute normalized path.

        Raises:
            HttpError: ``404 Path does not exist`` when the path leaves
                the root.
        """
        root = self.get_root()
        joined = _join(root, "./" if relative_path is None else relative_path)
        pathname = _resolve(_SLASHES.sub("/", joined.replace("\\", "/")))
        if not is_path_within_root(pathname, root):
            raise HttpError.not_found(PATH_NOT_FOUND)
        if not self.is_virtual_root:
            await verify_real_path(pathname, root)
        return pathname

    def relative(self, pathname: str) -> str:
        """Path of an absolute location relative to the root.

        Args:
            pathname: Absolute path returned by ``get_path``.

        Returns:
            Storage path, ``""`` for the root itself.
        """
        relative = posixpath.relpath(pathname, self.get_root())
        return "" if relative == "." else relative


class SourcePool:
    """Sources of one connector instance, built on first use.

    Args:
        config: Instance configuration.
        sources: Source settings by name; ``config.sources`` when
            omitted.
    """

    def __init__(
        self,
        config: AppConfig,
        sources: Mapping[str, SourceConfig] | None = None,
    ) -> None:
        self.config = config
        self.settings = dict(config.sources if sources is None else sources)
        self._built: dict[str, Source] | None = None

    def _build(self) -> dict[str, Source]:
        if self._built is None:
            built: dict[str, Source] = {}
            for name, settings in self.settings.items():
                built[name] = Source(
                    name,
                    settings,
                    self.config.with_overrides(settings),
                    FileStorage(create_storage_adapter(settings)),
                )
            self._built = built
        return self._built

    async def get_sources(
        self,
        source: str,
        role: str,
        action: str,
        access: AccessControlProtocol,
    ) -> list[Source]:
        """Select the sources a request works on.

        Args:
            source: Requested source name; all sources when empty.
            role: User role.
            action: Requested action.
            access: Access control; refusals for a source root are
                only logged.

        Returns:
            Matching sources in configuration order.

        Raises:
            HttpError: ``404 Source not found`` for an unknown name,
                ``400`` for an unknown storage adapter.
        """
        sources = list(self._build().values())
        if source:
            sources = [item for item in sources if item.name == source]
            if not sources:
                raise HttpError.not_found(SOURCE_NOT_FOUND)
        for item in sources:
            path = await item.get_path()
            if not await access.is_allow(role, action, path):
                logger.warning(
                    "Access denied for source %s action %s path %s",
                    item.name,
                    action,
                    path,
                )
        return sources
