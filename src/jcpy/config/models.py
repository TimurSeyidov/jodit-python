"""Connector configuration models.

Field names are snake_case in Python and camelCase in JSON.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from jcpy.config import defaults

type ExtensionsResolver = Callable[
    [str, AccessControlRule, str, str], list[str]
]
"""Compute the upper-cased extensions a rule applies to.

Called with the CONSTANT_CASE action, the rule, the path and the file
extension of the checked request.
"""

type ActionPredicate = Callable[[str, AccessControlRule, str, str], object]
"""Decide an action for the request; a non-boolean result allows it.

Called with the CONSTANT_CASE action, the rule, the path and the file
extension of the checked request.
"""


def _check_url(value: str) -> str:
    AnyUrl(value)
    return value


class _Model(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class PaperConfig(_Model):
    """PDF paper settings."""

    format: str = "A4"
    page_orientation: str = Field(default="portrait", alias="page_orientation")


class PdfConfig(_Model):
    """PDF generation settings."""

    default_font: str = "serif"
    is_remote_enabled: bool = True
    font_dir: str = Field(default_factory=tempfile.gettempdir)
    font_cache: str = Field(default_factory=tempfile.gettempdir)
    temp_dir: str = Field(default_factory=tempfile.gettempdir)
    chroot: str = Field(default_factory=tempfile.gettempdir)
    paper: PaperConfig = PaperConfig()


class S3Credentials(_Model):
    """Static S3 credentials."""

    access_key_id: Annotated[str, Field(min_length=1)]
    secret_access_key: Annotated[str, Field(min_length=1)]
    session_token: str | None = None


class S3Options(_Model):
    """Options of the built-in ``s3`` storage adapter."""

    bucket: Annotated[str, Field(min_length=1)]
    region: str | None = None
    endpoint: str | None = None
    force_path_style: bool | None = None
    prefix: str | None = None
    credentials: S3Credentials | None = None
    public_base_url: str | None = None
    connect_timeout: PositiveFloat = 10
    read_timeout: PositiveFloat = 60
    max_attempts: PositiveInt = 3

    @field_validator("endpoint", "public_base_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return None if value is None else _check_url(value)


class DynamicSourcesCache(_Model):
    """Cache limits for sources built by ``resolve_sources``."""

    max: PositiveInt = 200
    ttl_ms: PositiveInt = 60_000


class AccessControlRule(BaseModel):
    """Access control rule.

    ``role``, ``path`` and ``extensions`` select the requests the rule
    applies to (``None`` matches everything); every other key is an
    action name in CONSTANT_CASE (``FILE_UPLOAD``) mapped to a flag or,
    in rules built in code, to an ``ActionPredicate``.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    role: str | None = None
    path: str | None = None
    extensions: str | list[str] | ExtensionsResolver | None = None

    @model_validator(mode="after")
    def _actions_are_flags(self) -> Self:
        for key, value in (self.model_extra or {}).items():
            if not isinstance(value, bool) and not callable(value):
                msg = f"action {key!r} must be true or false"
                raise ValueError(msg)
        return self

    @property
    def actions(self) -> dict[str, bool | ActionPredicate]:
        """Action permissions declared by the rule.

        Returns:
            Mapping of CONSTANT_CASE action names to a flag or a
            predicate.
        """
        return dict(self.model_extra or {})


