"""``errorHttpStatus``: errors sent with ``200``, as by the PHP connector."""

from typing import TYPE_CHECKING

import pytest

from tests.conftest import source_config

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient, Response

    from tests.conftest import ClientFactory


def envelope(response: Response) -> tuple[int, int, list[str]]:
    body = response.json()
    assert body["success"] is False
    data = body["data"]
    return response.status_code, data["code"], data["messages"]


async def upload_page(http: AsyncClient) -> Response:
    return await http.post(
        "/fileUpload", files={"files[0]": ("page.html", b"<p>x</p>")}
    )


async def test_errors_keep_their_status_by_default(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    async with connector_client(source_config(tmp_path)) as http:
        response = await upload_page(http)

    assert envelope(response) == (
        403,
        403,
        ["File type is not in white list"],
    )


@pytest.mark.parametrize(
    ("method", "url", "params", "code", "message"),
    [
        ("POST", "/fileUpload", {}, 403, "File type is not in white list"),
        ("GET", "/files", {"source": "nope"}, 404, "Source not found"),
        ("GET", "/unknown", {}, 404, 'Action "unknown" not found'),
        ("GET", "/folderCreate", {}, 400, None),
        ("GET", "/fail", {"kind": "boom"}, 500, "Boom"),
    ],
)
async def test_errors_are_sent_with_200_when_disabled(
    connector_client: ClientFactory,
    tmp_path: Path,
    method: str,
    url: str,
    params: dict[str, str],
    code: int,
    message: str | None,
) -> None:
    config = source_config(tmp_path, errorHttpStatus=False)
    async with connector_client(config) as http:
        if method == "POST":
            response = await upload_page(http)
        else:
            response = await http.get(url, params=params)

    status, data_code, messages = envelope(response)
    assert (status, data_code) == (200, code)
    assert messages
    if message is not None:
        assert messages == [message]
    assert not (tmp_path / "page.html").exists()


async def test_only_post_refusal_is_sent_with_200(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    config = source_config(tmp_path, errorHttpStatus=False, onlyPOST=True)
    async with connector_client(config) as http:
        action = await http.get("/files")
        ping = await http.get("/ping")

    assert envelope(action)[:2] == (200, 405)
    # The liveness probe is not a Jodit request: it keeps its status.
    assert ping.status_code == 405


async def test_successful_answers_are_unchanged(
    connector_client: ClientFactory, tmp_path: Path
) -> None:
    config = source_config(tmp_path, errorHttpStatus=False)
    async with connector_client(config) as http:
        response = await http.get("/files")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["code"] == 220
