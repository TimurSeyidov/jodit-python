"""Features installed through optional extras."""

from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING

from jcpy.errors import HttpError

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def optional_feature(
    extra: str, feature: str, system_hint: str = ""
) -> Iterator[None]:
    """Guard the import of a feature that needs an optional extra.

    Wrap only the import statement: errors raised by the feature itself
    must not be mistaken for a missing installation.

    Args:
        extra: Name of the extra (``pdf``, ``docx``, ``s3``).
        feature: What the extra enables, for the error message.
        system_hint: What to install when a system library is missing.

    Yields:
        Nothing; the import runs in the ``with`` block.

    Raises:
        HttpError: ``501`` when the extra is not installed or one of its
            system libraries (Pango for ``pdf``) cannot be loaded.
    """
    try:
        yield
    except ImportError as error:
        msg = (
            f"{feature} requires the {extra} extra: "
            f"pip install 'jodit-python[{extra}]'"
        )
        raise HttpError(HTTPStatus.NOT_IMPLEMENTED, msg) from error
    except OSError as error:
        # e.g. "cannot load library 'libgobject-2.0-0': dlopen(...) ..."
        first_line = (str(error).splitlines() or [type(error).__name__])[0]
        reason = first_line.split(": ", 1)[0]
        msg = (
            f"{feature} is unavailable, a system library is missing: {reason}"
        )
        if system_hint:
            msg += f" ({system_hint})"
        raise HttpError(HTTPStatus.NOT_IMPLEMENTED, msg) from error
