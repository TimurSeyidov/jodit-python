"""File wrappers handed to storage SDKs."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO


class FullReader:
    """File wrapper completing short reads.

    Cloud SDKs send what one ``read(n)`` returns as ``n`` bytes of a
    request whose length is already announced.

    Args:
        file: Readable binary file.
    """

    def __init__(self, file: BinaryIO) -> None:
        self.file = file

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.file.read()
        parts: list[bytes] = []
        missing = size
        while missing and (part := self.file.read(missing)):
            parts.append(part)
            missing -= len(part)
        return b"".join(parts)
