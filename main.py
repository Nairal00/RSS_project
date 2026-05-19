from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from cache import load_cache, save_cache
from models import Article
from rss_fetcher import fetch_feed, validate_feed_url

FEEDS_FILE = Path(__file__).parent / "feeds.txt"
OUTPUT_FILE = Path(__file__).parent / "output.html"


def load_feed_urls() -> list[str]:
    if not FEEDS_FILE.exists():
        print(f"[ERROR] {FEEDS_FILE} not found. Create it with one RSS URL per line.")
        sys.exit(1)
    urls = []
    with FEEDS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    if not urls:
        print("[ERROR] feeds.txt contains no URLs.")
        sys.exit(1)
    return urls


def fetch_all_feeds(urls: list[str]) -> list[Article]:
    valid_urls = [u for u in urls if validate_feed_url(u)]
    articles: list[Article] = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_feed, url): url for url in valid_urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result = future.result()
                print(f"[INFO] Fetched {len(result)} articles from {url}")
                articles.extend(result)
            except Exception as e:
                print(f"[WARNING] Failed to fetch {url}: {type(e).__name__}: {e}")

    return articles


def main() -> None:
    load_dotenv()

    urls = load_feed_urls()
    articles = fetch_all_feeds(urls)

    print(f"\n[INFO] Total articles fetched: {len(articles)}")
    for article in sorted(articles, key=lambda a: a.published, reverse=True):
        source = "[Techmeme]" if article.is_techmeme else "[Feed]"
        print(f"  {source} {article.published.strftime('%Y-%m-%d %H:%M')} — {article.title}")


if __name__ == "__main__":
    main()