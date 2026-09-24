"""Connector actions by name."""

from types import MappingProxyType
from typing import TYPE_CHECKING

from jcpy.v1.file_copy.handler import file_copy_handler
from jcpy.v1.file_download.handler import file_download_handler
from jcpy.v1.file_move.handler import file_move_handler
from jcpy.v1.file_remove.handler import file_remove_handler
from jcpy.v1.file_rename.handler import file_rename_handler
from jcpy.v1.file_upload.handler import file_upload_handler
from jcpy.v1.file_upload_remote.handler import file_upload_remote_handler
from jcpy.v1.files.handler import files_handler
from jcpy.v1.folder_copy.handler import folder_copy_handler
from jcpy.v1.folder_create.handler import folder_create_handler
from jcpy.v1.folder_move.handler import folder_move_handler
from jcpy.v1.folder_remove.handler import folder_remove_handler
from jcpy.v1.folder_rename.handler import folder_rename_handler
from jcpy.v1.folders.handler import folders_handler
from jcpy.v1.generate_docx.handler import generate_docx_handler
from jcpy.v1.generate_pdf.handler import generate_pdf_handler
from jcpy.v1.get_local_file_by_url.handler import (
    get_local_file_by_url_handler,
)
from jcpy.v1.image_crop.handler import image_crop_handler
from jcpy.v1.image_load.handler import image_load_handler
from jcpy.v1.image_resize.handler import image_resize_handler
from jcpy.v1.image_save.handler import image_save_handler
from jcpy.v1.permissions.handler import permissions_handler

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.context import ActionHandler

ACTIONS: Mapping[str, ActionHandler] = MappingProxyType(
    {
        "files": files_handler,
        "fileUpload": file_upload_handler,
        "fileUploadRemote": file_upload_remote_handler,
        "fileRemove": file_remove_handler,
        "fileMove": file_move_handler,
        "fileCopy": file_copy_handler,
        "fileRename": file_rename_handler,
        "folderCreate": folder_create_handler,
        "folderRemove": folder_remove_handler,
        "folderMove": folder_move_handler,
        "folderCopy": folder_copy_handler,
        "folderRename": folder_rename_handler,
        "fileDownload": file_download_handler,
        "getLocalFileByUrl": get_local_file_by_url_handler,
        "folders": folders_handler,
        "permissions": permissions_handler,
        "imageResize": image_resize_handler,
        "imageCrop": image_crop_handler,
        "imageSave": image_save_handler,
        "imageLoad": image_load_handler,
        "generatePdf": generate_pdf_handler,
        "generateDocx": generate_docx_handler,
    }
)
"""Built-in action handlers keyed by action name."""
