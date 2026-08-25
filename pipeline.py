"""Business-flow orchestration: collect, enrich, score, and sort articles."""

import time
from datetime import datetime
from typing import Optional

from openai import OpenAI

from config import SAME_SOURCE_SLEEP_SECS
from content_extractor import fetch_article_content
from feed_fetcher import fetch_feed, load_feeds
from models import Article, FeedError
from summarizer import call_deepseek


def _enrich_articles(
    articles: list[Article],
    client: OpenAI,
) -> tuple[list[Article], list[FeedError]]:
    """Fetch Jina content and DeepSeek score for each article.

    Applies same-source sleep throttle between consecutive articles from the
    same source.  Returns ``(valid_articles, errors)``.
    """
    valid: list[Article] = []
    errors: list[FeedError] = []
    last_source: Optional[str] = None
    for article in articles:
        if article.source == last_source:
            time.sleep(SAME_SOURCE_SLEEP_SECS)
        last_source = article.source

        content, jina_error = fetch_article_content(article.source, article)
        if jina_error:
            errors.append(jina_error)
            continue

        summary, score, api_error = call_deepseek(
            client, content, article.source, article.title  # type: ignore[arg-type]
        )
        if api_error:
            api_error.jina_content = content
            errors.append(api_error)
            continue

        article.summary = summary
        article.score = score
        valid.append(article)
    return valid, errors


def collect_scored_articles(
    feeds_path: str,
    client: OpenAI,
    since: datetime,
    now: datetime,
) -> tuple[list[Article], list[FeedError], list[str]]:
    """Load feeds, enrich each article via Jina + DeepSeek, and return sorted results.

    Returns ``(articles, errors, silent_sources)``.
    """
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

    valid_articles, enrich_errors = _enrich_articles(all_articles, client)
    all_errors.extend(enrich_errors)

    # Sort by score descending; break ties by proximity to now (ascending delta)
    valid_articles.sort(
        key=lambda a: (-(a.score or 0), abs((now - a.published).total_seconds()))
    )

    return valid_articles, all_errors, silent_sources
