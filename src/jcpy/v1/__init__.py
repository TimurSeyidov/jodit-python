"""Connector actions by name."""

from types import MappingProxyType
from typing import TYPE_CHECKING

from jcpy.v1.permissions.handler import permissions_handler

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.context import ActionHandler

ACTIONS: Mapping[str, ActionHandler] = MappingProxyType(
    {"permissions": permissions_handler}
)
"""Built-in action handlers keyed by action name."""
