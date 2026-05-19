from __future__ import annotations

import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup

from models import Article

# Private/reserved IP ranges to block (SSRF prevention)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_host(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except (socket.gaierror, ValueError):
        return False


def validate_feed_url(url: str) -> bool:
    """Return True if the URL is safe to fetch. Rejects non-http(s) and private IPs."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        print(f"[WARNING] Rejected URL (invalid scheme): {url}")
        return False
    if not parsed.hostname:
        print(f"[WARNING] Rejected URL (no hostname): {url}")
        return False
    if _is_private_host(parsed.hostname):
        print(f"[WARNING] Rejected URL (private/reserved IP): {url}")
        return False
    return True


def is_techmeme(url: str) -> bool:
    return "techmeme.com" in url


def strip_html(html_str: str) -> str:
    """Remove HTML tags and return plain text."""
    return BeautifulSoup(html_str, "lxml").get_text(separator=" ").strip()


def _parse_published(entry: object) -> datetime:
    """Convert feedparser published_parsed to a timezone-aware UTC datetime."""
    parsed = getattr(entry, "published_parsed", None)
    if parsed is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def fetch_feed(url: str) -> list[Article]:
    """Fetch and parse a single RSS/Atom feed URL into a list of Articles."""
    result = feedparser.parse(url)

    if result.get("bozo"):
        exc = result.get("bozo_exception", "unknown error")
        print(f"[WARNING] Malformed feed at {url}: {exc}")

    articles: list[Article] = []
    techmeme = is_techmeme(url)

    for entry in result.entries:
        title: str = getattr(entry, "title", "").strip()
        link: str = getattr(entry, "link", "").strip()
        raw_summary: str = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""

        if not title or not link:
            continue

        published = _parse_published(entry)
        clean_summary = strip_html(raw_summary) if techmeme else raw_summary

        articles.append(
            Article(
                title=title,
                url=link,
                raw_summary=raw_summary,
                clean_summary=clean_summary,
                published=published,
                source_feed=url,
                is_techmeme=techmeme,
            )
        )

    return articles
