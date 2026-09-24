"""Named storage adapter factories."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from jcpy.errors import HttpError
from jcpy.storage.local import LocalStorageAdapter
from jcpy.storage.s3 import S3StorageAdapter

if TYPE_CHECKING:
    from jcpy.config.models import SourceConfig
    from jcpy.storage.base import StorageAdapter

type StorageAdapterFactory = Callable[[SourceConfig], StorageAdapter]
"""Build the adapter of a source that names it in ``storageAdapter``."""

LOCAL_ADAPTER = "local"

_registry: dict[str, StorageAdapterFactory] = {}


def register_storage_adapter(
    name: str, factory: StorageAdapterFactory
) -> None:
    """Register or replace a named storage adapter factory.

    Args:
        name: Value of ``storageAdapter`` selecting the adapter.
        factory: Builds the adapter for a source.
    """
    _registry[name] = factory


def get_registered_storage_adapters() -> list[str]:
    """List registered adapter names.

    Returns:
        Names in registration order; ``local`` and ``s3`` are built in.
    """
    return list(_registry)


def is_local_storage_source(source: SourceConfig) -> bool:
    """Tell whether a source lives on the local filesystem.

    Args:
        source: Source settings.

    Returns:
        ``True`` for the default ``local`` adapter; other adapters use
        ``root`` as a virtual path only.
    """
    return source.storage_adapter in {None, LOCAL_ADAPTER}


def create_storage_adapter(source: SourceConfig) -> StorageAdapter:
    """Build the storage adapter named by a source.

    Args:
        source: Source settings.

    Returns:
        Adapter instance.

    Raises:
        HttpError: ``400`` for an unregistered adapter name.
    """
    name = source.storage_adapter or LOCAL_ADAPTER
    factory = _registry.get(name)
    if factory is None:
        registered = ", ".join(get_registered_storage_adapters())
        msg = (
            f'Unknown storage adapter "{name}" for source "{source.name}". '
            f"Registered adapters: {registered}"
        )
        raise HttpError.bad_request(msg)
    return factory(source)


def _local_factory(source: SourceConfig) -> StorageAdapter:
    if not source.root:
        msg = (
            f'Source "{source.name}" uses the local filesystem and needs '
            'a "root" directory'
        )
        raise HttpError.bad_request(msg)
    return LocalStorageAdapter(source.root)


def _s3_factory(source: SourceConfig) -> StorageAdapter:
    if source.s3 is None:
        msg = (
            f'Source "{source.name}" uses the s3 adapter and needs an '
            '"s3" options block'
        )
        raise HttpError.bad_request(msg)
    return S3StorageAdapter(source.s3)


register_storage_adapter(LOCAL_ADAPTER, _local_factory)
register_storage_adapter("s3", _s3_factory)
