"""FastAPI application factory."""

from fastapi import APIRouter, FastAPI

from jcpy.v1.ping.handler import PingResponse, ping_handler


def create_router() -> APIRouter:
    """Build the connector router.

    Returns:
        Router with all connector endpoints, ready to be included
        into a FastAPI application.
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
    """Build a standalone connector application.

    Returns:
        FastAPI application with the connector router mounted at ``/``.
    """
    app = FastAPI(title="Jodit Connector")
    app.include_router(create_router())
    return app
