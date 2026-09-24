---
title: Dynamic Sources (multi-tenant)
description: Picking the sources of each request, for one connector serving many tenants.
---

# Dynamic Sources (multi-tenant)

One connector instance can serve many tenants (customers, users,
projects), each with its own folders or bucket: the `resolve_sources`
callback picks the sources of every request.

Compare with [several instances](integration.md#5-several-instances):
instances are a fixed set with different configurations and
authentication; dynamic sources are an open set of tenants sharing one
configuration, resolved at runtime (from a database, for instance).

## How it works

1. A request arrives. After `onlyPOST` and CORS, and **before
   authentication**, the connector calls `resolve_sources(request)`.
2. The callback returns `ResolvedSources(id=..., sources=...)`, or
   `None`.
3. With sources, the connector builds them (or reuses those built for
   the same `id`) and the whole request sees only them: `files`,
   `fileUpload`, `folderCreate`...
4. With `None`, the static `sources` of the configuration apply.

Returned sources have the shape of `sources` in the configuration
(`title`, `baseurl`, `root` or `storageAdapter` + `s3`...), as dicts or
`SourceConfig` models, with [per-source overrides](config.md#per-source-overrides)
allowed. They are validated like the configuration; invalid settings
fail the request with `500`.

## Example: tenant from a header

```python
--8<-- "examples/multi_tenant.py:build"
```

Full program: [`examples/multi_tenant.py`](examples.md#multi-tenant).

A tenant in a bucket of its own:

```python
from starlette.requests import Request

from jcpy import ResolvedSources


async def tenant_sources(request: Request) -> ResolvedSources | None:
    tenant = await find_tenant(request.headers.get("x-tenant-id"))
    if tenant is None:
        return None
    return ResolvedSources(
        # Anything that should rebuild the sources when it changes.
        id=f"{tenant.id}:{tenant.updated_at.isoformat()}",
        sources={
            "files": {
                "title": tenant.name,
                "baseurl": tenant.public_url,
                "storageAdapter": "s3",
                "s3": {
                    "bucket": tenant.bucket,
                    "region": tenant.region,
                    "prefix": tenant.prefix,
                    "credentials": {
                        "accessKeyId": tenant.key_id,
                        "secretAccessKey": tenant.secret,
                    },
                },
            }
        },
    )
```

Any part of the request can identify the tenant: a header, a cookie, a
subdomain, a query parameter, a JWT claim.

## Caching

Built sources are cached by `id`:

- same `id` within the TTL: the resolver still runs (it is part of your
  authorization), but the built sources are reused;
- a new `id`, or an expired entry: the sources are built again;
- when the cache is full the least recently used tenants go first.

Limits come from [`dynamicSourcesCache`](config.md#dynamicSourcesCache)
(200 tenants, 60 s by default):

```json
{"dynamicSourcesCache": {"max": 1000, "ttlMs": 300000}}
```

Put a version into the `id` (an `updated_at` timestamp, a hash of the
settings) so that changed credentials apply on the next request rather
than after the TTL. To drop every tenant at once, keep the `Connector`
and call `connector.clear_dynamic_sources()`
([Python API](usage.md#connector)).

## Authentication and roles

`resolve_sources` runs before `check_authentication` and both get the
same request, so the resolver can leave the tenant on `request.state`
for the authentication callback:

```python
from http import HTTPStatus

from starlette.requests import Request

from jcpy import HttpError, ResolvedSources, create_app


async def tenant_sources(request: Request) -> ResolvedSources | None:
    tenant = await find_tenant_by_api_key(request.query_params.get("key"))
    if tenant is None:
        return None
    request.state.tenant = tenant
    return ResolvedSources(id=tenant.id, sources=tenant.sources)


async def role(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HttpError(HTTPStatus.UNAUTHORIZED, "Unknown tenant")
    return await verify_user_token(request, tenant.jwt_secret)


app = create_app(
    "config.json", resolve_sources=tenant_sources, check_authentication=role
)
```

Roles then go through the usual [access rules](access-control.md);
usually one role matrix (`viewer`, `editor`, `admin`) serves every
tenant and the tenant decides which role a user gets.

## CORS per tenant

With `allowCrossOrigin` on, every origin is accepted unless restricted.
`allowed_origins=` takes a predicate that sees the request, so it can
consult the tenant:

```python
from urllib.parse import urlsplit

from starlette.requests import Request


async def tenant_origin(origin: str, request: Request) -> bool:
    tenant = await find_tenant_by_api_key(request.query_params.get("key"))
    return tenant is not None and urlsplit(origin).hostname in tenant.domains


app = create_app("config.json", allowed_origins=tenant_origin)
```

CORS runs before `resolve_sources`, so the predicate does its own
lookup. Preflights from other origins get `403` and no CORS headers.

## Falling back to static sources

`None` from the resolver means "not a tenant request" and the static
`sources` apply, so one instance can serve a shared source and tenant
sources together. For a tenants-only instance set `"sources": {}`: then
requests the resolver declines have no sources: listings come back
empty, `permissions` reports everything as denied, and other actions
answer `404 Source not found`.

## Reference

```python
@dataclass(frozen=True)
class ResolvedSources:
    id: str  # cache key; change it to rebuild
    sources: Mapping[str, SourceConfig | Mapping[str, Any]]


type SourcesResolver = Callable[
    [Request], ResolvedSources | None | Awaitable[ResolvedSources | None]
]
```
