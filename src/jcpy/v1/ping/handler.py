"""Liveness probe: ``GET /ping``."""

from typing import Literal

from pydantic import BaseModel


class PingResponse(BaseModel):
    """Service is running."""

    success: Literal[True] = True


async def ping_handler() -> PingResponse:
    """Answer the liveness probe."""
    return PingResponse()
