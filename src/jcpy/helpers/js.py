"""JavaScript semantics the connector output depends on.

Ports of ``bytes.format`` (bytes 3.1.2), ``dayjs().format`` (dayjs
1.11.18, English locale), ``slugify`` (slugify 1.6.6, default options)
and a few language rules (truthiness, string ordering, ``slice``).
"""

import json
import math
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from importlib import resources

_BYTE_UNITS = (
    ("PB", 1024**5),
    ("TB", 1024**4),
    ("GB", 1024**3),
    ("MB", 1024**2),
    ("KB", 1024),
)
_TRAILING_ZEROS = re.compile(r"(?:\.0*|(\.[^0]+)0+)$")

_DAYJS_TOKENS = re.compile(
    r"\[([^\]]+)]|Y{1,4}|M{1,4}|D{1,2}|d{1,4}|H{1,2}|h{1,2}|a|A|m{1,2}"
    r"|s{1,2}|Z{1,2}|SSS"
)
_WEEKDAYS = (
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DAYJS_DEFAULT_FORMAT = "YYYY-MM-DDTHH:mm:ssZ"

# JavaScript ``\s``: differs from Python's ``str.isspace`` set.
_JS_SPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_SLUG_REMOVE = re.compile(f"[^A-Za-z0-9_{_JS_SPACE}$*+~.()'\"!\\-:@]+")
_SLUG_SPACES = re.compile(f"[{_JS_SPACE}]+")
_JS_SPACE_CHARS = (
    "".join(
        chr(code)
        for code in (*b"\t\n\v\f\r ", 0xA0, 0x1680, *range(0x2000, 0x200B))
    )
    + "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


_JS_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_JS_INTEGER_LITERAL = re.compile(r"0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+")
_JS_FLOAT_PREFIX = re.compile(
    r"[+-]?(?:Infinity|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)
_JS_INFINITY = frozenset({"Infinity", "+Infinity", "-Infinity"})


def is_js_numeric(text: str) -> bool:
    """Mirror ``!isNaN(+text)`` for a string.

    Args:
        text: String to convert.

    Returns:
        Whether ``Number(text)`` is not ``NaN``.
    """
    stripped = text.strip(_JS_SPACE_CHARS)
    return (
        not stripped
        or stripped in _JS_INFINITY
        or _JS_DECIMAL.fullmatch(stripped) is not None
        or _JS_INTEGER_LITERAL.fullmatch(stripped) is not None
    )


def js_parse_float(text: str) -> int | float:
    """Mirror ``parseFloat``.

    Args:
        text: String to parse.

    Returns:
        Parsed number; integral finite results as ``int``, ``nan``
        when nothing parses.
    """
    match = _JS_FLOAT_PREFIX.match(text.lstrip())
    if match is None:
        return math.nan
    number = float(match.group(0))
    if math.isfinite(number) and number.is_integer():
        return int(number)
    return number


def js_truthy(value: object) -> bool:
    """Apply JavaScript truthiness (``NaN`` is falsy).

    Args:
        value: JSON-like value.

    Returns:
        Whether ``if (value)`` would pass in JavaScript.
    """
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, (list, dict)):
        return True
    return bool(value)


def js_string_key(text: str) -> bytes:
    """Sort key ordering strings by UTF-16 code units, like ``<``.

    Args:
        text: String to compare.

    Returns:
        Key whose byte order equals JavaScript string order.
    """
    return text.encode("utf-16-be", errors="surrogatepass")


def js_slice[T](items: list[T], start: float, end: float) -> list[T]:
    """Mirror ``Array.prototype.slice`` with numeric arguments.

    Args:
        items: Source list.
        start: Start index; fractions are truncated, negatives count
            from the end.
        end: End index, with the same rules.

    Returns:
        Selected elements.
    """

    def index(value: float) -> int:
        if math.isinf(value):
            return len(items) if value > 0 else -len(items) - 1
        return math.trunc(value)

    return items[index(start) : index(end)]


def format_bytes(size: float) -> str:
    """Format a size like ``bytes.format`` with default options.

    Args:
        size: Size in bytes.

    Returns:
        Size such as ``11B``, ``1.13KB`` or ``1.5MB``.
    """
    magnitude = abs(size)
    unit, divisor = "B", 1
    for name, value in _BYTE_UNITS:
        if magnitude >= value:
            unit, divisor = name, value
            break
    # Division by a power of two is exact for integer sizes, so the
    # decimal expansion equals the one ``toFixed`` rounds.
    exact = Decimal(size / divisor)
    text = str(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return _TRAILING_ZEROS.sub(r"\1", text) + unit


def _pad(value: int, width: int) -> str:
    return str(value).rjust(width, "0")


def _zone(moment: datetime) -> str:
    offset = moment.utcoffset() or timedelta()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{_pad(hours, 2)}:{_pad(rest, 2)}"


def format_datetime(timestamp_ms: float, pattern: str) -> str:
    """Format a timestamp in the server time zone like ``dayjs.format``.

    Args:
        timestamp_ms: Epoch milliseconds; fractions are truncated like
            JavaScript ``Date`` does.
        pattern: dayjs pattern, e.g. ``M/D/YYYY h:mm:ss A``; empty
            means ``YYYY-MM-DDTHH:mm:ssZ``.

    Returns:
        Formatted date; unknown ``Y`` tokens become the zone offset, as
        in dayjs.
    """
    moment = (
        _EPOCH + timedelta(milliseconds=math.trunc(timestamp_ms))
    ).astimezone()
    zone = _zone(moment)
    hour12 = moment.hour % 12 or 12
    weekday = (moment.weekday() + 1) % 7
    meridiem = "AM" if moment.hour < 12 else "PM"
    tokens = {
        "YY": str(moment.year)[-2:],
        "YYYY": _pad(moment.year, 4),
        "M": str(moment.month),
        "MM": _pad(moment.month, 2),
        "MMM": _MONTHS[moment.month - 1][:3],
        "MMMM": _MONTHS[moment.month - 1],
        "D": str(moment.day),
        "DD": _pad(moment.day, 2),
        "d": str(weekday),
        "dd": _WEEKDAYS[weekday][:2],
        "ddd": _WEEKDAYS[weekday][:3],
        "dddd": _WEEKDAYS[weekday],
        "H": str(moment.hour),
        "HH": _pad(moment.hour, 2),
        "h": str(hour12),
        "hh": _pad(hour12, 2),
        "a": meridiem.lower(),
        "A": meridiem,
        "m": str(moment.minute),
        "mm": _pad(moment.minute, 2),
        "s": str(moment.second),
        "ss": _pad(moment.second, 2),
        "SSS": _pad(moment.microsecond // 1000, 3),
        "Z": zone,
    }

    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        if escaped:
            return escaped
        return tokens.get(match.group(0)) or zone.replace(":", "")

    return _DAYJS_TOKENS.sub(replace, pattern or _DAYJS_DEFAULT_FORMAT)


@cache
def _charmap() -> dict[str, str]:
    data = resources.files("jcpy.helpers").joinpath("slugify_charmap.json")
    charmap: dict[str, str] = json.loads(data.read_text(encoding="utf-8"))
    return charmap


def slugify(text: str) -> str:
    """Make a slug like the ``slugify`` package with default options.

    Characters are transliterated through its character map, anything
    outside ``[\\w\\s$*_+~.()'"!\\-:@]`` is dropped, whitespace runs
    become ``-``.

    Args:
        text: Source text.

    Returns:
        Slug; case is preserved.
    """
    charmap = _charmap()
    parts: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        replacement = charmap.get(char, char)
        if replacement == "-":
            replacement = " "
        parts.append(_SLUG_REMOVE.sub("", replacement))
    return _SLUG_SPACES.sub("-", "".join(parts).strip(_JS_SPACE_CHARS))


_ILLEGAL_FILENAME = re.compile(r'[/?<>\\:*|"]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x80-\x9f]")
_RESERVED_NAME = re.compile(r"^\.+$")
_WINDOWS_RESERVED = re.compile(
    r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE
)
_WINDOWS_TRAILING = re.compile(r"[. ]+$")
_MAX_FILENAME_BYTES = 255


def _truncate_utf8(text: str, limit: int) -> str:
    size = 0
    for index, char in enumerate(text):
        size += len(char.encode("utf-8", errors="surrogatepass"))
        if size > limit:
            return text[:index]
    return text


def _sanitize(text: str, replacement: str) -> str:
    text = _ILLEGAL_FILENAME.sub(replacement, text)
    text = _CONTROL_CHARS.sub(replacement, text)
    text = _RESERVED_NAME.sub(replacement, text)
    text = _WINDOWS_RESERVED.sub(replacement, text)
    text = _WINDOWS_TRAILING.sub(replacement, text)
    return _truncate_utf8(text, _MAX_FILENAME_BYTES)


def sanitize_filename(name: str, replacement: str = "") -> str:
    """Make a safe file name like the ``sanitize-filename`` package.

    Path separators, reserved characters, control characters, ``.``
    and ``..``, Windows device names and trailing dots/spaces are
    replaced; the result is cut to 255 UTF-8 bytes.

    Args:
        name: Requested name.
        replacement: Substitute for removed parts.

    Returns:
        Safe name, possibly empty.
    """
    output = _sanitize(name, replacement)
    return output if not replacement else _sanitize(output, "")


_BYTES_PATTERN = re.compile(
    r"^((-|\+)?(\d+(?:\.\d+)?)) *(kb|mb|gb|tb|pb)$", re.IGNORECASE
)
_BYTES_MULTIPLIERS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
    "pb": 1024**5,
}
_JS_PARSE_INT = re.compile(r"[+-]?\d+")


def parse_bytes(value: str) -> int | None:
    """Parse a size such as ``8mb`` like ``bytes.parse``.

    Args:
        value: Size with an optional ``kb``..``pb`` unit.

    Returns:
        Size in bytes (rounded down), ``None`` when nothing parses.
    """
    match = _BYTES_PATTERN.match(value)
    if match is not None:
        number = float(match.group(1))
        unit = match.group(4).lower()
    else:
        number, unit = js_parse_int(value), "b"
        if math.isnan(number):
            return None
    return math.floor(_BYTES_MULTIPLIERS[unit] * number)


def node_extname(path: str) -> str:
    """Return the extension of a path, with the dot (``.tar.gz`` → ``.gz``).

    Args:
        path: File path.

    Returns:
        Extension with its dot (``.gz`` for ``x.tar.gz``, ``.x`` for
        ``..x``), ``""`` for names like ``.bashrc``.
    """
    start_dot, start_part, end = -1, 0, -1
    matched_slash = True
    pre_dot_state = 0
    for index in range(len(path) - 1, -1, -1):
        char = path[index]
        if char == "/":
            if not matched_slash:
                start_part = index + 1
                break
            continue
        if end == -1:
            matched_slash = False
            end = index + 1
        if char == ".":
            if start_dot == -1:
                start_dot = index
            elif pre_dot_state != 1:
                pre_dot_state = 1
        elif start_dot != -1:
            pre_dot_state = -1
    if (
        start_dot == -1
        or end == -1
        or pre_dot_state == 0
        or (
            pre_dot_state == 1
            and start_dot == end - 1
            and start_dot == start_part + 1
        )
    ):
        return ""
    return path[start_dot:end]


def node_basename(path: str, suffix: str = "") -> str:
    """Return the last path segment, without ``suffix`` when it ends so.

    Args:
        path: File path.
        suffix: Suffix to strip unless it is the whole name.

    Returns:
        Last path segment.
    """
    base = path.rstrip("/").rpartition("/")[2] if path.strip("/") else ""
    if suffix and base.endswith(suffix) and base != suffix:
        return base[: -len(suffix)]
    return base


def js_parse_int(text: str) -> float:
    """Mirror ``parseInt(text, 10)``.

    Args:
        text: String to parse.

    Returns:
        Parsed integer (as ``int``), ``nan`` when no digits lead.
    """
    prefix = _JS_PARSE_INT.match(text.lstrip(_JS_SPACE_CHARS))
    return math.nan if prefix is None else int(prefix.group(0))
