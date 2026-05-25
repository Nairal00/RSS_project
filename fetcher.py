"""RSS Feed Fetcher — Foundation, Data Pipeline, Content Extraction & AI Scoring."""

import calendar
import ipaddress
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIME_RANGE_HOURS: int = 72
DEEPSEEK_BASE_URL: str = 'https://api.deepseek.com'
DEEPSEEK_MODEL: str = 'deepseek-v4-flash'
SCORE_PROMPT: str = """你是一名资深的科技编辑。你的读者包括AI agent产品经理、用户研究员以及全职程序员。请阅读用户提供的文字，完成两件事：
1. 用英文总结文章，少于200字。复杂技术讲的简单有趣。
2. 给出 score：如果文章属于优先分类给 1，不符合给 0。符合给1。
   （1: a.模型与产品发布 b.AI agent c.企业使用案例 d.Human-AI interaction research e. Agent 与开发工程
     0: 不属于得分1的所有分类）

请只输出 json，格式如下：

{
    "summary": "这里是一句话摘要",
    "score": 1
}
"""

# ---------------------------------------------------------------------------
# SSRF prevention — private / reserved host patterns
# ---------------------------------------------------------------------------


def _resolve_host(host: str) -> list[str]:
    """Resolve *host* to IP address strings via DNS. Returns ``[]`` on any failure."""
    try:
        return [sockaddr[0] for *_, sockaddr in socket.getaddrinfo(host, None)]
    except socket.gaierror:
        return []

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
    summary: Optional[str] = None
    score: Optional[int] = None


@dataclass
class FeedError:
    """An error collected during feed fetching or parsing."""

    source: str
    message: str
    jina_content: Optional[str] = None


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

    # Reject links containing control characters (prevents HTTP header injection).
    if any(c in article.link for c in ('\r', '\n', '\x00')):
        msg = f'[{source}] Article link contains control characters; skipping: {article.link!r}'
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


def _redact(text: str, secret: str) -> str:
    """Replace *secret* in *text* with ``'<redacted>'`` to prevent credential leaks."""
    if not secret:
        return text
    return text.replace(secret, '<redacted>')


def call_deepseek(
    client: OpenAI,
    content: str,
    source: str,
    title: str,
) -> tuple[Optional[str], Optional[int], Optional[FeedError]]:
    """Summarize and score *content* via the DeepSeek API. Retries once on any failure.

    Returns ``(summary, score, None)`` on success or ``(None, None, FeedError)`` after
    two failed attempts.  *score* is guaranteed to be ``0`` or ``1``.
    """
    last_error: str = f'[{source}] No attempts made for "{title}"'
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {'role': 'system', 'content': SCORE_PROMPT},
                    {'role': 'user', 'content': content},
                ],
                response_format={'type': 'json_object'},
            )
            raw: str = response.choices[0].message.content or ''
            data: dict = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = (
                f'[{source}] Malformed JSON response for "{title}"'
                f' (attempt {attempt + 1}): {exc}'
            )
            print(last_error)
            continue
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            last_error = (
                f'[{source}] API error for "{title}"'
                f' (attempt {attempt + 1}): {_redact(str(exc), client.api_key)}'
            )
            print(last_error)
            continue

        summary = data.get('summary')
        score = data.get('score')

        if summary is None or score is None:
            last_error = (
                f'[{source}] Null summary or score for "{title}"'
                f' (attempt {attempt + 1})'
            )
            print(last_error)
            continue

        if score not in (0, 1):
            last_error = (
                f'[{source}] Score {score!r} out of range (0 or 1) for "{title}"'
                f' (attempt {attempt + 1})'
            )
            print(last_error)
            continue

        return str(summary), int(score), None

    return None, None, FeedError(source=source, message=last_error)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run(  # pylint: disable=too-many-locals
    feeds_path: str = 'feeds.txt',
) -> tuple[list[Article], list[FeedError]]:
    """Load feed sources, fetch articles, summarize and score via DeepSeek, sort results."""
    # Load local .env values (if present) without overriding existing process env.
    load_dotenv()

    api_key: Optional[str] = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        print('Error: DEEPSEEK_API_KEY environment variable is not set.')
        sys.exit(1)

    client: OpenAI = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    now: datetime = get_utc_now()
    since: datetime = now - timedelta(hours=TIME_RANGE_HOURS)

    feeds: dict[str, str] = load_feeds(feeds_path)

    all_articles: list[Article] = []
    all_errors: list[FeedError] = []

    for source, url in feeds.items():
        articles, errors = fetch_feed(source, url, since)
        all_articles.extend(articles)
        all_errors.extend(errors)

    valid_articles: list[Article] = []
    for article in all_articles:
        content, jina_error = fetch_article_content(article.source, article)
        if jina_error:
            all_errors.append(jina_error)
            continue

        summary, score, api_error = call_deepseek(
            client, content, article.source, article.title  # type: ignore[arg-type]
        )
        if api_error:
            api_error.jina_content = content
            all_errors.append(api_error)
            continue

        article.summary = summary
        article.score = score
        valid_articles.append(article)

    # Sort by score descending; break ties by proximity to now (ascending delta)
    valid_articles.sort(
        key=lambda a: (-(a.score or 0), abs((now - a.published).total_seconds()))
    )

    return valid_articles, all_errors


def main() -> None:
    """CLI entry point."""
    articles, errors = run()
    for article in articles:
        print(f'[{article.source}] {article.title}')
        print(f'  {article.link}')
        if article.summary:
            print(f'  Summary: {article.summary}')
    if errors:
        print(f'\n{len(errors)} error(s) collected:')
        for error in errors:
            print(f'- {error.message}')
            if error.jina_content:
                print(f'  [Article text preview]: {error.jina_content[:200]}...')


if __name__ == '__main__':
    main()
