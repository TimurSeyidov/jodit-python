"""Connector actions by name."""

from types import MappingProxyType
from typing import TYPE_CHECKING

from jcpy.v1.file_download.handler import file_download_handler
from jcpy.v1.files.handler import files_handler
from jcpy.v1.folders.handler import folders_handler
from jcpy.v1.get_local_file_by_url.handler import (
    get_local_file_by_url_handler,
)
from jcpy.v1.permissions.handler import permissions_handler

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.context import ActionHandler

ACTIONS: Mapping[str, ActionHandler] = MappingProxyType(
    {
        "files": files_handler,
        "fileDownload": file_download_handler,
        "getLocalFileByUrl": get_local_file_by_url_handler,
        "folders": folders_handler,
        "permissions": permissions_handler,
    }
)
"""Built-in action handlers keyed by action name."""
