"""Per-request sources for multi-tenant setups."""

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jcpy.config.models import SourceConfig
from jcpy.helpers.svg_icon import generate_icon
from jcpy.sources import SourcePool

if TYPE_CHECKING:
    from starlette.requests import Request

    from jcpy.config.models import AppConfig
    from jcpy.helpers.svg_icon import SvgGenerator


@dataclass(frozen=True, slots=True)
class ResolvedSources:
    """Sources of one tenant.

    Attributes:
        id: Cache key of the tenant; include a version marker (e.g. an
            ``updatedAt`` timestamp) to rebuild after settings change.
        sources: Source settings by name, as models or JSON-like dicts
            with the ``sources`` item shape of the configuration.
    """

    id: str
    sources: Mapping[str, SourceConfig | Mapping[str, Any]]


type SourcesResolver = Callable[
    [Request], ResolvedSources | Awaitable[ResolvedSources | None] | None
]
"""Pick the sources of a request; ``None`` falls back to static ones."""


@dataclass(slots=True)
class _Entry:
    expires_at: float
    pool: SourcePool


def _settings(
    name: str, value: SourceConfig | Mapping[str, Any]
) -> SourceConfig:
    if isinstance(value, SourceConfig):
        return value
    return SourceConfig.model_validate({"name": name, **value})


class TenantCache:
    """Built tenant sources, reused by id (LRU with expiry).

    Args:
        config: Instance configuration (``dynamicSourcesCache`` limits).
        svg_generator: Icon renderer for the built sources.
        clock: Monotonic time in seconds.
    """

    def __init__(
        self,
        config: AppConfig,
        svg_generator: SvgGenerator = generate_icon,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.svg_generator = svg_generator
        self.clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, resolved: ResolvedSources) -> SourcePool:
        """Return the sources of a tenant, building them when needed.

        A live entry is reused and becomes the most recent one. A new
        entry evicts expired ones and, beyond ``max``, the least
        recently used ones; the entry just built is always kept.

        Args:
            resolved: Tenant id and sources.

        Returns:
            Source pool of the tenant.
        """
        now = self.clock()
        cached = self._entries.get(resolved.id)
        if cached is not None and cached.expires_at > now:
            self._entries.move_to_end(resolved.id)
            return cached.pool

        limits = self.config.dynamic_sources_cache
        pool = SourcePool(
            self.config,
            {
                name: _settings(name, value)
                for name, value in resolved.sources.items()
            },
            svg_generator=self.svg_generator,
        )
        self._entries.pop(resolved.id, None)
        self._entries[resolved.id] = _Entry(now + limits.ttl_ms / 1000, pool)

        others = [key for key in self._entries if key != resolved.id]
        for key in others:
            entry = self._entries[key]
            if len(self._entries) > limits.max or entry.expires_at <= now:
                del self._entries[key]
        return pool

    def clear(self) -> None:
        """Drop every cached tenant."""
        self._entries.clear()
