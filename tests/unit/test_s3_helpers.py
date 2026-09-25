"""S3 key handling and public URLs, ported from jodit-nodejs s3.test.ts."""

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from jcpy.config.models import S3Options, SourceConfig
from jcpy.errors import HttpError
from jcpy.storage import create_storage_adapter
from jcpy.storage.s3 import (
    S3StorageAdapter,
    build_object_key,
    default_public_base_url,
    normalize_s3_path,
    strip_object_prefix,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", ""),
        ("/", ""),
        ("a/b", "a/b"),
        ("/a//b/", "a/b"),
        ("a\\b\\c", "a/b/c"),
        ("./a/./b", "a/b"),
    ],
)
def test_normalize_s3_path(path: str, expected: str) -> None:
    assert normalize_s3_path(path) == expected


def test_build_object_key() -> None:
    assert build_object_key("", "a/b") == "a/b"
    assert build_object_key("media/", "/a.png") == "media/a.png"
    assert build_object_key("/media/", "") == "media"


def test_strip_object_prefix() -> None:
    assert strip_object_prefix("", "/a/b") == "a/b"
    assert strip_object_prefix("media", "media") == ""
    assert strip_object_prefix("media", "media/a/b.png") == "a/b.png"
    # A sibling key sharing the start must not be mistaken for the prefix
    assert strip_object_prefix("media", "media-2/x") == "media-2/x"


def options(**values: object) -> S3Options:
    return S3Options.model_validate({"bucket": "my-bucket", **values})


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {"region": "eu-central-1", "prefix": "media"},
            "https://my-bucket.s3.eu-central-1.amazonaws.com/media",
        ),
        ({}, "https://my-bucket.s3.us-east-1.amazonaws.com"),
        (
            {"endpoint": "http://localhost:9000/", "forcePathStyle": True},
            "http://localhost:9000/my-bucket",
        ),
        (
            {"endpoint": "https://storage.yandexcloud.net", "prefix": "a"},
            "https://my-bucket.storage.yandexcloud.net/a",
        ),
    ],
)
def test_default_public_base_url(
    values: dict[str, object], expected: str
) -> None:
    assert default_public_base_url(options(**values)) == expected


def test_public_url_prefers_explicit_base() -> None:
    adapter = S3StorageAdapter(
        options(
            publicBaseUrl="https://cdn.example.com/files/",
            credentials={"accessKeyId": "k", "secretAccessKey": "s"},
        )
    )

    assert adapter.public_url("") == "https://cdn.example.com/files"
    assert adapter.public_url("/a/b.png") == (
        "https://cdn.example.com/files/a/b.png"
    )


def setting(config: object, name: str) -> object:
    """Read a botocore ``Config`` value (set dynamically, untyped)."""
    return getattr(config, name)


def test_client_settings() -> None:
    adapter = S3StorageAdapter(
        options(
            region="eu-west-1",
            endpoint="http://minio:9000",
            forcePathStyle=True,
            credentials={
                "accessKeyId": "k",
                "secretAccessKey": "s",
                "sessionToken": "t",
            },
        )
    )

    client_config = adapter.client.meta.config
    assert adapter.client.meta.region_name == "eu-west-1"
    assert adapter.client.meta.endpoint_url == "http://minio:9000"
    assert getattr(client_config, "s3") == {"addressing_style": "path"}  # noqa: B009
    assert setting(client_config, "connect_timeout") == 10
    assert setting(client_config, "read_timeout") == 60
    assert setting(client_config, "retries") == {
        "total_max_attempts": 3,
        "mode": "standard",
    }


def test_timeouts_and_retries_are_configurable() -> None:
    adapter = S3StorageAdapter(
        options(connectTimeout=2.5, readTimeout=30, maxAttempts=5)
    )

    client_config = adapter.client.meta.config
    assert setting(client_config, "connect_timeout") == 2.5
    assert setting(client_config, "read_timeout") == 30
    assert setting(client_config, "retries") == {
        "total_max_attempts": 5,
        "mode": "standard",
    }


def stubbed(**values: object) -> tuple[S3StorageAdapter, Stubber]:
    adapter = S3StorageAdapter(
        options(
            prefix="media",
            credentials={"accessKeyId": "k", "secretAccessKey": "s"},
            **values,
        )
    )
    stubber = Stubber(adapter.client)
    stubber.activate()
    return adapter, stubber


