"""File storage: adapter interface, local adapter and registry."""

from jcpy.storage.base import (
    FileWasNotFoundError,
    StatEntry,
    StorageAdapter,
    StorageError,
)
from jcpy.storage.file_storage import (
    CorruptedPathError,
    FileStorage,
    PathTraversalError,
    normalize_storage_path,
)
from jcpy.storage.local import LocalStorageAdapter
from jcpy.storage.registry import (
    StorageAdapterFactory,
    create_storage_adapter,
    get_registered_storage_adapters,
    is_local_storage_source,
    register_storage_adapter,
)

__all__ = [
    "CorruptedPathError",
    "FileStorage",
    "FileWasNotFoundError",
    "LocalStorageAdapter",
    "PathTraversalError",
    "StatEntry",
    "StorageAdapter",
    "StorageAdapterFactory",
    "StorageError",
    "create_storage_adapter",
    "get_registered_storage_adapters",
    "is_local_storage_source",
    "normalize_storage_path",
    "register_storage_adapter",
]
