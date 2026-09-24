"""Sources picked per request (one set of folders per tenant).

The tenant comes from the ``X-Tenant`` header; in a real application
it would come from the authenticated user, and the settings from a
database. Requests without a tenant use the configured ``shared``
source. Built sources are cached per tenant id (see
``dynamicSourcesCache``); putting the settings version into the id
rebuilds them after a change.

Run from the repository root::

    uv run python examples/multi_tenant.py
    curl -H "X-Tenant: acme" "http://localhost:8081/?action=files"
"""

from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from jcpy import HttpError, ResolvedSources, create_app

CONFIG = Path(__file__).parent / "config" / "tenants.json"


@dataclass(frozen=True, slots=True)
class Tenant:
    """Stored tenant settings.

    Attributes:
        title: Title of the tenant's source.
        version: Changes whenever the settings change.
    """

    title: str
    version: int


TENANTS = {
    "acme": Tenant("ACME files", 1),
    "globex": Tenant("Globex files", 3),
}


# --8<-- [start:build]
def tenant_sources(request: Request) -> ResolvedSources | None:
    """Pick the sources of the request's tenant.

    Args:
        request: Incoming request.

    Returns:
        Tenant sources, ``None`` for requests without a tenant.

    Raises:
        HttpError: ``403`` for an unknown tenant.
    """
    name = request.headers.get("x-tenant")
    if name is None:
        return None
    tenant = TENANTS.get(name)
    if tenant is None:
        raise HttpError.forbidden("Unknown tenant")
    return ResolvedSources(
        id=f"{name}:{tenant.version}",
        sources={
            "files": {
                "title": tenant.title,
                "root": f"./files/tenants/{name}",
                "baseurl": f"http://localhost:8080/files/tenants/{name}/",
            }
        },
    )


def build_app() -> FastAPI:
    """Build the application.

    Returns:
        Connector application with per-tenant sources.
    """
    return create_app(CONFIG, resolve_sources=tenant_sources)


# --8<-- [end:build]

if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8081)
