"""Configuration defaults, loading and validation."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from jcpy.config.loader import build_config, load_config, read_user_config
from jcpy.config.models import AccessControlRule, AppConfig
from jcpy.errors import ConfigError

if TYPE_CHECKING:
    from jcpy.types import JsonObject

SOURCE: JsonObject = {
    "title": "A",
    "root": "/srv/a",
    "baseurl": "http://files/a/",
}


def test_defaults_match_jodit_nodejs() -> None:
    config = build_config({})

    assert config.debug is True
    assert config.default_role == "guest"
    assert config.only_post is False
    assert config.allow_cross_origin is False
    assert config.datetime_format == "M/D/YYYY h:mm:ss A"
    assert config.default_permission == 0o775
    assert config.thumb_folder_name == "_thumbs"
    assert config.max_upload_file_size == "8mb"
    assert "webp" in config.extensions
    assert config.pdf.paper.format == "A4"
    assert config.dynamic_sources_cache.ttl_ms == 60_000
    assert config.access_control == []


def test_default_source_uses_working_directory() -> None:
    source = build_config({}).sources["default"]

    assert source.name == "default"
    assert source.title == "Test Files"
    assert source.root == str(Path.cwd() / "files")
    assert source.baseurl == "http://localhost:8081/files/"


def test_default_source_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("SOURCE_NAME", "Uploads")
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    source = build_config({}).sources["default"]

    assert source.title == "Uploads"
    assert source.root == str(tmp_path.resolve())
    assert source.baseurl == "http://localhost:9000/files/"

    monkeypatch.setenv("SOURCE_BASEURL", "https://cdn.example/f/")

    assert build_config({}).sources["default"].baseurl == (
        "https://cdn.example/f/"
    )


def test_user_values_override_defaults() -> None:
    config = build_config(
        {
            "onlyPOST": True,
            "extensions": ["jpg"],
            "pdf": {"paper": {"format": "A3"}},
            "quality": None,
        }
    )

    assert config.only_post is True
    assert config.extensions == ["jpg"]
    assert config.pdf.paper.format == "A3"
    assert config.pdf.paper.page_orientation == "portrait"
    assert config.quality == 90


def test_user_sources_replace_default_source() -> None:
    config = build_config({"sources": {"media": SOURCE}})

    assert list(config.sources) == ["media"]
    assert config.sources["media"].name == "media"


def test_explicit_source_name_is_kept() -> None:
    config = build_config({"sources": {"m": {**SOURCE, "name": "media"}}})

    assert config.sources["m"].name == "media"


def test_source_overrides_global_settings() -> None:
    config = build_config(
        {
            "maxFileSize": "2mb",
            "sources": {
                "a": {**SOURCE, "maxFileSize": "1mb", "createThumb": False},
                "b": {**SOURCE, "title": "B"},
            },
        }
    )

    a = config.for_source("a")
    assert a.max_file_size == "1mb"
    assert a.create_thumb is False
    assert a.root == "/srv/a"
    assert a.baseurl == "http://files/a/"
    assert a.title == "A"
    assert a.sources == {}
    assert config.for_source("b").max_file_size == "2mb"
    assert config.max_file_size == "2mb"


def test_source_without_overrides_returns_same_config() -> None:
    config = build_config({"sources": {"a": SOURCE}})

    assert config.sources["a"].overrides()["root"] == "/srv/a"


def test_access_control_rules() -> None:
    config = build_config(
        {
            "accessControl": [
                {"role": "guest", "FILES": True, "FILE_UPLOAD": False},
                {"role": "*", "extensions": "jpg, png", "path": "/img"},
            ]
        }
    )

    first, second = config.access_control
    assert first.actions == {"FILES": True, "FILE_UPLOAD": False}
    assert second.extensions == "jpg, png"
    assert second.actions == {}


def test_access_control_rule_without_extras() -> None:
    assert AccessControlRule().actions == {}


def test_s3_source() -> None:
    config = build_config(
        {
            "sources": {
                "media": {
                    "title": "Media",
                    "baseurl": "https://bucket.example/media/",
                    "storageAdapter": "s3",
                    "s3": {
                        "bucket": "bucket",
                        "endpoint": "http://minio:9000",
                        "forcePathStyle": True,
                        "credentials": {
                            "accessKeyId": "id",
                            "secretAccessKey": "secret",
                        },
                    },
                }
            }
        }
    )

    source = config.sources["media"]
    assert source.is_local is False
    assert source.s3 is not None
    assert source.s3.force_path_style is True
    assert source.s3.credentials is not None
    assert source.s3.credentials.access_key_id == "id"


@pytest.mark.parametrize(
    ("user", "message"),
    [
        ({"unknownKey": 1}, "unknownKey: Extra inputs are not permitted"),
        ({"max_file_size": "1mb"}, "max_file_size: Extra inputs"),
        ({"quality": "high"}, "quality: Input should be a valid integer"),
        (
            {"sources": {"a": {**SOURCE, "baseurl": "files"}}},
            "sources.a.baseurl",
        ),
        (
            {"sources": {"a": {"title": "A", "baseurl": "http://x/"}}},
            "root is required for local storage",
        ),
        (
            {
                "sources": {
                    "a": {
                        "title": "A",
                        "baseurl": "http://x/",
                        "storageAdapter": "s3",
                    }
                }
            },
            's3 options are required for storageAdapter "s3"',
        ),
        (
            {"sources": {"a": {**SOURCE, "bogus": 1}}},
            "unknown settings: bogus",
        ),
        (
            {"sources": {"a": {**SOURCE, "quality": "x"}}},
            "source 'a' overrides: quality",
        ),
        (
            {"accessControl": [{"role": "x", "FILES": "yes"}]},
            "action 'FILES' must be true or false",
        ),
        (
            {"dynamicSourcesCache": {"max": 0}},
            "dynamicSourcesCache.max",
        ),
        (
            {
                "sources": {
                    "a": {
                        "title": "A",
                        "baseurl": "http://x/",
                        "storageAdapter": "s3",
                        "s3": {"bucket": "b", "endpoint": "minio"},
                    }
                }
            },
            "sources.a.s3.endpoint",
        ),
    ],
)
def test_invalid_config(user: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match="Invalid connector config") as info:
        build_config(user)  # type: ignore[arg-type]

    assert message in str(info.value)


def test_read_user_config_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"title": "explicit"}))
    from_env = tmp_path / "env.json"
    from_env.write_text(json.dumps({"title": "file"}))

    assert read_user_config() == {}

    monkeypatch.setenv("CONFIG_FILE", str(from_env))
    assert read_user_config() == {"title": "file"}

    monkeypatch.setenv("CONFIG", '{"title": "inline"}')
    assert read_user_config() == {"title": "inline"}

    assert read_user_config(explicit) == {"title": "explicit"}


def test_load_config_from_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"onlyPOST": True}))

    assert load_config(path).only_post is True
    assert load_config(str(path)).only_post is True


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{broken", "Invalid JSON in"),
        ("[1, 2]", "must contain a JSON object"),
    ],
)
def test_malformed_config_file(
    tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "config.json"
    path.write_text(content)

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(tmp_path / "missing.json")


def test_malformed_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIG", "nope")

    with pytest.raises(ConfigError, match="CONFIG environment variable"):
        load_config()


def test_models_are_immutable() -> None:
    config = AppConfig()

    with pytest.raises(ValueError, match="frozen"):
        config.debug = False  # type: ignore[misc]
