"""Keys of object stores (S3, Azure Blob) with an optional prefix.

Folders are emulated like the S3 console does: a zero-byte object whose
key ends with ``/`` marks an explicitly created folder, and any key with
a ``/`` implies its parent folders.
"""


def normalize_key(path: str) -> str:
    """Normalize a storage path to a key fragment.

    Args:
        path: Path with any separators.

    Returns:
        Path with ``/`` only, no empty or ``.`` segments; ``""`` for the
        root.
    """
    segments = path.replace("\\", "/").split("/")
    return "/".join(part for part in segments if part and part != ".")


def build_key(prefix: str, path: str) -> str:
    """Build the object key of a storage path.

    Args:
        prefix: Key prefix acting as the source root.
        path: Storage path.

    Returns:
        Object key.
    """
    normalized_prefix = normalize_key(prefix)
    normalized_path = normalize_key(path)
    if not normalized_prefix:
        return normalized_path
    if not normalized_path:
        return normalized_prefix
    return f"{normalized_prefix}/{normalized_path}"


def strip_key_prefix(prefix: str, key: str) -> str:
    """Turn an object key back into a storage path.

    Args:
        prefix: Key prefix acting as the source root.
        key: Object key.

    Returns:
        Storage path; keys outside the prefix are only normalized.
    """
    normalized_prefix = normalize_key(prefix)
    if not normalized_prefix:
        return normalize_key(key)
    if key == normalized_prefix:
        return ""
    with_slash = f"{normalized_prefix}/"
    if key.startswith(with_slash):
        return normalize_key(key[len(with_slash) :])
    return normalize_key(key)
