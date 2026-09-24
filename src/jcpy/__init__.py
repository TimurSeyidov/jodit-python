"""Jodit FileBrowser and Uploader connector for Python."""

from importlib.metadata import version

from jcpy.acl import (
    DEFAULT_RULES,
    AccessControl,
    AccessControlProtocol,
    RulesProvider,
)
from jcpy.app import create_app, create_router
from jcpy.config.loader import load_config
from jcpy.config.models import (
    AccessControlRule,
    ActionPredicate,
    AppConfig,
    ExtensionsResolver,
    SourceConfig,
)
from jcpy.connector import Connector
from jcpy.context import ActionContext
from jcpy.errors import ConfigError, HttpError
from jcpy.helpers.svg_icon import SvgGenerator, generate_icon
from jcpy.storage import StorageAdapter, register_storage_adapter
from jcpy.tenants import ResolvedSources, SourcesResolver
from jcpy.types import AuthCallback, OriginPredicate

__version__ = version("jodit-python")

__all__ = [
    "DEFAULT_RULES",
    "AccessControl",
    "AccessControlProtocol",
    "AccessControlRule",
    "ActionContext",
    "ActionPredicate",
    "AppConfig",
    "AuthCallback",
    "ConfigError",
    "Connector",
    "ExtensionsResolver",
    "HttpError",
    "OriginPredicate",
    "ResolvedSources",
    "RulesProvider",
    "SourceConfig",
    "SourcesResolver",
    "StorageAdapter",
    "SvgGenerator",
    "__version__",
    "create_app",
    "create_router",
    "generate_icon",
    "load_config",
    "register_storage_adapter",
]
