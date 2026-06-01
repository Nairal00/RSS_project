"""Tests for feed_fetcher: load_feeds, _parse_published, _parse_entries, fetch_feed."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from config import TIME_RANGE_HOURS
from models import Article, FeedError
from feed_fetcher import _parse_entries, _parse_published, fetch_feed, load_feeds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(hours=TIME_RANGE_HOURS)

# A published_parsed value that falls within the time window (1 hour ago)
RECENT_STRUCT = time.gmtime((NOW - timedelta(hours=1)).timestamp())

# A published_parsed value older than the window (25 hours ago)
# Keep this outside the configured time window even if TIME_RANGE_HOURS changes.
OLD_STRUCT = time.gmtime((NOW - timedelta(hours=TIME_RANGE_HOURS + 1)).timestamp())


def _make_entry(
    title: str = 'Test Article',
    link: str = 'https://example.com/article',
    published_parsed=None,
    summary: str = 'A summary',
) -> dict:
    """Build a minimal dict that looks like a feedparser entry."""
    return {
        'title': title,
        'link': link,
        'published_parsed': published_parsed if published_parsed is not None else RECENT_STRUCT,
        'summary': summary,
    }


def _make_feed(entries: list) -> MagicMock:
    """Build a minimal feedparser result mock."""
    mock = MagicMock()
    mock.entries = entries
    return mock


def _mock_response(content: bytes = b'<feed/>', status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# load_feeds
# ---------------------------------------------------------------------------


class TestLoadFeeds:
    def test_normal_parse(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text(
            '# comment\n'
            'FeedA=https://a.example.com/rss\n'
            'FeedB=https://b.example.com/atom\n',
            encoding='utf-8',
        )
        result = load_feeds(str(feeds_file))
        assert result == {
            'FeedA': 'https://a.example.com/rss',
            'FeedB': 'https://b.example.com/atom',
        }

    def test_missing_file_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            load_feeds('/nonexistent/path/feeds.txt')
        assert exc_info.value.code == 1

    def test_missing_file_prints_error(self, capsys):
        with pytest.raises(SystemExit):
            load_feeds('/nonexistent/path/feeds.txt')
        captured = capsys.readouterr()
        assert 'Error' in captured.out

    def test_skips_blank_and_comment_lines(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('\n# ignore me\n\nFeedC=https://c.example.com\n', encoding='utf-8')
        result = load_feeds(str(feeds_file))
        assert list(result.keys()) == ['FeedC']

    def test_invalid_url_scheme_skipped(self, tmp_path, capsys):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text(
            'BadFeed=ftp://example.com/feed\nGoodFeed=https://example.com/feed\n',
            encoding='utf-8',
        )
        result = load_feeds(str(feeds_file))
        assert 'BadFeed' not in result
        assert 'GoodFeed' in result
        captured = capsys.readouterr()
        assert 'Skipping' in captured.out


class TestLoadFeedsOsError:
    def test_os_error_exits(self):
        with patch('builtins.open', side_effect=OSError('permission denied')):
            with pytest.raises(SystemExit) as exc_info:
                load_feeds('some_path.txt')
        assert exc_info.value.code == 1

    def test_os_error_prints_message(self, capsys):
        with patch('builtins.open', side_effect=OSError('permission denied')):
            with pytest.raises(SystemExit):
                load_feeds('some_path.txt')
        captured = capsys.readouterr()
        assert 'Error' in captured.out


# ---------------------------------------------------------------------------
# _parse_published
# ---------------------------------------------------------------------------


class TestParsePublished:
    def test_valid_struct(self):
        entry = {'published_parsed': RECENT_STRUCT}
        result = _parse_published(entry)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_missing_field_returns_none(self):
        assert _parse_published({}) is None

    def test_none_value_returns_none(self):
        assert _parse_published({'published_parsed': None}) is None

    def test_malformed_value_returns_none(self):
        assert _parse_published({'published_parsed': 'not-a-struct'}) is None


# ---------------------------------------------------------------------------
# fetch_feed — private IP rejection
# ---------------------------------------------------------------------------


class TestFetchFeedPrivateIp:
    def test_private_ip_is_rejected(self):
        articles, errors = fetch_feed('TestSource', 'http://192.168.0.1/rss', SINCE)
        assert articles == []
        assert len(errors) == 1
        assert 'Rejected' in errors[0].message

    def test_private_ip_no_http_call(self):
        with patch('feed_fetcher.requests.get') as mock_get:
            fetch_feed('TestSource', 'http://10.0.0.1/rss', SINCE)
            mock_get.assert_not_called()

    def test_private_ip_prints_message(self, capsys):
        fetch_feed('TestSource', 'http://127.0.0.1/rss', SINCE)
        captured = capsys.readouterr()
        assert 'Rejected' in captured.out


# ---------------------------------------------------------------------------
# fetch_feed — HTTP errors
# ---------------------------------------------------------------------------


class TestFetchFeedHttpErrors:
    def test_http_404_logged(self):
        http_err = requests.HTTPError('404 Not Found')
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        http_err.response = mock_resp

        mock_response = _mock_response()
        mock_response.raise_for_status.side_effect = http_err

        with patch('feed_fetcher.requests.get', return_value=mock_response):
            articles, errors = fetch_feed('BadFeed', 'https://bad.example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        assert '404' in errors[0].message

    def test_http_error_printed(self, capsys):
        http_err = requests.HTTPError('500 Server Error')
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        http_err.response = mock_resp

        mock_response = _mock_response()
        mock_response.raise_for_status.side_effect = http_err

        with patch('feed_fetcher.requests.get', return_value=mock_response):
            fetch_feed('BadFeed', 'https://bad.example.com/rss', SINCE)

        captured = capsys.readouterr()
        assert 'HTTP error' in captured.out

    def test_connection_error_logged(self):
        with patch('feed_fetcher.requests.get', side_effect=requests.ConnectionError('timeout')):
            articles, errors = fetch_feed('BadFeed', 'https://bad.example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        assert 'Request error' in errors[0].message


# ---------------------------------------------------------------------------
# fetch_feed — empty feed
# ---------------------------------------------------------------------------


class TestFetchFeedEmpty:
    def test_empty_feed_returns_error(self, capsys):
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed([])),
        ):
            articles, errors = fetch_feed('EmptyFeed', 'https://empty.example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        captured = capsys.readouterr()
        assert 'No parseable entries' in captured.out


# ---------------------------------------------------------------------------
# fetch_feed — normal feed (articles within time window)
# ---------------------------------------------------------------------------


class TestFetchFeedNormal:
    def test_returns_articles(self):
        entries = [_make_entry()]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert len(articles) == 1
        assert errors == []
        art = articles[0]
        assert isinstance(art, Article)
        assert art.source == 'GoodFeed'
        assert art.title == 'Test Article'
        assert art.link == 'https://example.com/article'

    def test_article_not_printed_during_fetch(self, capsys):
        entries = [_make_entry(title='My Title', link='https://example.com/x')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        captured = capsys.readouterr()
        assert 'My Title' not in captured.out
        assert 'https://example.com/x' not in captured.out

    def test_old_articles_excluded(self):
        entries = [_make_entry(published_parsed=OLD_STRUCT)]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert articles == []
        assert errors == []

    def test_description_populated(self):
        entries = [_make_entry(summary='Test summary')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, _ = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert articles[0].description == 'Test summary'

    def test_no_updates_returns_empty_silently(self, capsys):
        """All entries are old — fetch_feed returns ([], []) without printing."""
        entries = [_make_entry(published_parsed=OLD_STRUCT)]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert articles == []
        assert errors == []
        captured = capsys.readouterr()
        assert 'No update in the last' not in captured.out


# ---------------------------------------------------------------------------
# fetch_feed — empty / broken article link
# ---------------------------------------------------------------------------


class TestFetchFeedBrokenLink:
    def test_empty_link_skipped_with_error(self):
        entries = [_make_entry(link='')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        assert 'broken link' in errors[0].message.lower() or 'empty' in errors[0].message.lower()

    def test_non_http_link_skipped_with_error(self):
        entries = [_make_entry(link='ftp://example.com/article')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_broken_link_error_contains_source(self):
        entries = [_make_entry(link='')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            _, errors = fetch_feed('MySrc', 'https://example.com/rss', SINCE)

        assert errors[0].source == 'MySrc'

    def test_broken_link_error_contains_published_time(self):
        entries = [_make_entry(link='')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            _, errors = fetch_feed('MySrc', 'https://example.com/rss', SINCE)

        # The error message should contain an ISO timestamp
        assert 'T' in errors[0].message  # ISO 8601 datetime contains 'T'


# ---------------------------------------------------------------------------
# fetch_feed — malformed / missing published time
# ---------------------------------------------------------------------------


class TestFetchFeedMalformedPublished:
    def test_missing_published_skipped_with_error(self):
        entry = _make_entry()
        entry['published_parsed'] = None
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed([entry])),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_malformed_published_skipped_with_error(self):
        entry = _make_entry()
        entry['published_parsed'] = 'not-a-struct'
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed([entry])),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_malformed_published_error_contains_title_and_link(self):
        entry = _make_entry(title='Bad Entry', link='https://example.com/bad')
        entry['published_parsed'] = None
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed([entry])),
        ):
            _, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert 'Bad Entry' in errors[0].message
        assert 'https://example.com/bad' in errors[0].message


# ---------------------------------------------------------------------------
# _parse_entries — private article link (SSRF guard)
# ---------------------------------------------------------------------------


class TestParseEntriesArticlePrivateLink:
    def test_private_article_link_skipped(self):
        entries = [_make_entry(link='http://192.168.1.1/article')]
        articles, errors = _parse_entries('Src', entries, SINCE)
        assert articles == []
        assert len(errors) == 1
        assert 'Private' in errors[0].message

    def test_private_article_link_error_contains_source(self):
        entries = [_make_entry(link='http://10.0.0.1/article')]
        _, errors = _parse_entries('MySrc', entries, SINCE)
        assert errors[0].source == 'MySrc'

    def test_private_article_link_via_fetch_feed(self):
        """Ensure private article links are also caught through fetch_feed."""
        entries = [_make_entry(link='http://127.0.0.1/article')]
        with (
            patch('feed_fetcher.requests.get', return_value=_mock_response()),
            patch('feed_fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)
        assert articles == []
        assert any('Private' in e.message for e in errors)
