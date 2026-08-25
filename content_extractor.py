"""Article content extraction via the Jina AI reader."""

import re
from typing import Optional

import requests

from models import Article, FeedError
from validators import has_control_chars, is_private_url, safe_get
from config import JINA_BASE_URL, JINA_REMOVE_SELECTOR, JINA_TIMEOUT, MAX_RESPONSE_BYTES


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


def _validate_link(source: str, link: str) -> Optional[FeedError]:
    """Return a FeedError if *link* fails SSRF or control-character checks, else None."""
    if is_private_url(link):
        msg = f'[{source}] Rejected private/reserved article link: {link}'
        print(msg)
        return FeedError(source=source, message=msg)
    if has_control_chars(link):
        msg = f'[{source}] Article link contains control characters; skipping: {link!r}'
        print(msg)
        return FeedError(source=source, message=msg)
    return None


def _do_request(
    source: str,
    title: str,
    jina_url: str,
) -> tuple[Optional[requests.Response], Optional[FeedError]]:
    """Send a streaming GET request to *jina_url* and return ``(response, None)`` on success."""
    try:
        response = safe_get(
            jina_url,
            headers={'X-Remove-Selector': JINA_REMOVE_SELECTOR},
            timeout=JINA_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()
        return response, None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'N/A'
        msg = f'[{source}] Jina HTTP error {status} for "{title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)
    except (ValueError, requests.RequestException) as exc:
        msg = f'[{source}] Jina request error for "{title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)


def _decode_response(
    source: str,
    title: str,
    response: requests.Response,
) -> tuple[Optional[str], Optional[FeedError]]:
    """Read, size-check, and decode the response body; return ``(text, None)`` on success."""
    encoding = response.encoding if isinstance(response.encoding, str) else response.apparent_encoding or 'utf-8'
    raw_bytes = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)

    too_large_msg = f'[{source}] Jina response too large for "{title}"; skipping.'

    if isinstance(raw_bytes, (bytes, bytearray)):
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            print(too_large_msg)
            return None, FeedError(source=source, message=too_large_msg)
        return raw_bytes.decode(encoding, errors='replace'), None

    # Compatibility path for mocked/non-stream responses that only expose ``text``.
    # Check Content-Length header first to avoid loading an oversized body.
    content_length = response.headers.get('Content-Length')
    if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
        print(too_large_msg)
        return None, FeedError(source=source, message=too_large_msg)
    raw_text = response.text if isinstance(response.text, str) else str(response.text)
    if len(raw_text.encode(encoding, errors='replace')) > MAX_RESPONSE_BYTES:
        print(too_large_msg)
        return None, FeedError(source=source, message=too_large_msg)
    return raw_text, None


def fetch_article_content(
    source: str,
    article: Article,
) -> tuple[Optional[str], Optional[FeedError]]:
    """Fetch clean article text via the Jina AI reader (``https://r.jina.ai/{link}``).

    - Applies SSRF guard on *article.link* before making any outbound request.
    - Returns ``(content, None)`` on success or ``(None, FeedError)`` on any failure.
    - If Jina returns an empty body, logs "Jina无法读取网页信息" and skips the article.
    """
    if err := _validate_link(source, article.link):
        return None, err

    response, err = _do_request(source, article.title, f'{JINA_BASE_URL}{article.link}')
    if err:
        return None, err

    raw_text, err = _decode_response(source, article.title, response)  # type: ignore[arg-type]
    if err:
        return None, err

    content = raw_text.strip()  # type: ignore[union-attr]
    if not content:
        msg = f'[{source}] Jina无法读取网页信息: {article.link}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    return strip_markdown(content), None
