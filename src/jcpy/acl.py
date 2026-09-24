"""Role, path and extension based access control."""

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from types import MappingProxyType
from typing import Protocol

from jcpy.config.models import AccessControlRule, ExtensionsResolver
from jcpy.errors import HttpError
from jcpy.helpers.case import constant_case

DEFAULT_RULES = MappingProxyType(
    {
        "FILES": True,
        "FILE_MOVE": True,
        "FILE_COPY": True,
        "FILE_UPLOAD": True,
        "FILE_UPLOAD_REMOTE": True,
        "FILE_REMOVE": True,
        "FILE_RENAME": True,
        "FILE_DOWNLOAD": True,
        "FOLDERS": True,
        "FOLDER_MOVE": True,
        "FOLDER_COPY": True,
        "FOLDER_CREATE": True,
        "FOLDER_REMOVE": True,
        "FOLDER_RENAME": True,
        "FOLDER_TREE": True,
        "IMAGE_RESIZE": True,
        "IMAGE_CROP": True,
        "IMAGE_SAVE": True,
        "IMAGE_LOAD": True,
        "GENERATE_PDF": True,
        "GENERATE_DOCX": True,
    }
)
"""Permission of every action when no rule decides it."""

ACCESS_DENIED = "Access denied"

type Rules = Sequence[AccessControlRule]

type RulesProvider = Callable[[], Rules | Awaitable[Rules]]
"""Load the rules on every check, e.g. from a database."""

_SEPARATORS = re.compile(r"[,\s]+")
_SLASHES = re.compile(r"/+")


class AccessControlProtocol(Protocol):
    """Interface of an access control implementation."""

    async def is_allow(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        """Tell whether the role may run the action.

        Args:
            role: User role.
            action: Action name in any case (``fileUpload``).
            path: Path the action works on.
            file_extension: Extension of the file, ``*`` for any.

        Returns:
            ``True`` when allowed.
        """
        ...

    async def check_permission(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        """Require the role to be allowed to run the action.

        Args:
            role: User role.
            action: Action name in any case (``fileUpload``).
            path: Path the action works on.
            file_extension: Extension of the file, ``*`` for any.

        Returns:
            ``True``.

        Raises:
            HttpError: ``403 Access denied``.
        """
        ...


def normalize_path(path: str) -> str:
    """Use forward slashes and collapse repeated ones.

    Args:
        path: Path with any separators.

    Returns:
        Normalized path.
    """
    return _SLASHES.sub("/", path.replace("\\", "/"))


class AccessControl:
    """Evaluate access control rules; the last matching rule wins.

    Args:
        rules: Rules, or a callable returning them (sync or async).
    """

    def __init__(self, rules: Rules | RulesProvider) -> None:
        self._rules = rules

    def set_access_list(self, rules: Rules | RulesProvider) -> None:
        """Replace the rules.

        Args:
            rules: Rules, or a callable returning them (sync or async).
        """
        self._rules = rules

    async def _load_rules(self) -> Rules:
        if not callable(self._rules):
            return self._rules
        loaded = self._rules()
        return await loaded if inspect.isawaitable(loaded) else loaded

    async def check_permission(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        """Require the role to be allowed to run the action.

        Args:
            role: User role.
            action: Action name in any case (``fileUpload``).
            path: Path the action works on.
            file_extension: Extension of the file, ``*`` for any.

        Returns:
            ``True``.

        Raises:
            HttpError: ``403 Access denied``.
        """
        if not await self.is_allow(role, action, path, file_extension):
            raise HttpError.forbidden(ACCESS_DENIED)
        return True

    async def is_allow(
        self,
        role: str,
        action: str,
        path: str = "/",
        file_extension: str = "*",
    ) -> bool:
        """Tell whether the role may run the action.

        A rule applies when its role is missing, ``*`` or equal to
        ``role``, the normalized ``path`` starts with its path, and its
        extensions contain ``*`` or ``file_extension``. The last
        applying rule that mentions the action decides; without one
        ``DEFAULT_RULES`` (or ``True`` for unknown actions) does.

        Args:
            role: User role.
            action: Action name in any case (``fileUpload``).
            path: Path the action works on.
            file_extension: Extension of the file, ``*`` for any.

        Returns:
            ``True`` when allowed.
        """
        name = constant_case(action)
        allow: bool | None = None
        for rule in await self._load_rules():
            if not _applies(rule, role, name, path, file_extension):
                continue
            value = rule.actions.get(name)
            if value is None:
                continue
            if isinstance(value, bool):
                allow = value
            else:
                result = value(name, rule, path, file_extension)
                allow = result if isinstance(result, bool) else True
        if allow is None:
            allow = DEFAULT_RULES.get(name, True)
        return allow


def _rule_extensions(
    extensions: str | list[str] | ExtensionsResolver,
    rule: AccessControlRule,
    name: str,
    path: str,
    file_extension: str,
) -> list[str]:
    if isinstance(extensions, str):
        return [item.upper() for item in _SEPARATORS.split(extensions)]
    if isinstance(extensions, list):
        return [item.upper() for item in extensions]
    return extensions(name, rule, path, file_extension)


def _applies(
    rule: AccessControlRule,
    role: str,
    name: str,
    path: str,
    file_extension: str,
) -> bool:
    if rule.role is not None and rule.role not in {"*", role}:
        return False
    if rule.path is not None and not normalize_path(path).startswith(
        normalize_path(rule.path)
    ):
        return False
    if rule.extensions is None:
        return True
    allowed = _rule_extensions(
        rule.extensions, rule, name, path, file_extension
    )
    return "*" in allowed or file_extension.upper() in allowed
