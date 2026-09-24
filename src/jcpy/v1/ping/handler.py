"""Liveness probe: ``GET /ping``."""

from typing import Literal

from pydantic import BaseModel


class PingResponse(BaseModel):
    """Liveness probe response: always ``{"success": true}``."""

    success: Literal[True] = True
