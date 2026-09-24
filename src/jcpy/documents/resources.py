"""Loading of resources referenced by HTML documents."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from jcpy.helpers import ssrf
from jcpy.helpers.js import parse_bytes

if TYPE_CHECKING:
    from jcpy.config.models import AppConfig

_REMOTE_SCHEMES = frozenset({"http", "https"})


class ResourceRefusedError(ValueError):
    """A resource must not be loaded."""


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """How remote resources of a document may be loaded.

    Attributes:
        remote: Whether ``http``/``https`` resources are loaded at all.
        guard: Apply the SSRF checks of remote uploads.
        limit: Maximum size of one resource in bytes.
        timeout: Network timeout in seconds.
    """

    remote: bool
    guard: bool
    limit: int | None
    timeout: float

    @classmethod
    def from_config(cls, config: AppConfig) -> ResourcePolicy:
        """Derive the policy from the connector settings.

        ``pdf.isRemoteEnabled`` switches remote resources on and off,
        ``allowPrivateNetworkUploads`` lifts the SSRF checks,
        ``maxFileSize`` caps each resource, ``timeoutLimit`` bounds the
        network time.

        Args:
            config: Connector configuration.

        Returns:
            Policy.
        """
        limit = (
            parse_bytes(config.max_file_size) if config.max_file_size else None
        )
        return cls(
            remote=config.pdf.is_remote_enabled,
            guard=not config.allow_private_network_uploads,
            limit=limit,
            timeout=config.timeout_limit,
        )


def is_remote(url: str) -> bool:
    """Tell whether a URL is fetched over the network.

    Args:
        url: Resource URL.

    Returns:
        ``True`` for ``http`` and ``https`` URLs.
    """
    return url.partition(":")[0].lower() in _REMOTE_SCHEMES


async def load_remote(url: str, policy: ResourcePolicy) -> ssrf.Fetched:
    """Download a remote resource under the policy.

    Args:
        url: ``http``/``https`` URL.
        policy: Loading policy.

    Returns:
        Downloaded resource.

    Raises:
        ResourceRefusedError: Remote resources are disabled or the URL
            is not ``http``/``https``.
        HttpError: The SSRF checks refused the URL or the download
            failed.
    """
    if not policy.remote:
        msg = f"Remote resources are disabled: {url}"
        raise ResourceRefusedError(msg)
    if not is_remote(url):
        msg = f"Only http and https resources are allowed: {url}"
        raise ResourceRefusedError(msg)
    return await ssrf.fetch(
        url,
        guard=policy.guard,
        limit=policy.limit,
        network_timeout=policy.timeout,
    )
