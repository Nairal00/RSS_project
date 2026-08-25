"""CLI entry point for the RSS AI News Digest."""

from datetime import datetime, timezone

from config import HTML_OUTPUT_PATH, NEWSLETTER_TITLE
from feed_fetcher import compute_since_window
from html_generator import generate_html, open_digest, write_digest
from pipeline import collect_scored_articles
from summarizer import build_deepseek_client_from_env


def get_utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def main() -> None:
    """CLI entry point."""
    now = get_utc_now()
    client = build_deepseek_client_from_env()
    since = compute_since_window(now)
    articles, errors, silent = collect_scored_articles('feeds.txt', client, since, now)
    html = generate_html(articles=articles, errors=errors, silent_sources=silent,
                         title=NEWSLETTER_TITLE, now=now)
    path = write_digest(html, HTML_OUTPUT_PATH)
    open_digest(path)


if __name__ == '__main__':
    main()
