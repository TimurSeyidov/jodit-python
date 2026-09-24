"""Loading the connector configuration from JSON."""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from jcpy.config.models import AppConfig
from jcpy.errors import ConfigError
from jcpy.helpers.merge import override

if TYPE_CHECKING:
    from jcpy.types import JsonObject

CONFIG_ENV = "CONFIG"
CONFIG_FILE_ENV = "CONFIG_FILE"


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"Cannot read config file {path}: {error.strerror}"
        raise ConfigError(msg) from error


def _parse(text: str, origin: str) -> JsonObject:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"Invalid JSON in {origin}: {error}"
        raise ConfigError(msg) from error
    if not isinstance(data, dict):
        msg = f"{origin} must contain a JSON object"
        raise ConfigError(msg)
    return data


def read_user_config(config_file: str | Path | None = None) -> JsonObject:
    """Read the user configuration without applying defaults.

    Sources, in order of priority: ``config_file``, the ``CONFIG``
    environment variable (JSON text), the file named by
    ``CONFIG_FILE``.

    Args:
        config_file: Path to a JSON file.

    Returns:
        User settings; empty when no source is set.

    Raises:
        ConfigError: The file cannot be read or is not a JSON object.
    """
    if config_file is not None:
        path = Path(config_file)
        return _parse(_read_file(path), str(path))
    if inline := os.environ.get(CONFIG_ENV):
        return _parse(inline, f"the {CONFIG_ENV} environment variable")
    if file_name := os.environ.get(CONFIG_FILE_ENV):
        path = Path(file_name).resolve()
        return _parse(_read_file(path), str(path))
    return {}


def build_config(user: JsonObject) -> AppConfig:
    """Apply user settings on top of the defaults.

    Nested objects are merged, other values (lists included) replace
    the default, ``null`` keeps the default, ``sources`` replaces the
    default sources as a whole.

    Args:
        user: Settings with their JSON (camelCase) names.

    Returns:
        Validated configuration.

    Raises:
        ConfigError: A setting is unknown or has an invalid value.
    """
    defaults: JsonObject = AppConfig().model_dump(mode="json")
    data = override(defaults, user, replace={"sources"})
    try:
        return AppConfig.model_validate(data)
    except ValidationError as error:
        details = "\n".join(
            f"  {'.'.join(map(str, item['loc'])) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        msg = f"Invalid connector config:\n{details}"
        raise ConfigError(msg) from None


def load_config(config_file: str | Path | None = None) -> AppConfig:
    """Load the configuration: code defaults overridden by user JSON.

    Args:
        config_file: Path to a JSON file; when omitted ``CONFIG`` and
            then ``CONFIG_FILE`` are consulted.

    Returns:
        Validated configuration.

    Raises:
        ConfigError: The configuration cannot be read or is invalid.
    """
    return build_config(read_user_config(config_file))
