"""Tenant source cache."""

from jcpy.config.loader import build_config
from jcpy.config.models import SourceConfig
from jcpy.tenants import ResolvedSources, TenantCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def tenant(tenant_id: str) -> ResolvedSources:
    return ResolvedSources(
        tenant_id,
        {
            "files": {
                "title": tenant_id,
                "root": f"/srv/{tenant_id}",
                "baseurl": f"http://cdn/{tenant_id}/",
            }
        },
    )


def cache(max_size: int = 2, ttl_ms: int = 1000) -> tuple[TenantCache, Clock]:
    clock = Clock()
    config = build_config(
        {"dynamicSourcesCache": {"max": max_size, "ttlMs": ttl_ms}}
    )
    return TenantCache(config, clock=clock), clock


def test_same_id_reuses_the_pool() -> None:
    tenants, _ = cache()

    first = tenants.get(tenant("a"))

    assert tenants.get(tenant("a")) is first
    assert first.settings["files"].name == "files"
    assert first.settings["files"].title == "a"


def test_expired_entry_is_rebuilt() -> None:
    tenants, clock = cache(ttl_ms=1000)
    first = tenants.get(tenant("a"))

    clock.now = 1.0

    assert tenants.get(tenant("a")) is not first


def test_least_recently_used_is_evicted() -> None:
    tenants, _ = cache(max_size=2)
    a = tenants.get(tenant("a"))
    tenants.get(tenant("b"))
    tenants.get(tenant("a"))

    tenants.get(tenant("c"))

    assert len(tenants) == 2
    assert tenants.get(tenant("a")) is a


def test_expired_entries_are_dropped_on_insert() -> None:
    tenants, clock = cache(max_size=10, ttl_ms=1000)
    tenants.get(tenant("a"))
    clock.now = 0.5
    tenants.get(tenant("b"))
    clock.now = 1.2

    tenants.get(tenant("c"))

    assert len(tenants) == 2


def test_models_are_accepted_and_clear_drops_everything() -> None:
    tenants, _ = cache()
    model = SourceConfig.model_validate(
        {"name": "x", "title": "X", "root": "/x", "baseurl": "http://x/"}
    )

    pool = tenants.get(ResolvedSources("m", {"files": model}))
    tenants.clear()

    assert pool.settings["files"] is model
    assert len(tenants) == 0
