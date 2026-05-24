"""RSS Feed Fetcher — Foundation, Data Pipeline & Content Extraction."""

import calendar
import hashlib
import ipaddress
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIME_RANGE_HOURS: int = 48

# ---------------------------------------------------------------------------
# SSRF prevention — private / reserved host patterns
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Article:
    """A parsed RSS article within the time window."""

    source: str
    title: str
    link: str
    description: Optional[str]
    published: datetime


@dataclass
class FeedError:
    """An error collected during feed fetching or parsing."""

    source: str
    message: str


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def is_private_url(url: str) -> bool:
    """Return True when *url* resolves to a private / reserved host (SSRF guard).

    Uses :mod:`ipaddress` for IP-literal hostnames, covering all private,
    loopback, link-local, reserved, and IPv4-mapped IPv6 addresses.
    Non-IP hostnames are checked only for the literal string ``localhost``.
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
        # Hostname (not a bare IP literal) — allow; DNS-level checks are out of scope.
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


def load_feeds(path: str) -> dict[str, str]:
    """Load ``NAME=URL`` pairs from *path*.

    Blank lines and lines beginning with ``#`` are ignored.
    Exits with ``sys.exit(1)`` if the file cannot be opened.
    """
    feeds: dict[str, str] = {}
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    name, _, url = line.partition('=')
                    name, url = name.strip(), url.strip()
                    if urlparse(url).scheme not in ('http', 'https'):
                        print(f'[{name}] Skipping feed with invalid URL scheme: {url}')
                        continue
                    feeds[name] = url
    except FileNotFoundError:
        print(f'Error: feeds file not found: {path}')
        sys.exit(1)
    except OSError as exc:
        print(f'Error reading feeds file: {exc}')
        sys.exit(1)
    return feeds


def _parse_published(entry: dict) -> Optional[datetime]:
    """Extract a UTC-aware datetime from a feedparser entry dict.

    Returns ``None`` when the field is absent or malformed.
    """
    published_parsed = entry.get('published_parsed')
    if not published_parsed:
        return None
    try:
        ts = calendar.timegm(published_parsed)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, OverflowError, OSError):
        return None


def _parse_entries(
    source: str,
    entries: list,
    since: datetime,
) -> tuple[list[Article], list[FeedError]]:
    """Validate and filter raw feed entries, returning ``(articles, errors)``.

    Skips entries with missing/malformed published time, articles older than
    *since*, empty/broken links, or article links pointing to private/reserved IPs.
    """
    articles: list[Article] = []
    errors: list[FeedError] = []

    for entry in entries:
        title: str = entry.get('title', '').strip()
        link: str = entry.get('link', '').strip()

        # --- Validate published time ---
        published = _parse_published(entry)
        if published is None:
            msg = (
                f'[{source}] Malformed or missing published time '
                f'for article "{title}" ({link}); skipping.'
            )
            print(msg)
            errors.append(FeedError(source=source, message=msg))
            continue

        # --- Time-range filter ---
        if published < since:
            continue

        # --- Validate link format ---
        if not link or not link.startswith(('http://', 'https://')):
            msg = (
                f'[{source}] Empty or broken link for article '
                f'published at {published.isoformat()}; skipping.'
            )
            print(msg)
            errors.append(FeedError(source=source, message=msg))
            continue

        # --- SSRF guard on article link ---
        if is_private_url(link):
            msg = (
                f'[{source}] Private/reserved article link '
                f'published at {published.isoformat()}; skipping.'
            )
            print(msg)
            errors.append(FeedError(source=source, message=msg))
            continue

        articles.append(Article(
            source=source,
            title=title,
            link=link,
            description=entry.get('summary') or entry.get('description') or None,
            published=published,
        ))
        print(f'[{source}] {title}\n  {link}')

    return articles, errors


def fetch_feed(
    source: str,
    url: str,
    since: datetime,
) -> tuple[list[Article], list[FeedError]]:
    """Fetch *url* and return ``(articles, errors)`` for articles published after *since*.

    - Rejects private / reserved feed URLs immediately (SSRF prevention).
    - On HTTP error: prints status code + message, records the error, returns empty.
    - Entry-level validation is delegated to :func:`_parse_entries`.
    """
    errors: list[FeedError] = []
    articles: list[Article] = []

    # --- SSRF guard on feed URL ---
    if is_private_url(url):
        msg = f'[{source}] Rejected private/reserved URL: {url}'
        print(msg)
        errors.append(FeedError(source=source, message=msg))
        return articles, errors

    # --- HTTP fetch ---
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'N/A'
        msg = f'[{source}] HTTP error {status}: {exc}'
        print(msg)
        errors.append(FeedError(source=source, message=msg))
        return articles, errors
    except requests.RequestException as exc:
        msg = f'[{source}] Request error: {exc}'
        print(msg)
        errors.append(FeedError(source=source, message=msg))
        return articles, errors

    feed = feedparser.parse(response.content)

    if not feed.entries:
        msg = f'[{source}] No parseable entries found; the feed may be empty or malformed.'
        print(msg)
        errors.append(FeedError(source=source, message=msg))
        return articles, errors

    articles, errors = _parse_entries(source, feed.entries, since)

    if not articles and not errors:
        print(f'[{source}] No update in the last {TIME_RANGE_HOURS} hours.')

    return articles, errors


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def sanitize_filename(title: str, url: str) -> str:
    """Return a safe filename component derived from *title*.

    Lowercases, replaces spaces with ``_``, removes non-alphanumeric-or-underscore
    characters, and truncates to 50 characters.  If the result is empty (e.g. the
    title was blank or entirely non-ASCII), falls back to the first 8 hex characters
    of the MD5 hash of *url*.
    """
    name = title.lower().replace(' ', '_')
    name = re.sub(r'[^a-z0-9_]', '', name)
    name = name[:50]
    if not name:
        name = hashlib.md5(url.encode()).hexdigest()[:8]
    return name


def strip_markdown(text: str) -> str:
    """Remove images, image links, hyperlinks, and inline formatting from *text*.

    Processing order matters — image-links must be stripped before plain images,
    and images before hyperlinks.
    """
    # Image links: [![alt](img_url)](link_url) → remove entirely
    text = re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)', '', text)
    # Plain images: ![alt](url) → remove entirely
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    # Hyperlinks: [text](url) → text
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Bold: **text** or __text__ → text
    text = re.sub(r'\*{2}([^*\n]+)\*{2}', r'\1', text)
    text = re.sub(r'_{2}([^_\n]+)_{2}', r'\1', text)
    # Italic: *text* (not list bullets) or _text_ → text
    text = re.sub(r'(?<!\*)\*(?!\*|\s)([^*\n]+?)(?<!\s)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_(?!_|\s)([^_\n]+?)(?<!\s)_(?!_)', r'\1', text)
    # Inline code: `code` → code
    text = re.sub(r'`([^`\n]+)`', r'\1', text)
    return text


def fetch_article_content(
    source: str,
    article: Article,
) -> tuple[Optional[str], Optional[FeedError]]:
    """Fetch clean article text via the Jina AI reader (``https://r.jina.ai/{link}``).

    - Applies SSRF guard on *article.link* before making any outbound request.
    - Returns ``(content, None)`` on success or ``(None, FeedError)`` on any failure.
    - If Jina returns an empty body, logs "Jina无法读取网页信息" and skips the article.
    """
    if is_private_url(article.link):
        msg = f'[{source}] Rejected private/reserved article link: {article.link}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    jina_url = f'https://r.jina.ai/{article.link}'
    jina_headers = {
        'X-Remove-Selector': 'nav, header, footer, aside',
    }
    try:
        response = requests.get(jina_url, headers=jina_headers, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'N/A'
        msg = f'[{source}] Jina HTTP error {status} for "{article.title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)
    except requests.RequestException as exc:
        msg = f'[{source}] Jina request error for "{article.title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    content = response.text.strip()
    if not content:
        msg = f'[{source}] Jina无法读取网页信息: {article.link}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    return strip_markdown(content), None


def save_article(source: str, title: str, url: str, content: str) -> str:
    """Save *content* to ``{source}_{sanitized_title}.md`` in the current directory.

    Overwrites any pre-existing file with the same name.
    Returns the filename that was written.
    """
    sanitized = sanitize_filename(title, url)
    filename = f'{source}_{sanitized}.md'
    with open(filename, 'w', encoding='utf-8') as fh:
        fh.write(content)
    return filename


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run(feeds_path: str = 'feeds.txt') -> tuple[list[Article], list[FeedError]]:
    """Load feed sources, fetch all articles, and save content to markdown files."""
    now: datetime = get_utc_now()
    since: datetime = now - timedelta(hours=TIME_RANGE_HOURS)

    feeds: dict[str, str] = load_feeds(feeds_path)

    all_articles: list[Article] = []
    all_errors: list[FeedError] = []

    for source, url in feeds.items():
        articles, errors = fetch_feed(source, url, since)
        all_articles.extend(articles)
        all_errors.extend(errors)

    for article in all_articles:
        content, error = fetch_article_content(article.source, article)
        if error:
            all_errors.append(error)
            continue
        filename = save_article(article.source, article.title, article.link, content)
        print(f'[{article.source}] Saved: {filename}')

    return all_articles, all_errors


def main() -> None:
    """CLI entry point."""
    _, errors = run()  # NOTE: Sprint 4 will pass articles to the HTML renderer
    if errors:
        print(f'\n{len(errors)} error(s) collected (will be shown in the final digest).')
        print('Collected errors:')
        for error in errors:
            print(f'- {error.message}')


if __name__ == '__main__':
    main()
