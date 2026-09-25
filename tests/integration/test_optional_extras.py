"""The core works without extras; their actions answer 501."""

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.conftest import source_config, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from jcpy.types import JsonObject
    from tests.conftest import ClientFactory

OPTIONAL = (
    "weasyprint",
    "boto3",
    "botocore",
    "docx",
    "html4docx",
    "bs4",
    "paramiko",
)


def test_importing_the_package_loads_no_extra() -> None:
    code = (
        "import sys, jcpy, jcpy.app; "
        f"print(sorted(m for m in {OPTIONAL!r} if m in sys.modules))"
    )
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    ("module", "action", "extra"),
    [
        ("jcpy.documents.pdf", "generatePdf", "pdf"),
        ("jcpy.documents.docx", "generateDocx", "docx"),
    ],
)
async def test_document_actions_without_their_extra(
    connector_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    action: str,
    extra: str,
) -> None:
    monkeypatch.setitem(sys.modules, module, None)

    async with connector_client() as http:
        response = await http.get(f"/{action}", params={"html": "<p>x</p>"})
        invalid = await http.get(f"/{action}")

    assert response.status_code == 501
    assert response.json()["data"]["messages"] == [
        f"{action} requires the {extra} extra: "
        f"pip install 'jodit-python[{extra}]'"
    ]
    # Parameters are still validated first.
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    ("adapter", "options"),
    [
        ("s3", {"bucket": "b"}),
        ("sftp", {"host": "localhost", "username": "u"}),
    ],
)
async def test_storage_without_its_extra(
    connector_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    adapter: str,
    options: JsonObject,
) -> None:
    monkeypatch.setitem(sys.modules, f"jcpy.storage.{adapter}", None)
    write_file(tmp_path, "a.txt", "a")
    local_source = source_config(tmp_path)["sources"]
    assert isinstance(local_source, dict)
    config: JsonObject = {
        "sources": {
            **local_source,
            "bucket": {
                "title": "Bucket",
                "baseurl": "http://localhost/bucket/",
                "storageAdapter": adapter,
                adapter: options,
            },
        }
    }

    async with connector_client(config) as http:
        local = await http.get("/files", params={"source": "test"})
        bucket = await http.get("/files", params={"source": "bucket"})

    assert local.status_code == 200
    assert bucket.status_code == 501
    assert f"jodit-python[{adapter}]" in bucket.json()["data"]["messages"][0]