def test_default_credential_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_client(service: str, **kwargs: object) -> object:
        calls.append({"service": service, **kwargs})
        return object()

    monkeypatch.setattr("boto3.client", fake_client)

    S3StorageAdapter(options())

    (call,) = calls
    assert call["service"] == "s3"
    assert call["region_name"] == "us-east-1"
    # No keys passed: boto3 falls back to the default credential chain.
    assert not {"aws_access_key_id", "aws_secret_access_key"} & set(call)


async def test_root_needs_no_marker() -> None:
    adapter, stubber = stubbed()

    await adapter.create_directory("/")

    stubber.assert_no_pending_responses()


@pytest.mark.parametrize("method", ["stat", "file_exists"])
async def test_access_errors_are_not_hidden(method: str) -> None:
    adapter, stubber = stubbed()
    stubber.add_client_error(
        "head_object", service_error_code="403", http_status_code=403
    )

    with pytest.raises(ClientError):
        await getattr(adapter, method)("a.txt")


async def test_listing_skips_the_folder_itself() -> None:
    adapter, stubber = stubbed()
    stubber.add_response(
        "list_objects_v2",
        {
            "CommonPrefixes": [
                {"Prefix": "media/dir/"},
                {"Prefix": "media/dir/x/"},
            ],
            "Contents": [
                {"Key": "media/dir/"},
                {"Key": "media/dir/a.txt", "Size": 3},
            ],
            "IsTruncated": False,
        },
        {"Bucket": "my-bucket", "Prefix": "media/dir/", "Delimiter": "/"},
    )

    entries = [entry async for entry in adapter.list("dir", deep=False)]

    assert [(e.path, e.is_file) for e in entries] == [
        ("dir/x", False),
        ("dir/a.txt", True),
    ]


async def test_delete_directory_in_batches() -> None:
    adapter, stubber = stubbed()
    for keys, truncated in ((["media/d/1", "media/d/2"], True), ([], False)):
        stubber.add_response(
            "list_objects_v2",
            {
                "Contents": [{"Key": key} for key in keys],
                "IsTruncated": truncated,
            },
            {"Bucket": "my-bucket", "Prefix": "media/d/", "MaxKeys": 1000},
        )
        if keys:
            stubber.add_response(
                "delete_objects",
                {},
                {
                    "Bucket": "my-bucket",
                    "Delete": {
                        "Objects": [{"Key": key} for key in keys],
                        "Quiet": True,
                    },
                },
            )

    await adapter.delete_directory("d")

    stubber.assert_no_pending_responses()


async def test_delete_directory_reports_failed_objects() -> None:
    adapter, stubber = stubbed()
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "media/d/1"}, {"Key": "media/d/2"}]},
        {"Bucket": "my-bucket", "Prefix": "media/d/", "MaxKeys": 1000},
    )
    stubber.add_response(
        "delete_objects",
        {
            "Errors": [
                {
                    "Key": "media/d/2",
                    "Code": "AccessDenied",
                    "Message": "Access Denied",
                }
            ]
        },
        {
            "Bucket": "my-bucket",
            "Delete": {
                "Objects": [{"Key": "media/d/1"}, {"Key": "media/d/2"}],
                "Quiet": True,
            },
        },
    )

    with pytest.raises(OSError, match=r"1 object\(s\) could not be deleted"):
        await adapter.delete_directory("d")

    stubber.assert_no_pending_responses()


async def test_delete_error_without_details() -> None:
    adapter, stubber = stubbed()
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "media/d/1"}]},
        {"Bucket": "my-bucket", "Prefix": "media/d/", "MaxKeys": 1000},
    )
    stubber.add_response(
        "delete_objects",
        {"Errors": [{}]},
        {
            "Bucket": "my-bucket",
            "Delete": {"Objects": [{"Key": "media/d/1"}], "Quiet": True},
        },
    )

    with pytest.raises(OSError, match=r"could not be deleted, e\.g\. : $"):
        await adapter.delete_directory("d")


def test_s3_source_needs_options() -> None:
    settings = SourceConfig.model_construct(
        name="s", title="S", baseurl="http://s/", storage_adapter="s3"
    )

    with pytest.raises(HttpError, match='needs an "s3" options block'):
        create_storage_adapter(settings)