class AppConfig(_Model):
    """Complete connector configuration with its defaults."""

    title: str = ""
    default_files_key: str = "default"
    save_same_file_name_strategy: str = "addNumber"
    debug: bool = True
    sources: dict[str, SourceConfig] = Field(
        default_factory=lambda: {
            "default": SourceConfig.model_validate(defaults.default_source())
        }
    )
    dynamic_sources_cache: DynamicSourcesCache = DynamicSourcesCache()
    datetime_format: str = "M/D/YYYY h:mm:ss A"
    quality: int = 90
    count_in_chunk: int = 1_000_000
    default_sort_by: str = "changed-desc"
    default_permission: int = 0o775
    create_thumb: bool = True
    thumb_size: int = 250
    thumb_folder_name: str = "_thumbs"
    generate_svg_thumbs: bool = True
    svg_thumb_width: int = 100
    svg_thumb_height: int = 100
    exclude_directory_names: list[str] = Field(
        default_factory=lambda: [".tmb", ".quarantine"]
    )
    max_file_size: str = "8mb"
    max_upload_file_size: str = "8mb"
    memory_limit: str = "256M"
    timeout_limit: int = 60
    allow_cross_origin: bool = False
    allowed_origins: list[str] | None = None
    only_post: bool = Field(default=False, alias="onlyPOST")
    safe_thumbs_count_in_one_time: int = 20
    source_class_name: str = "FileSystem"
    access_control: list[AccessControlRule] = Field(default_factory=list)
    role_session_var: str = "JoditUserRole"
    default_role: str = "guest"
    allow_replace_source_file: bool = True
    allow_private_network_uploads: bool = False
    baseurl: str = ""
    root: str = Field(default_factory=lambda: str(Path.cwd() / "files"))
    extensions: list[str] = Field(
        default_factory=lambda: list(defaults.EXTENSIONS)
    )
    image_extensions: list[str] = Field(
        default_factory=lambda: list(defaults.IMAGE_EXTENSIONS)
    )
    max_image_width: int = 1900
    max_image_height: int = 1900
    pdf: PdfConfig = PdfConfig()

    @model_validator(mode="before")
    @classmethod
    def _name_sources(cls, data: Any) -> Any:  # noqa: ANN401
        """Default every source ``name`` to its key in ``sources``."""
        sources = data.get("sources") if isinstance(data, dict) else None
        if isinstance(sources, dict):
            data = {
                **data,
                "sources": {
                    key: (
                        {"name": key, **value}
                        if isinstance(value, dict)
                        else value
                    )
                    for key, value in sources.items()
                },
            }
        return data

    @model_validator(mode="after")
    def _validate_source_overrides(self) -> Self:
        for name in self.sources:
            try:
                self.for_source(name)
            except ValidationError as error:
                details = "; ".join(
                    f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                    for item in error.errors()
                )
                msg = f"source {name!r} overrides: {details}"
                raise ValueError(msg) from None
        return self

    def for_source(self, name: str) -> AppConfig:
        """Build the configuration seen by one source.

        Every setting the source defines replaces the global one;
        ``sources`` itself cannot be overridden.

        Args:
            name: Key of the source in ``sources``.

        Returns:
            Effective configuration of the source.

        Raises:
            KeyError: There is no such source.
            pydantic.ValidationError: An override has an invalid value.
        """
        return self.with_overrides(self.sources[name])

    def with_overrides(self, source: SourceConfig) -> AppConfig:
        """Build the configuration seen by a source, configured or not.

        Args:
            source: Source settings.

        Returns:
            Global settings with the source overrides applied and no
            ``sources``.

        Raises:
            pydantic.ValidationError: An override has an invalid value.
        """
        data = self.model_dump(exclude={"sources"})
        return AppConfig.model_validate(
            {**data, **source.overrides(), "sources": {}}
        )


class SourceConfig(BaseModel):
    """File source.

    Besides its own fields a source may set any ``AppConfig`` setting
    (except ``sources``), overriding the global value for this source.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        extra="allow",
        frozen=True,
    )

    name: str
    title: str
    baseurl: str
    root: str | None = None
    default_files_key: str | None = None
    storage_adapter: str | None = None
    s3: S3Options | None = None

    @field_validator("baseurl")
    @classmethod
    def _baseurl_is_url(cls, value: str) -> str:
        return _check_url(value)

    @model_validator(mode="after")
    def _check_storage(self) -> Self:
        unknown = sorted(
            set(self.model_extra or {}) - _OVERRIDABLE - _OWN_FIELDS
        )
        if unknown:
            msg = f"unknown settings: {', '.join(unknown)}"
            raise ValueError(msg)
        if self.is_local and not self.root:
            msg = "root is required for local storage"
            raise ValueError(msg)
        if self.storage_adapter == "s3" and self.s3 is None:
            msg = 's3 options are required for storageAdapter "s3"'
            raise ValueError(msg)
        return self

    @property
    def is_local(self) -> bool:
        """Whether the source is backed by the local filesystem.

        Returns:
            ``True`` for the default ``local`` storage adapter.
        """
        return self.storage_adapter in {None, "local"}

    def overrides(self) -> dict[str, Any]:
        """Collect the global settings this source replaces.

        Returns:
            Settings keyed by their JSON (camelCase) names.
        """
        result: dict[str, Any] = dict(self.model_extra or {})
        for field_name in ("title", "root", "default_files_key"):
            value = getattr(self, field_name)
            if value is not None:
                result[to_camel(field_name)] = value
        result["baseurl"] = self.baseurl
        return result


_OWN_FIELDS = frozenset(
    {"name", "title", "baseurl", "root", "defaultFilesKey"}
    | {"storageAdapter", "s3"}
)
_OVERRIDABLE = frozenset(
    info.alias or name
    for name, info in AppConfig.model_fields.items()
    if name != "sources"
)

AppConfig.model_rebuild()
