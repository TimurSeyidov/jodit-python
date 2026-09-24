"""Guard for features installed through extras."""

import pytest

from jcpy.errors import HttpError
from jcpy.optional import optional_feature


def test_missing_package_names_the_extra() -> None:
    with pytest.raises(HttpError) as caught, optional_feature("pdf", "PDF"):
        raise ImportError

    assert caught.value.status_code == 501
    assert caught.value.messages == [
        "PDF requires the pdf extra: pip install 'jodit-python[pdf]'"
    ]


def test_missing_system_library_is_named_briefly() -> None:
    error = OSError(
        "cannot load library 'libgobject-2.0-0': dlopen(...): tried: ...\n"
        "more details"
    )
    with (
        pytest.raises(HttpError) as caught,
        optional_feature("pdf", "PDF", "install Pango"),
    ):
        raise error

    assert caught.value.status_code == 501
    assert caught.value.messages == [
        "PDF is unavailable, a system library is missing: "
        "cannot load library 'libgobject-2.0-0' (install Pango)"
    ]


def test_system_error_without_text_or_hint() -> None:
    with pytest.raises(HttpError) as caught, optional_feature("x", "X"):
        raise OSError

    assert caught.value.messages == [
        "X is unavailable, a system library is missing: OSError"
    ]


def test_other_errors_pass_through() -> None:
    with pytest.raises(ValueError, match="boom"), optional_feature("x", "X"):
        raise ValueError("boom")
