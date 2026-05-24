"""Tests for Sprint 1 & Sprint 2: RSS Feed Fetcher."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from fetcher import (
    TIME_RANGE_HOURS,
    Article,
    FeedError,
    _parse_entries,
    _parse_published,
    fetch_article_content,
    fetch_feed,
    get_utc_now,
    is_private_url,
    load_feeds,
    main,
    run,
    sanitize_filename,
    save_article,
    strip_markdown,
)

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
# is_private_url
# ---------------------------------------------------------------------------


class TestIsPrivateUrl:
    def test_localhost(self):
        assert is_private_url('http://localhost/feed') is True

    def test_127(self):
        assert is_private_url('http://127.0.0.1/feed') is True

    def test_10_x(self):
        assert is_private_url('http://10.0.0.1/feed') is True

    def test_172_private(self):
        assert is_private_url('http://172.16.0.1/feed') is True

    def test_192_168(self):
        assert is_private_url('http://192.168.1.1/feed') is True

    def test_link_local(self):
        assert is_private_url('http://169.254.1.1/feed') is True

    def test_ipv6_loopback(self):
        assert is_private_url('http://[::1]/feed') is True

    def test_public_ip(self):
        assert is_private_url('https://example.com/feed') is False

    def test_public_domain(self):
        assert is_private_url('https://openai.com/blog/rss.xml') is False

    def test_ipv4_mapped_ipv6_loopback(self):
        """::ffff:127.0.0.1 is an IPv4-mapped loopback — must be blocked."""
        assert is_private_url('http://[::ffff:127.0.0.1]/feed') is True

    def test_ipv4_mapped_ipv6_private(self):
        """::ffff:192.168.1.1 is an IPv4-mapped private address — must be blocked."""
        assert is_private_url('http://[::ffff:192.168.1.1]/feed') is True

    def test_ipv6_link_local(self):
        assert is_private_url('http://[fe80::1]/feed') is True

    def test_ipv6_ula(self):
        assert is_private_url('http://[fd00::1]/feed') is True

    def test_unspecified_ipv4(self):
        assert is_private_url('http://0.0.0.0/feed') is True

    def test_localhost_uppercase(self):
        assert is_private_url('http://LOCALHOST/feed') is True

    def test_172_boundary_public(self):
        """172.15.x.x is NOT in the 172.16.0.0/12 private range."""
        assert is_private_url('http://172.15.0.1/feed') is False

    def test_empty_url_treated_as_private(self):
        """Empty string has no hostname — must be treated as private."""
        assert is_private_url('') is True

    @pytest.mark.parametrize('url', [
        'http://127.0.0.1/feed',
        'http://127.255.255.255/feed',
        'http://10.0.0.1/feed',
        'http://10.255.255.255/feed',
        'http://172.16.0.1/feed',
        'http://172.31.255.255/feed',
        'http://192.168.0.1/feed',
        'http://169.254.1.1/feed',
        'http://0.0.0.0/feed',
        'http://[::1]/feed',
        'http://[fe80::1]/feed',
        'http://[fd00::1]/feed',
        'http://[::ffff:127.0.0.1]/feed',
        'http://[::ffff:10.0.0.1]/feed',
        'http://localhost/feed',
        'http://LOCALHOST/feed',
    ])
    def test_all_private_addresses_blocked(self, url):
        assert is_private_url(url) is True


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
        with patch('fetcher.requests.get') as mock_get:
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

        with patch('fetcher.requests.get', return_value=mock_response):
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

        with patch('fetcher.requests.get', return_value=mock_response):
            fetch_feed('BadFeed', 'https://bad.example.com/rss', SINCE)

        captured = capsys.readouterr()
        assert 'HTTP error' in captured.out

    def test_connection_error_logged(self):
        with patch('fetcher.requests.get', side_effect=requests.ConnectionError('timeout')):
            articles, errors = fetch_feed('BadFeed', 'https://bad.example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        assert 'Request error' in errors[0].message


# ---------------------------------------------------------------------------
# fetch_feed — empty feed
# ---------------------------------------------------------------------------


class TestFetchFeedEmpty:
    def test_empty_feed_prints_no_updates(self, capsys):
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed([])),
        ):
            articles, errors = fetch_feed('EmptyFeed', 'https://empty.example.com/rss', SINCE)

        assert articles == []
        assert errors == []
        captured = capsys.readouterr()
        assert 'No updates found' in captured.out


# ---------------------------------------------------------------------------
# fetch_feed — normal feed (articles within time window)
# ---------------------------------------------------------------------------


class TestFetchFeedNormal:
    def test_returns_articles(self):
        entries = [_make_entry()]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert len(articles) == 1
        assert errors == []
        art = articles[0]
        assert isinstance(art, Article)
        assert art.source == 'GoodFeed'
        assert art.title == 'Test Article'
        assert art.link == 'https://example.com/article'

    def test_article_printed_to_console(self, capsys):
        entries = [_make_entry(title='My Title', link='https://example.com/x')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        captured = capsys.readouterr()
        assert 'My Title' in captured.out
        assert 'https://example.com/x' in captured.out

    def test_old_articles_excluded(self):
        entries = [_make_entry(published_parsed=OLD_STRUCT)]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert articles == []
        assert errors == []

    def test_description_populated(self):
        entries = [_make_entry(summary='Test summary')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, _ = fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        assert articles[0].description == 'Test summary'

    def test_no_updates_in_range_message(self, capsys):
        """All entries are old — should print 'No updates in the last N hours'."""
        entries = [_make_entry(published_parsed=OLD_STRUCT)]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            fetch_feed('GoodFeed', 'https://good.example.com/rss', SINCE)

        captured = capsys.readouterr()
        assert 'No updates in the last' in captured.out


# ---------------------------------------------------------------------------
# fetch_feed — empty / broken article link
# ---------------------------------------------------------------------------


class TestFetchFeedBrokenLink:
    def test_empty_link_skipped_with_error(self):
        entries = [_make_entry(link='')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1
        assert 'broken link' in errors[0].message.lower() or 'empty' in errors[0].message.lower()

    def test_non_http_link_skipped_with_error(self):
        entries = [_make_entry(link='ftp://example.com/article')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_broken_link_error_contains_source(self):
        entries = [_make_entry(link='')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            _, errors = fetch_feed('MySrc', 'https://example.com/rss', SINCE)

        assert errors[0].source == 'MySrc'

    def test_broken_link_error_contains_published_time(self):
        entries = [_make_entry(link='')]
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
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
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed([entry])),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_malformed_published_skipped_with_error(self):
        entry = _make_entry()
        entry['published_parsed'] = 'not-a-struct'
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed([entry])),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)

        assert articles == []
        assert len(errors) == 1

    def test_malformed_published_error_contains_title_and_link(self):
        entry = _make_entry(title='Bad Entry', link='https://example.com/bad')
        entry['published_parsed'] = None
        with (
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed([entry])),
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
            patch('fetcher.requests.get', return_value=_mock_response()),
            patch('fetcher.feedparser.parse', return_value=_make_feed(entries)),
        ):
            articles, errors = fetch_feed('Src', 'https://example.com/rss', SINCE)
        assert articles == []
        assert any('Private' in e.message for e in errors)


# ---------------------------------------------------------------------------


class TestGetUtcNow:
    def test_returns_datetime(self):
        result = get_utc_now()
        assert isinstance(result, datetime)

    def test_is_utc(self):
        result = get_utc_now()
        assert result.tzinfo == timezone.utc

    def test_is_recent(self):
        before = datetime.now(timezone.utc)
        result = get_utc_now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


# ---------------------------------------------------------------------------
# is_private_url — urlparse exception path
# ---------------------------------------------------------------------------


class TestIsPrivateUrlException:
    def test_urlparse_exception_treated_as_private(self):
        with patch('fetcher.urlparse', side_effect=ValueError('invalid IPv6')):
            assert is_private_url('http://[invalid::]/') is True


# ---------------------------------------------------------------------------
# load_feeds — OSError path
# ---------------------------------------------------------------------------


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
# run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_returns_articles_and_errors(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('TestFeed=https://example.com/rss\n', encoding='utf-8')

        article = Article(
            source='TestFeed',
            title='Hello',
            link='https://example.com/1',
            description=None,
            published=NOW,
        )
        error = FeedError(source='TestFeed', message='some error')

        with (
            patch('fetcher.fetch_feed', return_value=([article], [error])),
            patch('fetcher.fetch_article_content', return_value=('content', None)),
            patch('fetcher.save_article', return_value='TestFeed_hello.md'),
        ):
            articles, errors = run(str(feeds_file))

        assert articles == [article]
        assert errors == [error]

    def test_run_fetch_article_error_collected(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('TestFeed=https://example.com/rss\n', encoding='utf-8')

        article = Article(
            source='TestFeed',
            title='Hello',
            link='https://example.com/1',
            description=None,
            published=NOW,
        )
        jina_error = FeedError(source='TestFeed', message='Jina无法读取网页信息')

        with (
            patch('fetcher.fetch_feed', return_value=([article], [])),
            patch('fetcher.fetch_article_content', return_value=(None, jina_error)),
        ):
            articles, errors = run(str(feeds_file))

        assert articles == [article]
        assert jina_error in errors

    def test_run_empty_feeds_file(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('# no feeds here\n', encoding='utf-8')
        articles, errors = run(str(feeds_file))
        assert articles == []
        assert errors == []


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_with_no_errors(self, capsys):
        with patch('fetcher.run', return_value=([], [])):
            main()
        captured = capsys.readouterr()
        assert 'error(s) collected' not in captured.out
        assert 'Collected errors:' not in captured.out

    def test_main_prints_error_summary(self, capsys):
        error = FeedError(source='X', message='oops')
        with patch('fetcher.run', return_value=([], [error])):
            main()
        captured = capsys.readouterr()
        assert '1 error(s) collected' in captured.out
        assert 'Collected errors:' in captured.out
        assert '- oops' in captured.out


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_basic_sanitization(self):
        result = sanitize_filename('Hello World', 'https://example.com')
        assert result == 'hello_world'

    def test_spaces_replaced_with_underscore(self):
        result = sanitize_filename('My Great Article', 'https://example.com')
        assert '_' in result
        assert ' ' not in result

    def test_special_chars_removed(self):
        result = sanitize_filename('Hello: World! (2024)', 'https://example.com')
        assert ':' not in result
        assert '!' not in result
        assert '(' not in result

    def test_truncated_to_50_chars(self):
        long_title = 'a' * 100
        result = sanitize_filename(long_title, 'https://example.com')
        assert len(result) <= 50

    def test_empty_title_falls_back_to_url_hash(self):
        result = sanitize_filename('', 'https://example.com/article')
        assert len(result) == 8
        assert result.isalnum()

    def test_non_ascii_title_falls_back_to_url_hash(self):
        # After removing non-[a-z0-9_] chars, should be empty → fall back to hash
        result = sanitize_filename('日本語タイトル', 'https://example.com/article')
        assert len(result) == 8

    def test_hash_fallback_is_deterministic(self):
        url = 'https://example.com/specific-article'
        result1 = sanitize_filename('', url)
        result2 = sanitize_filename('', url)
        assert result1 == result2

    def test_mixed_valid_and_invalid_chars(self):
        result = sanitize_filename('AI & ML: Top 10!', 'https://example.com')
        assert result == 'ai__ml_top_10'


# ---------------------------------------------------------------------------
# strip_markdown
# ---------------------------------------------------------------------------


class TestStripMarkdown:
    def test_removes_plain_image(self):
        text = 'Before ![alt text](https://img.example.com/pic.png) After'
        result = strip_markdown(text)
        assert '![' not in result
        assert 'Before' in result
        assert 'After' in result

    def test_removes_image_link(self):
        text = '[![alt](https://img.example.com/a.png)](https://example.com)'
        result = strip_markdown(text)
        assert '![' not in result
        assert result.strip() == ''

    def test_converts_hyperlink_to_text(self):
        text = 'Click [here](https://example.com) for more.'
        result = strip_markdown(text)
        assert 'here' in result
        assert 'https://example.com' not in result
        assert '[' not in result

    def test_removes_bold(self):
        text = 'This is **important** text.'
        result = strip_markdown(text)
        assert '**' not in result
        assert 'important' in result

    def test_removes_inline_code(self):
        text = 'Use `print()` function.'
        result = strip_markdown(text)
        assert '`' not in result
        assert 'print()' in result

    def test_plain_text_unchanged(self):
        text = 'Just plain text with no formatting.'
        result = strip_markdown(text)
        assert result == text


# ---------------------------------------------------------------------------
# fetch_article_content
# ---------------------------------------------------------------------------


def _make_article(
    source: str = 'TestSource',
    title: str = 'Test Article',
    link: str = 'https://example.com/article',
) -> Article:
    """Build a minimal Article for Sprint 2 testing."""
    return Article(
        source=source,
        title=title,
        link=link,
        description=None,
        published=NOW,
    )


def _mock_jina_response(text: str = 'Article content', status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response for Jina calls."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchArticleContent:
    def test_successful_fetch_returns_content(self):
        article = _make_article()
        mock_resp = _mock_jina_response(text='# Article\n\nSome content here.')
        with patch('fetcher.requests.get', return_value=mock_resp):
            content, error = fetch_article_content(article.source, article)
        assert content is not None
        assert error is None

    def test_successful_fetch_strips_markdown(self):
        article = _make_article()
        raw = 'Check ![img](https://img.example.com/a.png) and [click](https://x.com).'
        mock_resp = _mock_jina_response(text=raw)
        with patch('fetcher.requests.get', return_value=mock_resp):
            content, error = fetch_article_content(article.source, article)
        assert '![' not in content
        assert 'https://x.com' not in content
        assert 'click' in content

    def test_jina_http_error_returns_feed_error(self):
        article = _make_article()
        http_err = requests.HTTPError('503 Service Unavailable')
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        http_err.response = mock_resp
        mock_response = _mock_jina_response()
        mock_response.raise_for_status.side_effect = http_err
        with patch('fetcher.requests.get', return_value=mock_response):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert '503' in error.message

    def test_jina_request_exception_returns_feed_error(self):
        article = _make_article()
        with patch('fetcher.requests.get', side_effect=requests.ConnectionError('timeout')):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert 'Jina request error' in error.message

    def test_private_ip_rejected_before_jina(self):
        article = _make_article(link='http://192.168.1.1/article')
        with patch('fetcher.requests.get') as mock_get:
            content, error = fetch_article_content(article.source, article)
            mock_get.assert_not_called()
        assert content is None
        assert error is not None
        assert 'Rejected' in error.message

    def test_empty_jina_response_returns_error(self):
        article = _make_article()
        mock_resp = _mock_jina_response(text='   ')
        with patch('fetcher.requests.get', return_value=mock_resp):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert 'Jina无法读取网页信息' in error.message

    def test_empty_jina_response_no_file_saved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        article = _make_article()
        mock_resp = _mock_jina_response(text='')
        with patch('fetcher.requests.get', return_value=mock_resp):
            fetch_article_content(article.source, article)
        assert list(tmp_path.iterdir()) == []

    def test_jina_url_constructed_correctly(self):
        article = _make_article(link='https://example.com/some-article')
        mock_resp = _mock_jina_response(text='content')
        with patch('fetcher.requests.get', return_value=mock_resp) as mock_get:
            fetch_article_content(article.source, article)
        called_url = mock_get.call_args[0][0]
        assert called_url == 'https://r.jina.ai/https://example.com/some-article'

    def test_private_ip_prints_message(self, capsys):
        article = _make_article(link='http://10.0.0.1/article')
        fetch_article_content(article.source, article)
        captured = capsys.readouterr()
        assert 'Rejected' in captured.out


# ---------------------------------------------------------------------------
# save_article
# ---------------------------------------------------------------------------


class TestSaveArticle:
    def test_saves_file_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        filename = save_article('MySrc', 'My Title', 'https://example.com', 'content')
        assert (tmp_path / filename).exists()

    def test_filename_format(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        filename = save_article('MySrc', 'My Title', 'https://example.com', 'content')
        assert filename.startswith('MySrc_')
        assert filename.endswith('.md')

    def test_file_content_written(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        filename = save_article('MySrc', 'My Title', 'https://example.com', 'Hello world')
        text = (tmp_path / filename).read_text(encoding='utf-8')
        assert text == 'Hello world'

    def test_overwrites_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        save_article('MySrc', 'My Title', 'https://example.com', 'first')
        save_article('MySrc', 'My Title', 'https://example.com', 'second')
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].read_text(encoding='utf-8') == 'second'

    def test_empty_title_uses_hash_in_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        filename = save_article('MySrc', '', 'https://example.com/article', 'content')
        # filename should be MySrc_<8-char-hash>.md
        parts = filename.replace('.md', '').split('_', 1)
        assert parts[0] == 'MySrc'
        assert len(parts[1]) == 8


# ---------------------------------------------------------------------------
# strip_markdown — italic and edge cases
# ---------------------------------------------------------------------------


class TestStripMarkdownItalicAndEdge:
    def test_removes_italic_asterisk(self):
        text = 'This is *italic* text.'
        result = strip_markdown(text)
        assert '*' not in result
        assert 'italic' in result

    def test_removes_italic_underscore(self):
        text = 'This is _italic_ text.'
        result = strip_markdown(text)
        assert result == 'This is italic text.'

    def test_removes_double_underscore_bold(self):
        text = 'This is __bold__ text.'
        result = strip_markdown(text)
        assert '__' not in result
        assert 'bold' in result

    def test_empty_string_returns_empty(self):
        assert strip_markdown('') == ''

    def test_no_modification_to_plain_list_bullets(self):
        """A leading '*' on its own (list bullet) must not eat adjacent text."""
        text = '* item one\n* item two'
        result = strip_markdown(text)
        # Leading bullets are not touched by the italic regex (requires non-space after *)
        assert 'item one' in result
        assert 'item two' in result


# ---------------------------------------------------------------------------
# _parse_entries — empty list and mixed valid/invalid entries
# ---------------------------------------------------------------------------


class TestParseEntriesMixed:
    def test_empty_entries_returns_empty(self):
        articles, errors = _parse_entries('Src', [], SINCE)
        assert articles == []
        assert errors == []

    def test_mixed_valid_and_invalid_entries(self):
        """Valid and broken entries in the same feed are handled independently."""
        valid = _make_entry(title='Good', link='https://example.com/good')
        broken = _make_entry(title='Bad', link='')
        articles, errors = _parse_entries('Src', [valid, broken], SINCE)
        assert len(articles) == 1
        assert articles[0].title == 'Good'
        assert len(errors) == 1

    def test_multiple_valid_entries_all_returned(self):
        entries = [
            _make_entry(title='A', link='https://example.com/a'),
            _make_entry(title='B', link='https://example.com/b'),
            _make_entry(title='C', link='https://example.com/c'),
        ]
        articles, errors = _parse_entries('Src', entries, SINCE)
        assert len(articles) == 3
        assert errors == []

    def test_all_old_entries_returns_empty_no_errors(self):
        entries = [
            _make_entry(published_parsed=OLD_STRUCT),
            _make_entry(published_parsed=OLD_STRUCT),
        ]
        articles, errors = _parse_entries('Src', entries, SINCE)
        assert articles == []
        assert errors == []
