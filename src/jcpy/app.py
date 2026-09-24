"""FastAPI application factory."""

from fastapi import APIRouter, FastAPI

from jcpy.v1.ping.handler import PingResponse, ping_handler


def create_router() -> APIRouter:
    """Build the connector router.

    The liveness probe is registered first so it answers before CORS,
    tenant resolution and authentication.
    """
    router = APIRouter()
    router.add_api_route(
        "/ping",
        ping_handler,
        methods=["GET"],
        response_model=PingResponse,
        summary="Liveness probe",
    )
    return router


def create_app() -> FastAPI:
    """Build a standalone connector application."""
    app = FastAPI(title="Jodit Connector")
    app.include_router(create_router())
    return app
