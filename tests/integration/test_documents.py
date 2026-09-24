"""``generatePdf`` and ``generateDocx`` actions."""

from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from docx import Document
from pypdf import PdfReader

from jcpy.documents import docx as docx_module
from jcpy.documents import pdf as pdf_module
from jcpy.v1.generate_docx import handler as docx_handler

if TYPE_CHECKING:
    from tests.conftest import ClientFactory


async def test_generate_pdf(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/",
            data={
                "action": "generatePdf",
                "html": "<h1>Отчёт</h1><p>text</p>",
                "options[format]": "A3",
                "options[page_orientation]": "landscape",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="document.pdf"'
    )
    assert response.headers["content-length"] == str(len(response.content))
    page = PdfReader(BytesIO(response.content)).pages[0]
    assert round(float(page.mediabox.width)) == 1191
    assert "text" in page.extract_text()


async def test_generate_docx(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.get(
            "/generateDocx",
            params={"html": "<p>Hello <b>DOCX</b></p><script>x()</script>"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == docx_handler.DOCX_TYPE
    assert response.headers["content-disposition"] == (
        "attachment;filename=document.docx"
    )
    assert response.headers["expires"] == "0"
    assert response.headers["cache-control"] == (
        "must-revalidate, post-check=0, pre-check=0"
    )
    document = Document(BytesIO(response.content))
    assert [p.text for p in document.paragraphs] == ["Hello DOCX"]


@pytest.mark.parametrize("action", ["generatePdf", "generateDocx"])
@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "html: Invalid input: expected string, received undefined"),
        (
            {"html": ""},
            "html: Too small: expected string to have >=1 characters",
        ),
        ({"html": "   "}, "Need html parameter"),
    ],
)
async def test_bad_html(
    connector_client: ClientFactory,
    action: str,
    params: dict[str, str],
    message: str,
) -> None:
    async with connector_client() as http:
        response = await http.get(f"/{action}", params=params)

    assert response.status_code == 400
    assert response.json()["data"]["messages"] == [message]


async def test_pdf_options_validation(connector_client: ClientFactory) -> None:
    async with connector_client() as http:
        response = await http.get(
            "/generatePdf", params={"html": "x", "options[format]": "A5"}
        )

    assert response.json()["data"]["messages"] == ["options: Invalid input"]


@pytest.mark.parametrize(
    ("module", "function", "action", "message"),
    [
        (pdf_module, "html_to_pdf", "generatePdf", "Failed to generate PDF"),
        (
            docx_module,
            "html_to_docx",
            "generateDocx",
            "Failed to generate DOCX",
        ),
    ],
)
async def test_render_failures(
    connector_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    function: str,
    action: str,
    message: str,
) -> None:
    async def broken(*_: object) -> bytes:
        msg = "renderer crashed"
        raise RuntimeError(msg)

    monkeypatch.setattr(module, function, broken)
    async with connector_client() as http:
        response = await http.get(f"/{action}", params={"html": "<p>x</p>"})

    assert response.status_code == 500
    assert response.json()["data"]["messages"] == [message]


async def test_pdf_defaults_to_portrait(
    connector_client: ClientFactory,
) -> None:
    async with connector_client() as http:
        response = await http.post(
            "/generatePdf",
            json={"html": "<p>x</p>", "options": {"format": "Letter"}},
        )

    page = PdfReader(BytesIO(response.content)).pages[0]
    assert (
        round(float(page.mediabox.width)),
        round(float(page.mediabox.height)),
    ) == (612, 792)
