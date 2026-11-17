"""Zero-dependency HTTPX process-environment compatibility shims."""

from .no_proxy import no_proxy_ipv6_guard

__all__ = ["no_proxy_ipv6_guard"]
