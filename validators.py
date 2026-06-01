"""URL validation and SSRF prevention utilities."""

import ipaddress
import socket
from urllib.parse import urlparse


def _resolve_host(host: str) -> list[str]:
    """Resolve *host* to IP address strings via DNS. Returns ``[]`` on any failure."""
    try:
        return [sockaddr[0] for *_, sockaddr in socket.getaddrinfo(host, None)]
    except socket.gaierror:
        return []


def is_private_url(url: str) -> bool:
    """Return True when *url* resolves to a private / reserved host (SSRF guard).

    Uses :mod:`ipaddress` for IP-literal hostnames, covering all private,
    loopback, link-local, reserved, and IPv4-mapped IPv6 addresses.
    Non-IP hostnames are resolved via DNS; if any resolved address is private
    the URL is blocked.  DNS failures are treated as non-private (fail-open)
    to avoid false positives on temporarily unreachable hosts.
    """
    try:
        host: str = urlparse(url).hostname or ''
    except ValueError:
        return True
    if not host:
        return True
    if host.lower() == 'localhost':
        return True
    try:
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(host)
    except ValueError:
        # Non-IP hostname — resolve via DNS to catch DNS-rebinding attacks.
        for ip_str in _resolve_host(host):
            try:
                resolved: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if isinstance(resolved, ipaddress.IPv6Address) and resolved.ipv4_mapped is not None:
                resolved = resolved.ipv4_mapped
            if (
                resolved.is_loopback
                or resolved.is_private
                or resolved.is_link_local
                or resolved.is_reserved
                or resolved.is_unspecified
            ):
                return True
        return False
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) so the IPv4 checks apply.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )
