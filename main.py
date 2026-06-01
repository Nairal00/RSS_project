"""CLI entry point for the RSS AI News Digest."""

import os
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from config import (
    DEEPSEEK_BASE_URL,
    HTML_OUTPUT_PATH,
    NEWSLETTER_TITLE,
    SAME_SOURCE_SLEEP_SECS,
    TIME_RANGE_HOURS,
)
from content_extractor import fetch_article_content
from feed_fetcher import fetch_feed, load_feeds
from html_generator import generate_html
from models import Article, FeedError
from summarizer import call_deepseek


def get_utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def run(  # pylint: disable=too-many-locals
    feeds_path: str = 'feeds.txt',
) -> tuple[list[Article], list[FeedError], list[str]]:
    """Load feed sources, fetch articles, summarize and score via DeepSeek, sort results."""
    # Load local .env values (if present) without overriding existing process env.
    load_dotenv()

    api_key: Optional[str] = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        print('Error: DEEPSEEK_API_KEY environment variable is not set.')
        sys.exit(1)

    client: OpenAI = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    now: datetime = get_utc_now()
    # Anchor to UTC midnight (= Beijing 08:00), then go back 24 hours.
    # This always covers exactly "the 24 hours before Beijing 08:00 today",
    # regardless of what time the program actually runs.
    utc_midnight: datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since: datetime = utc_midnight - timedelta(hours=TIME_RANGE_HOURS)

    feeds: dict[str, str] = load_feeds(feeds_path)

    all_articles: list[Article] = []
    all_errors: list[FeedError] = []
    silent_sources: list[str] = []

    for source, url in feeds.items():
        articles, errors = fetch_feed(source, url, since)
        if not articles and not errors:
            silent_sources.append(source)
        all_articles.extend(articles)
        all_errors.extend(errors)

    valid_articles: list[Article] = []
    last_source: Optional[str] = None
    for article in all_articles:
        if article.source == last_source:
            time.sleep(SAME_SOURCE_SLEEP_SECS)
        last_source = article.source
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

    return valid_articles, all_errors, silent_sources


def main() -> None:
    """CLI entry point."""
    articles, errors, silent_sources = run()

    html_output = generate_html(
        articles=articles,
        errors=errors,
        silent_sources=silent_sources,
        title=NEWSLETTER_TITLE,
        now=get_utc_now(),
    )
    with open(HTML_OUTPUT_PATH, 'w', encoding='utf-8') as fh:
        fh.write(html_output)

    digest_uri = Path(HTML_OUTPUT_PATH).resolve().as_uri()
    webbrowser.open(digest_uri)


if __name__ == '__main__':
    main()
