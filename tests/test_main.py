from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import main as main_module
from main import fetch_all_feeds, load_feed_urls
from models import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_article(title: str = "Test", url: str = "https://example.com/a") -> Article:
    return Article(
        title=title,
        url=url,
        raw_summary="",
        clean_summary="",
        published=datetime(2024, 1, 1, tzinfo=timezone.utc),
        source_feed="https://example.com/feed",
        is_techmeme=False,
    )


# ---------------------------------------------------------------------------
# load_feed_urls
# ---------------------------------------------------------------------------

class TestLoadFeedUrls:
    @pytest.fixture(autouse=True)
    def patch_feeds_file(self, tmp_path, monkeypatch):
        self._tmp_path = tmp_path
        self._feeds_file = tmp_path / "feeds.txt"
        monkeypatch.setattr(main_module, "FEEDS_FILE", self._feeds_file)

    def test_valid_urls_returned(self):
        self._feeds_file.write_text(
            "https://example.com/feed\nhttps://another.com/rss\n",
            encoding="utf-8",
        )
        result = load_feed_urls()
        assert result == ["https://example.com/feed", "https://another.com/rss"]

    def test_comment_lines_skipped(self):
        self._feeds_file.write_text(
            "# This is a comment\nhttps://example.com/feed\n",
            encoding="utf-8",
        )
        result = load_feed_urls()
        assert result == ["https://example.com/feed"]

    def test_blank_lines_skipped(self):
        self._feeds_file.write_text(
            "\nhttps://example.com/feed\n\n",
            encoding="utf-8",
        )
        result = load_feed_urls()
        assert result == ["https://example.com/feed"]

    def test_only_comments_causes_exit(self):
        self._feeds_file.write_text("# just a comment\n# another\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_feed_urls()

    def test_empty_file_causes_exit(self):
        self._feeds_file.write_text("", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_feed_urls()

    def test_missing_file_causes_exit(self):
        # File was never created by this fixture
        with pytest.raises(SystemExit):
            load_feed_urls()

    def test_missing_file_prints_error(self, capsys):
        with pytest.raises(SystemExit):
            load_feed_urls()
        assert "[ERROR]" in capsys.readouterr().out

    def test_only_comments_prints_error(self, capsys):
        self._feeds_file.write_text("# comment\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_feed_urls()
        assert "[ERROR]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fetch_all_feeds
# ---------------------------------------------------------------------------

class TestFetchAllFeeds:
    def test_valid_url_returns_articles(self):
        article = _make_article()
        with patch("main.validate_feed_url", return_value=True), \
             patch("main.fetch_feed", return_value=[article]):
            result = fetch_all_feeds(["https://example.com/feed"])
        assert len(result) == 1
        assert result[0].title == "Test"

    def test_invalid_url_filtered_before_fetch(self):
        with patch("main.validate_feed_url", return_value=False), \
             patch("main.fetch_feed") as mock_fetch:
            result = fetch_all_feeds(["https://192.168.1.1/feed"])
        mock_fetch.assert_not_called()
        assert result == []

    def test_fetch_exception_returns_empty_list(self):
        with patch("main.validate_feed_url", return_value=True), \
             patch("main.fetch_feed", side_effect=ConnectionError("timeout")):
            result = fetch_all_feeds(["https://example.com/feed"])
        assert result == []

    def test_fetch_exception_prints_warning(self, capsys):
        with patch("main.validate_feed_url", return_value=True), \
             patch("main.fetch_feed", side_effect=RuntimeError("boom")):
            fetch_all_feeds(["https://example.com/feed"])
        assert "[WARNING]" in capsys.readouterr().out

    def test_one_bad_feed_does_not_block_others(self):
        good_article = _make_article()

        def fake_fetch(url: str) -> list[Article]:
            if "bad" in url:
                raise ConnectionError("failed")
            return [good_article]

        with patch("main.validate_feed_url", return_value=True), \
             patch("main.fetch_feed", side_effect=fake_fetch):
            result = fetch_all_feeds(["https://bad.com/feed", "https://good.com/feed"])
        assert len(result) == 1
        assert result[0].title == "Test"

    def test_multiple_valid_feeds_combined(self):
        articles = [_make_article(title=f"A{i}", url=f"https://example.com/{i}") for i in range(3)]

        def fake_fetch(url: str) -> list[Article]:
            return [articles[int(url[-1])]]

        with patch("main.validate_feed_url", return_value=True), \
             patch("main.fetch_feed", side_effect=fake_fetch):
            result = fetch_all_feeds(
                ["https://example.com/0", "https://example.com/1", "https://example.com/2"]
            )
        assert len(result) == 3

    def test_empty_url_list_returns_empty(self):
        result = fetch_all_feeds([])
        assert result == []


# ---------------------------------------------------------------------------
# main() — integration coverage
# ---------------------------------------------------------------------------

class TestMain:
    @pytest.fixture(autouse=True)
    def patch_feeds_file(self, tmp_path, monkeypatch):
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text("https://example.com/feed\n", encoding="utf-8")
        monkeypatch.setattr(main_module, "FEEDS_FILE", feeds_file)

    def test_main_prints_article_count(self, capsys):
        article = _make_article()
        with patch("main.load_dotenv"), \
             patch("main.fetch_all_feeds", return_value=[article]):
            main_module.main()
        assert "Total articles fetched: 1" in capsys.readouterr().out

    def test_main_labels_techmeme_articles(self, capsys):
        techmeme_article = Article(
            title="AI News",
            url="https://www.techmeme.com/a",
            raw_summary="",
            clean_summary="",
            published=datetime(2024, 6, 1, tzinfo=timezone.utc),
            source_feed="https://www.techmeme.com/feed.xml",
            is_techmeme=True,
        )
        with patch("main.load_dotenv"), \
             patch("main.fetch_all_feeds", return_value=[techmeme_article]):
            main_module.main()
        out = capsys.readouterr().out
        assert "[Techmeme]" in out

    def test_main_labels_non_techmeme_articles(self, capsys):
        article = _make_article()
        with patch("main.load_dotenv"), \
             patch("main.fetch_all_feeds", return_value=[article]):
            main_module.main()
        assert "[Feed]" in capsys.readouterr().out

    def test_main_sorts_by_published_descending(self, capsys):
        older = _make_article(title="Older", url="https://example.com/old")
        older.published = datetime(2024, 1, 1, tzinfo=timezone.utc)
        newer = _make_article(title="Newer", url="https://example.com/new")
        newer.published = datetime(2024, 6, 1, tzinfo=timezone.utc)

        with patch("main.load_dotenv"), \
             patch("main.fetch_all_feeds", return_value=[older, newer]):
            main_module.main()
        out = capsys.readouterr().out
        assert out.index("Newer") < out.index("Older")

    def test_main_empty_feed_prints_zero(self, capsys):
        with patch("main.load_dotenv"), \
             patch("main.fetch_all_feeds", return_value=[]):
            main_module.main()
        assert "Total articles fetched: 0" in capsys.readouterr().out
