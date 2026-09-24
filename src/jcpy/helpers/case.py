"""Port of ``constantCase`` and ``camelCase`` from ``change-case`` 5."""

import unicodedata

_LETTER_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo"})
_SEPARATOR = "\0"


def _is_upper(char: str) -> bool:
    return unicodedata.category(char) == "Lu"


def _is_lower(char: str) -> bool:
    return unicodedata.category(char) == "Ll"


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_word_char(char: str) -> bool:
    return _is_digit(char) or unicodedata.category(char) in _LETTER_CATEGORIES


def _split_lower_upper(text: str) -> str:
    """Mirror ``replace(/([\\p{Ll}\\d])(\\p{Lu})/gu, "$1\\0$2")``."""
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if (
            following
            and (_is_lower(char) or _is_digit(char))
            and _is_upper(following)
        ):
            result += [char, _SEPARATOR, following]
            index += 2
        else:
            result.append(char)
            index += 1
    return "".join(result)


def _split_upper_upper(text: str) -> str:
    """Mirror ``replace(/(\\p{Lu})([\\p{Lu}][\\p{Ll}])/gu, "$1\\0$2")``."""
    result: list[str] = []
    index = 0
    while index < len(text):
        chunk = text[index : index + 3]
        if (
            len(chunk) == 3
            and _is_upper(chunk[0])
            and _is_upper(chunk[1])
            and _is_lower(chunk[2])
        ):
            result += [chunk[0], _SEPARATOR, chunk[1:]]
            index += 3
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def split_words(value: str) -> list[str]:
    """Split any cased string into words like ``change-case``'s ``split``.

    Args:
        value: Input such as ``fileUpload``, ``file-upload`` or
            ``FILE_UPLOAD``.

    Returns:
        Words in their original case, e.g. ``["file", "Upload"]``.
    """
    text = _split_upper_upper(_split_lower_upper(value.strip()))
    parts: list[str] = []
    word: list[str] = []
    for char in text:
        if _is_word_char(char):
            word.append(char)
        elif word:
            parts.append("".join(word))
            word = []
    if word:
        parts.append("".join(word))
    return parts


def constant_case(value: str) -> str:
    """Convert to ``CONSTANT_CASE``.

    Args:
        value: Input in any case.

    Returns:
        Upper-cased words joined by ``_``, e.g. ``FILE_UPLOAD``.
    """
    return "_".join(word.upper() for word in split_words(value))


def camel_case(value: str) -> str:
    """Convert to ``camelCase``.

    Args:
        value: Input in any case.

    Returns:
        First word lower-cased, the rest capitalized; a word starting
        with a digit is prefixed by ``_``, e.g. ``allowFileUpload``.
    """
    result: list[str] = []
    for index, word in enumerate(split_words(value)):
        if index == 0:
            result.append(word.lower())
            continue
        first = word[0]
        initial = f"_{first}" if _is_digit(first) else first.upper()
        result.append(initial + word[1:].lower())
    return "".join(result)
