"""Article content extraction via the Jina AI reader."""

import re
from typing import Optional

import requests

from models import Article, FeedError
from validators import is_private_url
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

    jina_url = f'{JINA_BASE_URL}{article.link}'
    jina_headers = {
        'X-Remove-Selector': JINA_REMOVE_SELECTOR,
    }
    try:
        response = requests.get(jina_url, headers=jina_headers, timeout=JINA_TIMEOUT, stream=True)
        response.raise_for_status()
        encoding = response.encoding if isinstance(response.encoding, str) else 'utf-8'
        raw_bytes = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)

        if isinstance(raw_bytes, (bytes, bytearray)):
            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                msg = f'[{source}] Jina response too large for "{article.title}"; skipping.'
                print(msg)
                return None, FeedError(source=source, message=msg)
            raw_text = raw_bytes.decode(encoding, errors='replace')
        else:
            # Compatibility path for mocked/non-stream responses that only expose ``text``.
            raw_text = response.text if isinstance(response.text, str) else str(response.text)
            if len(raw_text.encode(encoding, errors='replace')) > MAX_RESPONSE_BYTES:
                msg = f'[{source}] Jina response too large for "{article.title}"; skipping.'
                print(msg)
                return None, FeedError(source=source, message=msg)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'N/A'
        msg = f'[{source}] Jina HTTP error {status} for "{article.title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)
    except requests.RequestException as exc:
        msg = f'[{source}] Jina request error for "{article.title}": {exc}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    content = raw_text.strip()
    if not content:
        msg = f'[{source}] Jina无法读取网页信息: {article.link}'
        print(msg)
        return None, FeedError(source=source, message=msg)

    return strip_markdown(content), None
