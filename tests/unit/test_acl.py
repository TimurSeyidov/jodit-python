"""Access control rules, ported from jodit-nodejs access-control.test.ts."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from jcpy.acl import DEFAULT_RULES, AccessControl, normalize_path
from jcpy.config.models import AccessControlRule
from jcpy.errors import HttpError

if TYPE_CHECKING:
    from jcpy.types import JsonObject


def acl(*rules: JsonObject | AccessControlRule) -> AccessControl:
    return AccessControl(
        [
            rule
            if isinstance(rule, AccessControlRule)
            else AccessControlRule.model_validate(rule)
            for rule in rules
        ]
    )


def test_default_rules_allow_everything() -> None:
    assert all(DEFAULT_RULES.values())
    assert {
        "FILES",
        "FILE_MOVE",
        "FILE_COPY",
        "FILE_UPLOAD",
        "FILE_UPLOAD_REMOTE",
        "FILE_REMOVE",
        "FILE_RENAME",
        "FILE_DOWNLOAD",
        "FOLDERS",
        "FOLDER_MOVE",
        "FOLDER_COPY",
        "FOLDER_CREATE",
        "FOLDER_REMOVE",
        "FOLDER_RENAME",
        "FOLDER_TREE",
        "IMAGE_RESIZE",
        "IMAGE_CROP",
        "IMAGE_SAVE",
        "IMAGE_LOAD",
        "GENERATE_PDF",
        "GENERATE_DOCX",
    } == set(DEFAULT_RULES)


async def test_set_access_list_replaces_rules() -> None:
    access = acl()
    access.set_access_list(
        [AccessControlRule.model_validate({"role": "admin", "FILES": False})]
    )

    assert await access.is_allow("admin", "FILES", "/", "*") is False


class TestBasicChecks:
    async def test_explicit_true(self) -> None:
        access = acl({"role": "user", "FILES": True})

        assert await access.is_allow("user", "FILES", "/", "*") is True

    async def test_explicit_false(self) -> None:
        access = acl({"role": "user", "FILES": False})

        assert await access.is_allow("user", "FILES", "/", "*") is False

    async def test_default_rule_without_match(self) -> None:
        assert await acl().is_allow("any-role", "FILES", "/", "*") is True

    async def test_unknown_action_is_allowed(self) -> None:
        assert await acl().is_allow("guest", "somethingElse") is True

    @pytest.mark.parametrize("action", ["fileUpload", "file-upload"])
    async def test_action_names_are_constant_cased(self, action: str) -> None:
        access = acl({"role": "user", "FILE_UPLOAD": False})

        assert await access.is_allow("user", action, "/", "*") is False


class TestRoles:
    async def test_exact_role(self) -> None:
        access = acl({"role": "admin", "FILES": False})

        assert await access.is_allow("admin", "FILES") is False
        assert await access.is_allow("user", "FILES") is True

    async def test_wildcard_role(self) -> None:
        access = acl({"role": "*", "FILES": False})

        for role in ("admin", "user", "guest"):
            assert await access.is_allow(role, "FILES") is False

    async def test_rule_of_other_role_is_skipped(self) -> None:
        access = acl(
            {"role": "admin", "FILES": False}, {"role": "user", "FILES": True}
        )

        assert await access.is_allow("user", "FILES") is True

    async def test_rule_without_role_matches_any(self) -> None:
        access = acl({"FILES": False})

        assert await access.is_allow("any-role", "FILES") is False


class TestPaths:
    async def test_exact_path(self) -> None:
        access = acl({"role": "user", "path": "/private", "FILES": False})

        assert await access.is_allow("user", "FILES", "/private") is False
        assert await access.is_allow("user", "FILES", "/public") is True

    async def test_path_prefix(self) -> None:
        access = acl({"role": "user", "path": "/private", "FILES": False})

        assert (
            await access.is_allow("user", "FILES", "/private/folder/a.txt")
            is False
        )

    @pytest.mark.parametrize(
        "rule_path", ["/private\\subfolder", "/private///subfolder"]
    )
    async def test_rule_path_is_normalized(self, rule_path: str) -> None:
        access = acl({"role": "user", "path": rule_path, "FILES": False})

        assert (
            await access.is_allow("user", "FILES", "/private/subfolder/f.txt")
            is False
        )

    async def test_rule_without_path_matches_any(self) -> None:
        access = acl({"role": "user", "FILES": False})

        assert await access.is_allow("user", "FILES", "/any/path") is False

    def test_normalize_path(self) -> None:
        assert normalize_path("\\a//b\\\\c") == "/a/b/c"


class TestExtensions:
    async def test_single_extension_string(self) -> None:
        access = acl(
            {"role": "user", "extensions": "jpg", "FILE_REMOVE": False}
        )

        assert (
            await access.is_allow("user", "FILE_REMOVE", "/", "jpg") is False
        )
        assert await access.is_allow("user", "FILE_REMOVE", "/", "png") is True

    async def test_comma_separated_string(self) -> None:
        access = acl(
            {
                "role": "user",
                "extensions": "jpg, png, gif",
                "FILE_REMOVE": False,
            }
        )

        for extension in ("jpg", "png", "gif"):
            assert (
                await access.is_allow("user", "FILE_REMOVE", "/", extension)
                is False
            )
        assert await access.is_allow("user", "FILE_REMOVE", "/", "txt") is True

    async def test_list_is_case_insensitive(self) -> None:
        access = acl(
            {
                "role": "user",
                "extensions": ["JPG", "png"],
                "FILE_REMOVE": False,
            }
        )

        for extension in ("jpg", "JPG", "PNG", "png"):
            assert (
                await access.is_allow("user", "FILE_REMOVE", "/", extension)
                is False
            )
        assert await access.is_allow("user", "FILE_REMOVE", "/", "txt") is True

    async def test_wildcard_extension(self) -> None:
        access = acl({"role": "user", "extensions": "*", "FILE_REMOVE": False})

        for extension in ("jpg", "txt", "pdf"):
            assert (
                await access.is_allow("user", "FILE_REMOVE", "/", extension)
                is False
            )

    async def test_extensions_resolver(self) -> None:
        def resolver(
            action: str, rule: AccessControlRule, path: str, extension: str
        ) -> list[str]:
            return ["JPG"] if extension == "jpg" else []

        access = acl(
            AccessControlRule.model_validate(
                {"role": "user", "extensions": resolver, "FILE_REMOVE": False}
            )
        )

        assert (
            await access.is_allow("user", "FILE_REMOVE", "/", "jpg") is False
        )
        assert await access.is_allow("user", "FILE_REMOVE", "/", "png") is True

    async def test_empty_extension_string_matches_nothing(self) -> None:
        access = acl({"role": "user", "extensions": "", "FILE_REMOVE": False})

        assert await access.is_allow("user", "FILE_REMOVE", "/", "jpg") is True

    async def test_rule_with_extensions_skips_any_extension_checks(
        self,
    ) -> None:
        access = acl(
            {"role": "user", "extensions": ["jpg"], "FILE_REMOVE": False}
        )

        assert await access.is_allow("user", "FILE_REMOVE") is True

    async def test_rule_without_extensions_matches_any(self) -> None:
        access = acl({"role": "user", "FILE_REMOVE": False})

        assert (
            await access.is_allow("user", "FILE_REMOVE", "/", "any") is False
        )


class TestActionPredicates:
    async def test_boolean_result(self) -> None:
        def only_allowed(
            action: str, rule: AccessControlRule, path: str, extension: str
        ) -> bool:
            return "allowed" in path

        access = acl(
            AccessControlRule.model_validate(
                {"role": "user", "FILES": only_allowed}
            )
        )

        assert await access.is_allow("user", "FILES", "/allowed/p") is True
        assert await access.is_allow("user", "FILES", "/denied/p") is False

    async def test_non_boolean_result_allows(self) -> None:
        def text(
            action: str, rule: AccessControlRule, path: str, extension: str
        ) -> str:
            return "some string"

        access = acl(
            AccessControlRule.model_validate({"role": "user", "FILES": text})
        )

        assert await access.is_allow("user", "FILES") is True

    async def test_predicate_receives_request_details(self) -> None:
        calls: list[tuple[str, str | None, str, str]] = []

        def spy(
            action: str, rule: AccessControlRule, path: str, extension: str
        ) -> bool:
            calls.append((action, rule.role, path, extension))
            return True

        access = acl(
            AccessControlRule.model_validate(
                {"role": "user", "FILE_UPLOAD": spy}
            )
        )
        await access.is_allow("user", "fileUpload", "/a", "png")

        assert calls == [("FILE_UPLOAD", "user", "/a", "png")]


class TestPriority:
    async def test_last_matching_rule_wins(self) -> None:
        access = acl(
            {"role": "user", "FILES": True}, {"role": "user", "FILES": False}
        )

        assert await access.is_allow("user", "FILES") is False

    async def test_specific_rules_later(self) -> None:
        access = acl(
            {"role": "user", "FILES": True},
            {"role": "user", "path": "/private", "FILES": False},
        )

        assert await access.is_allow("user", "FILES", "/public") is True
        assert await access.is_allow("user", "FILES", "/private") is False

    async def test_role_path_and_extension_together(self) -> None:
        access = acl(
            {
                "role": "user",
                "path": "/uploads",
                "extensions": ["jpg", "png"],
                "FILE_UPLOAD": False,
            }
        )

        check = access.is_allow
        assert (
            await check("user", "FILE_UPLOAD", "/uploads/i.jpg", "jpg")
            is False
        )
        assert await check("admin", "FILE_UPLOAD", "/uploads/i.jpg", "jpg")
        assert await check("user", "FILE_UPLOAD", "/public/i.jpg", "jpg")
        assert await check("user", "FILE_UPLOAD", "/uploads/f.txt", "txt")

    async def test_overlapping_rules(self) -> None:
        access = acl(
            {"role": "*", "FILES": False}, {"role": "admin", "FILES": True}
        )

        assert await access.is_allow("guest", "FILES") is False
        assert await access.is_allow("admin", "FILES") is True

    async def test_rule_without_action_uses_default(self) -> None:
        access = acl({"role": "user"})

        assert await access.is_allow("user", "FILES") is True


class TestCheckPermission:
    async def test_allowed(self) -> None:
        access = acl({"role": "user", "FILES": True})

        assert await access.check_permission("user", "FILES") is True

    async def test_denied(self) -> None:
        access = acl({"role": "user", "FILES": False})

        with pytest.raises(HttpError, match="Access denied") as info:
            await access.check_permission("user", "FILES", "/", "*")

        assert info.value.status_code == 403


class TestRuleProviders:
    async def test_sync_provider(self) -> None:
        def rules() -> list[AccessControlRule]:
            return [AccessControlRule.model_validate({"FILES": False})]

        assert await AccessControl(rules).is_allow("guest", "FILES") is False

    async def test_async_provider_is_called_per_check(self) -> None:
        calls: list[int] = []

        async def rules() -> list[AccessControlRule]:
            await asyncio.sleep(0)
            calls.append(1)
            return [AccessControlRule.model_validate({"FILES": True})]

        access = AccessControl(rules)
        await access.is_allow("guest", "FILES")
        await access.is_allow("guest", "FILES")

        assert len(calls) == 2


def test_json_rules_reject_non_boolean_actions() -> None:
    with pytest.raises(ValueError, match="must be true or false"):
        AccessControlRule.model_validate({"FILES": "yes"})
