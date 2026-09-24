"""Standalone entry point."""

from unittest.mock import MagicMock

import pytest

from jcpy import run


def test_get_port_defaults_to_8081(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PORT", raising=False)

    assert run.get_port() == 8081


def test_get_port_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9000")

    assert run.get_port() == 9000


@pytest.mark.parametrize("value", ["abc", "0", "65536", "-1"])
def test_get_port_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PORT", value)

    with pytest.raises(SystemExit, match="Invalid PORT"):
        run.get_port()


def test_main_starts_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    uvicorn_run = MagicMock()
    monkeypatch.setattr("uvicorn.run", uvicorn_run)
    monkeypatch.setenv("PORT", "8082")
    monkeypatch.setenv("HOST", "127.0.0.1")

    run.main()

    uvicorn_run.assert_called_once_with(
        "jcpy.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8082,
    )
