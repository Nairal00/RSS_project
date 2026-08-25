"""RSS feed fetching and entry parsing."""

import calendar
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
import feedparser
import requests

from config import FEED_FETCH_TIMEOUT, TIME_RANGE_HOURS
from models import Article, FeedError
from validators import has_control_chars, is_http_url, is_private_url, safe_get


def compute_since_window(now: datetime) -> datetime:
    """Return the start of the time window for feed filtering.

    Anchors to UTC midnight of *now*, then subtracts ``TIME_RANGE_HOURS``.
    This always covers exactly the 24 hours before Beijing 08:00 regardless of
    when the program runs.
    """
    utc_midnight: datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return utc_midnight - timedelta(hours=TIME_RANGE_HOURS)


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
                    if not is_http_url(url):
                        print(f'[{name}] Skipping feed with invalid URL scheme: {url}')
                        continue
                    if has_control_chars(url):
                        print(f'[{name}] Skipping feed URL with control characters: {url!r}')
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
            break

        # --- Validate link format ---
        if not link or not is_http_url(link):
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
        response = safe_get(url, timeout=FEED_FETCH_TIMEOUT)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'N/A'
        msg = f'[{source}] HTTP error {status}: {exc}'
        print(msg)
        errors.append(FeedError(source=source, message=msg))
        return articles, errors
    except (ValueError, requests.RequestException) as exc:
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

    return articles, errors
