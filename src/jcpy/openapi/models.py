"""Schemas of action parameters and responses for the API documentation.

Request validation lives in the action handlers; these models only
describe the wire format.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Doc(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# --- shared parameters --------------------------------------------------


class SourceQuery(_Doc):
    """Parameters every source-bound action accepts."""

    source: str | None = Field(
        default=None,
        description="Source name; the first (or every) source when omitted",
        examples=["default"],
    )
    path: str | None = Field(
        default=None,
        description="Directory inside the source",
        examples=["/"],
    )


class NameQuery(SourceQuery):
    """Parameters of actions working on one entry of a directory."""

    name: str = Field(description="Entry name", examples=["photo.jpg"])


class RenameQuery(NameQuery):
    """Parameters of rename actions."""

    newname: str = Field(description="New name", examples=["holiday.jpg"])


class MoveQuery(_Doc):
    """Parameters of move and copy actions."""

    source: str | None = Field(default=None, description="Source name")
    from_: str = Field(
        alias="from",
        description="Entry path relative to the source root",
        examples=["/photos/photo.jpg"],
    )
    path: str | None = Field(
        default=None,
        description="Destination directory (the root when omitted)",
        examples=["/archive"],
    )


class FilesMods(_Doc):
    """Listing modifiers, sent as ``mods[...]``."""

    with_folders: bool | None = Field(
        default=None, alias="withFolders", description="Include folders"
    )
    only_images: bool | None = Field(
        default=None, alias="onlyImages", description="Only image files"
    )
    offset: int | None = Field(default=None, description="First item")
    limit: int | None = Field(default=None, description="Number of items")
    sort_by: (
        Literal[
            "name-asc",
            "name-desc",
            "changed-asc",
            "changed-desc",
            "size-asc",
            "size-desc",
        ]
        | None
    ) = Field(default=None, alias="sortBy", description="Sort order")
    folders_position: Literal["default", "top", "bottom"] | None = Field(
        default=None, alias="foldersPosition", description="Where folders go"
    )
    filter_word: str | None = Field(
        default=None,
        alias="filterWord",
        description="Case-insensitive part of the names to keep",
    )


class FilesQuery(SourceQuery):
    """Parameters of ``files``."""

    mods: FilesMods | None = None


class FoldersQuery(SourceQuery):
    """Parameters of ``folders``."""

    dots: bool | None = Field(
        default=None, description="Start with `.` or `..` (default true)"
    )


class UrlQuery(_Doc):
    """Parameters of ``getLocalFileByUrl``."""

    url: str = Field(
        description="Public URL of a file",
        examples=["http://localhost:8081/files/photo.jpg"],
    )


class RemoteUploadQuery(SourceQuery):
    """Parameters of ``fileUploadRemote``."""

    url: str = Field(
        description="File to download", examples=["https://example.com/a.png"]
    )


class FolderCreateQuery(SourceQuery):
    """Parameters of ``folderCreate``."""

    name: str = Field(description="New folder name", examples=["photos"])


class ResizeBox(_Doc):
    """Target size, sent as ``box[w]`` and ``box[h]``."""

    w: int = Field(gt=0, description="Width in pixels")
    h: int = Field(gt=0, description="Height in pixels")


class CropBox(ResizeBox):
    """Region to keep, sent as ``box[x]``, ``box[y]``, ``box[w]``..."""

    x: int = Field(ge=0, description="Left offset in pixels")
    y: int = Field(ge=0, description="Top offset in pixels")


class ImageResizeQuery(NameQuery):
    """Parameters of ``imageResize``."""

    newname: str | None = Field(
        default=None, description="Save as (overwrite `name` when omitted)"
    )
    box: ResizeBox


class ImageCropQuery(NameQuery):
    """Parameters of ``imageCrop``."""

    newname: str | None = Field(
        default=None, description="Save as (overwrite `name` when omitted)"
    )
    box: CropBox


class ImageLoadBody(NameQuery):
    """Body of ``imageLoad``."""


class PdfOptions(_Doc):
    """PDF options, sent as ``options[...]``."""

    format: Literal["A4", "A3", "Letter", "Legal", "Tabloid"] | None = None
    page_orientation: Literal["portrait", "landscape"] | None = None
    default_font: Literal["courier", "helvetica", "times"] | None = Field(
        default=None, alias="defaultFont"
    )


class GeneratePdfQuery(_Doc):
    """Parameters of ``generatePdf``."""

    html: str = Field(min_length=1, description="Document markup")
    options: PdfOptions | None = None


class GenerateDocxQuery(_Doc):
    """Parameters of ``generateDocx``."""

    html: str = Field(min_length=1, description="Document markup")


class UploadForm(SourceQuery):
    """Multipart form of ``fileUpload``."""

    files: list[bytes] = Field(
        description="Files, as `files[0]`, `files[1]`... or the "
        "`defaultFilesKey` field",
        json_schema_extra={"items": {"type": "string", "format": "binary"}},
    )


class ImageSaveForm(SourceQuery):
    """Multipart form of ``imageSave``."""

    name: str | None = Field(default=None, description="Original image")
    newname: str | None = Field(default=None, description="Save as")
    files: list[bytes] = Field(
        description="The edited image (first file is used)",
        json_schema_extra={"items": {"type": "string", "format": "binary"}},
    )


# --- responses ------------------------------------------------------------


class ErrorData(_Doc):
    """Error details."""

    code: int = Field(description="HTTP status", examples=[400])
    messages: list[str] = Field(examples=[["Validation failed"]])


class ErrorResponse(_Doc):
    """Error envelope."""

    success: Literal[False]
    data: ErrorData


class PingResponse(_Doc):
    """Liveness probe answer."""

    success: Literal[True]


class Done(_Doc):
    """Result of an action without payload."""

    code: Literal[220] = 220


class DoneResponse(_Doc):
    """Success envelope without payload."""

    success: Literal[True]
    data: Done


class FileItem(_Doc):
    """Entry of a listing."""

    file: str = Field(examples=["photo.jpg"])
    name: str = Field(examples=["photo.jpg"])
    type: Literal["file", "image", "folder"]
    is_image: bool | None = Field(default=None, alias="isImage")
    size: str | None = Field(default=None, examples=["1.5MB"])
    changed: str | None = Field(
        default=None, examples=["9/24/2026 1:02:03 PM"]
    )
    thumb: str | None = Field(default=None, examples=["_thumbs/photo.jpg"])


class SourceFiles(_Doc):
    """Listing of one source."""

    name: str
    title: str
    baseurl: str
    path: str
    files: list[FileItem]


class FilesData(Done):
    """Result of ``files``."""

    sources: list[SourceFiles]


class FilesResponse(_Doc):
    """Answer of ``files``."""

    success: Literal[True]
    data: FilesData


class SourceFolders(_Doc):
    """Folders of one source."""

    name: str
    title: str
    baseurl: str
    path: str
    folders: list[str] = Field(examples=[["..", "photos"]])


class FoldersData(_Doc):
    """Result of ``folders``."""

    sources: list[SourceFolders]
    code: Literal[220] = 220


class FoldersResponse(_Doc):
    """Answer of ``folders``."""

    success: Literal[True]
    data: FoldersData


class PermissionsData(Done):
    """Result of ``permissions``."""

    permissions: dict[str, bool] = Field(
        examples=[{"allowFiles": True, "allowFileUpload": False}]
    )


class PermissionsResponse(_Doc):
    """Answer of ``permissions``."""

    success: Literal[True]
    data: PermissionsData


class UploadData(Done):
    """Result of ``fileUpload``."""

    baseurl: str
    messages: list[str] = Field(examples=[["File photo.jpg was uploaded"]])
    files: list[str] = Field(examples=[["photos/photo.jpg"]])
    is_images: list[bool] = Field(alias="isImages")


class UploadResponse(_Doc):
    """Answer of ``fileUpload``."""

    success: Literal[True]
    data: UploadData


class RemoteUploadData(Done):
    """Result of ``fileUploadRemote``."""

    baseurl: str
    newfilename: str = Field(examples=["photo.jpg"])
    is_image: bool = Field(alias="isImage")


class RemoteUploadResponse(_Doc):
    """Answer of ``fileUploadRemote``."""

    success: Literal[True]
    data: RemoteUploadData


class LocalFileData(Done):
    """Result of ``getLocalFileByUrl``."""

    path: str = Field(examples=["/photos"])
    name: str = Field(examples=["photo.jpg"])
    source: str = Field(examples=["default"])


class LocalFileResponse(_Doc):
    """Answer of ``getLocalFileByUrl``."""

    success: Literal[True]
    data: LocalFileData


class MessagesData(Done):
    """Result carrying messages."""

    messages: list[str]


class MessagesResponse(_Doc):
    """Answer carrying messages."""

    success: Literal[True]
    data: MessagesData


class ImageData(Done):
    """Result of ``imageResize`` and ``imageCrop``."""

    new_path: str = Field(
        alias="newPath", examples=["http://localhost:8081/files/photo.jpg"]
    )


class ImageResponse(_Doc):
    """Answer of ``imageResize`` and ``imageCrop``."""

    success: Literal[True]
    data: ImageData


class ImageSaveData(ImageData):
    """Result of ``imageSave``."""

    name: str


class ImageSaveResponse(_Doc):
    """Answer of ``imageSave``."""

    success: Literal[True]
    data: ImageSaveData


class ImageLoadData(Done):
    """Result of ``imageLoad``."""

    content: str = Field(examples=["data:image/png;base64,iVBORw0KGgo..."])
    name: str


class ImageLoadResponse(_Doc):
    """Answer of ``imageLoad``."""

    success: Literal[True]
    data: ImageLoadData
