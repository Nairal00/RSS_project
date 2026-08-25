"""URL validation and SSRF prevention utilities."""

import functools
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
import requests.exceptions

from config import CONTROL_CHARS


def is_http_url(url: str) -> bool:
    """Return True when *url* has an http or https scheme (case-insensitive)."""
    try:
        return urlparse(url).scheme.lower() in ('http', 'https')
    except ValueError:
        return False


def has_control_chars(url: str) -> bool:
    """Return True when *url* contains CR, LF, or NUL characters."""
    return any(c in url for c in CONTROL_CHARS)


@functools.lru_cache(maxsize=512)
def _resolve_host(host: str) -> list[str]:
    """Resolve *host* to IP address strings via DNS. Returns ``[]`` on any failure."""
    try:
        return [sockaddr[0] for *_, sockaddr in socket.getaddrinfo(host, None)]
    except socket.gaierror:
        return []


def is_private_url(url: str) -> bool:  # pylint: disable=too-many-return-statements
    """Return True when *url* resolves to a private / reserved host (SSRF guard).

    Uses :mod:`ipaddress` for IP-literal hostnames, covering all private,
    loopback, link-local, reserved, and IPv4-mapped IPv6 addresses.
    Non-IP hostnames are resolved via DNS; if any resolved address is private
    the URL is blocked.  DNS failures are treated as private (fail-closed)
    to prevent SSRF via temporarily unreachable hosts.
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
        ips = _resolve_host(host)
        if not ips:
            # DNS failure (NXDOMAIN, timeout, etc.) — fail-closed to prevent SSRF.
            return True
        for ip_str in ips:
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


def safe_get(url: str, *, max_redirects: int = 5, **kwargs) -> requests.Response:
    """GET *url*, following redirects while validating each hop against SSRF rules.

    Prevents redirect-based SSRF bypass: after each 3xx response the ``Location``
    header is checked with :func:`is_private_url` before the next hop is made.

    Raises :class:`ValueError` when a redirect target resolves to a
    private/reserved address, and
    :class:`requests.exceptions.TooManyRedirects` after *max_redirects* hops.
    All other :class:`requests.exceptions.RequestException` subclasses propagate
    unchanged so callers can handle them normally.
    """
    kwargs = dict(kwargs)
    kwargs['allow_redirects'] = False
    for _ in range(max_redirects + 1):
        response = requests.get(url, **kwargs)
        if not response.is_redirect:
            return response
        location = response.headers.get('Location', '')
        resolved = urljoin(url, location)
        if is_private_url(resolved):
            response.close()
            raise ValueError(f'Redirect to private/reserved URL blocked: {resolved}')
        response.close()
        url = resolved
    raise requests.exceptions.TooManyRedirects(
        f'Exceeded {max_redirects} redirects'
    )
