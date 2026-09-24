"""Connector actions by name."""

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.context import ActionHandler

ACTIONS: Mapping[str, ActionHandler] = MappingProxyType({})
"""Built-in action handlers keyed by action name."""
