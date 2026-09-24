"""The documentation covers everything the code offers."""

import re
from pathlib import Path

import pytest

from jcpy.acl import DEFAULT_RULES
from jcpy.config.models import AppConfig, PdfConfig, S3Options, SourceConfig
from jcpy.helpers.case import constant_case
from jcpy.v1 import ACTIONS

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "docs" / "content"


def page(name: str) -> str:
    return (CONTENT / name).read_text("utf-8")


def aliases(
    model: type[AppConfig | SourceConfig | PdfConfig | S3Options],
) -> set[str]:
    return {info.alias or name for name, info in model.model_fields.items()}


@pytest.mark.parametrize("key", sorted(aliases(AppConfig)))
def test_setting_is_documented(key: str) -> None:
    assert f"`{key}`" in page("config.md")


@pytest.mark.parametrize(
    "key",
    sorted(aliases(SourceConfig) | {f"pdf.{k}" for k in aliases(PdfConfig)}),
)
def test_nested_setting_is_documented(key: str) -> None:
    assert f"`{key.removeprefix('pdf.')}`" in page("config.md")


@pytest.mark.parametrize("key", sorted(aliases(S3Options)))
def test_s3_option_is_documented(key: str) -> None:
    assert f"`{key}`" in page("aws-s3.md")


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_action_is_documented(action: str) -> None:
    assert re.search(rf"^### .*`{action}`", page("api.md"), re.MULTILINE)


@pytest.mark.parametrize(
    "key",
    sorted({*DEFAULT_RULES, *(constant_case(action) for action in ACTIONS)}),
)
def test_rule_key_is_documented(key: str) -> None:
    assert f"`{key}`" in page("access-control.md")


@pytest.mark.parametrize(
    "example", sorted(path.stem for path in (ROOT / "examples").glob("*.py"))
)
def test_example_is_documented(example: str) -> None:
    assert f'examples/{example}.py"' in page("examples.md")


def test_every_page_is_in_the_navigation() -> None:
    nav = (ROOT / "docs" / "mkdocs.yml").read_text("utf-8")
    pages = {
        path.relative_to(CONTENT).as_posix() for path in CONTENT.rglob("*.md")
    }

    assert {name for name in pages if f": {name}" not in nav} == set()
