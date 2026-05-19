from __future__ import annotations

import socket
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rss_fetcher import (
    _is_private_host,
    _parse_published,
    fetch_feed,
    is_techmeme,
    strip_html,
    validate_feed_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    title: str = "Test Article",
    link: str = "https://example.com/article",
    summary: str = "Plain summary",
    published_parsed: tuple | None = (2024, 1, 15, 10, 30, 0, 0, 15, 0),
) -> SimpleNamespace:
    """Return a minimal feedparser-like entry object."""
    ns = SimpleNamespace(title=title, link=link, summary=summary)
    ns.published_parsed = published_parsed
    return ns


def _make_feed_result(entries: list, bozo: bool = False) -> MagicMock:
    result = MagicMock()
    result.bozo = bozo
    result.bozo_exception = Exception("parse error") if bozo else None
    result.entries = entries
    return result


# ---------------------------------------------------------------------------
# validate_feed_url
# ---------------------------------------------------------------------------

class TestValidateFeedUrl:
    def test_valid_https_url(self):
        with patch("rss_fetcher._is_private_host", return_value=False):
            assert validate_feed_url("https://example.com/feed") is True

    def test_valid_http_url(self):
        with patch("rss_fetcher._is_private_host", return_value=False):
            assert validate_feed_url("http://example.com/feed") is True

    @pytest.mark.parametrize("url", [
        "ftp://example.com/feed",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
        "not-a-url",
        "//example.com/feed",  # scheme-relative, no scheme
    ])
    def test_invalid_scheme_rejected(self, url: str):
        assert validate_feed_url(url) is False

    @pytest.mark.parametrize("private_ip", [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
    ])
    def test_private_ip_rejected(self, private_ip: str, capsys):
        with patch("socket.gethostbyname", return_value=private_ip):
            result = validate_feed_url("https://internal.host/feed")
        assert result is False
        assert "[WARNING]" in capsys.readouterr().out

    def test_dns_failure_treated_as_non_private(self):
        # Unresolvable host → _is_private_host returns False → URL passes
        with patch("socket.gethostbyname", side_effect=socket.gaierror):
            assert validate_feed_url("https://nonexistent.invalid/feed") is True

    def test_url_missing_hostname_rejected(self):
        assert validate_feed_url("https:///no-host") is False

    def test_warning_printed_for_invalid_scheme(self, capsys):
        validate_feed_url("ftp://example.com/feed")
        assert "[WARNING]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _is_private_host (direct — covers IPv6 and ValueError branches)
# ---------------------------------------------------------------------------

class TestIsPrivateHost:
    @pytest.mark.parametrize("ipv6_addr", [
        "::1",        # loopback
        "fc00::1",    # unique local (fc00::/7)
        "fd00::1",    # unique local (fd00:: also in fc00::/7)
    ])
    def test_ipv6_private_addresses_detected(self, ipv6_addr: str):
        with patch("socket.gethostbyname", return_value=ipv6_addr):
            assert _is_private_host("internal.host") is True

    def test_ipaddress_value_error_returns_false(self):
        # gethostbyname returns something ip_address() can't parse
        with patch("socket.gethostbyname", return_value="not-an-ip"):
            assert _is_private_host("weird.host") is False

    def test_public_ipv4_returns_false(self):
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            assert _is_private_host("dns.google") is False


# ---------------------------------------------------------------------------
# is_techmeme
# ---------------------------------------------------------------------------

class TestIsTechmeme:
    @pytest.mark.parametrize("url,expected", [
        ("https://www.techmeme.com/feed.xml", True),
        ("https://techmeme.com/feed", True),
        ("https://news.ycombinator.com/rss", False),
        ("https://developers.googleblog.com/feeds/posts/default/-/AI/", False),
        ("", False),
    ])
    def test_detection(self, url: str, expected: bool):
        assert is_techmeme(url) == expected


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_basic_tags(self):
        result = strip_html("<p>Hello <b>world</b></p>")
        assert "<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_plain_text_returned_unchanged(self):
        assert strip_html("Just plain text") == "Just plain text"

    def test_empty_string_returns_empty(self):
        assert strip_html("") == ""

    def test_nested_tags_stripped(self):
        html = '<div><a href="https://example.com">Link</a> and more</div>'
        result = strip_html(html)
        assert "<" not in result
        assert "Link" in result
        assert "and more" in result

    def test_anchor_tags_stripped_text_preserved(self):
        result = strip_html('<a href="https://example.com">Click here</a>')
        assert "Click here" in result
        assert "href" not in result

    def test_whitespace_collapsed(self):
        result = strip_html("<p>  spaces  </p>")
        assert result == "spaces"


# ---------------------------------------------------------------------------
# _parse_published
# ---------------------------------------------------------------------------

class TestParsePublished:
    def test_valid_tuple_returns_utc_datetime(self):
        entry = SimpleNamespace(published_parsed=(2024, 1, 15, 10, 30, 0, 0, 15, 0))
        result = _parse_published(entry)
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result.tzinfo == timezone.utc

    def test_none_published_parsed_returns_min(self):
        entry = SimpleNamespace(published_parsed=None)
        result = _parse_published(entry)
        assert result == datetime.min.replace(tzinfo=timezone.utc)
        assert result.tzinfo == timezone.utc

    def test_missing_attribute_returns_min(self):
        entry = SimpleNamespace()  # no published_parsed attribute
        result = _parse_published(entry)
        assert result == datetime.min.replace(tzinfo=timezone.utc)

    def test_result_is_always_timezone_aware(self):
        entry = SimpleNamespace(published_parsed=(2023, 6, 1, 0, 0, 0, 0, 152, 0))
        result = _parse_published(entry)
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# fetch_feed
# ---------------------------------------------------------------------------

class TestFetchFeed:
    def test_normal_feed_returns_articles(self):
        entry = _make_entry()
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert len(articles) == 1
        assert articles[0].title == "Test Article"
        assert articles[0].url == "https://example.com/article"
        assert articles[0].is_techmeme is False

    def test_techmeme_feed_strips_html_in_clean_summary(self):
        entry = _make_entry(
            link="https://www.techmeme.com/article",
            summary="<p>Summary with <b>HTML</b></p>",
        )
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://www.techmeme.com/feed.xml")
        assert articles[0].is_techmeme is True
        assert "<" not in articles[0].clean_summary
        assert articles[0].raw_summary == "<p>Summary with <b>HTML</b></p>"

    def test_non_techmeme_preserves_raw_summary_as_clean(self):
        entry = _make_entry(summary="<p>Raw HTML kept</p>")
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles[0].clean_summary == "<p>Raw HTML kept</p>"

    def test_entry_missing_title_is_skipped(self):
        entry = _make_entry(title="")
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles == []

    def test_entry_missing_link_is_skipped(self):
        entry = _make_entry(link="")
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles == []

    def test_bozo_feed_prints_warning_still_parses(self, capsys):
        entry = _make_entry()
        with patch("feedparser.parse", return_value=_make_feed_result([entry], bozo=True)):
            articles = fetch_feed("https://example.com/feed.xml")
        assert "[WARNING]" in capsys.readouterr().out
        assert len(articles) == 1  # valid entries still returned

    def test_empty_feed_returns_empty_list(self):
        with patch("feedparser.parse", return_value=_make_feed_result([])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles == []

    def test_published_is_utc_aware(self):
        entry = _make_entry()
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles[0].published.tzinfo == timezone.utc

    def test_source_feed_set_to_feed_url(self):
        entry = _make_entry()
        url = "https://example.com/feed.xml"
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed(url)
        assert articles[0].source_feed == url

    def test_entry_with_none_published_uses_fallback(self):
        entry = _make_entry(published_parsed=None)
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles[0].published == datetime.min.replace(tzinfo=timezone.utc)

    def test_multiple_entries_all_returned(self):
        entries = [_make_entry(title=f"Article {i}", link=f"https://example.com/{i}") for i in range(5)]
        with patch("feedparser.parse", return_value=_make_feed_result(entries)):
            articles = fetch_feed("https://example.com/feed.xml")
        assert len(articles) == 5

    def test_entry_uses_description_when_summary_empty(self):
        entry = SimpleNamespace(
            title="Title",
            link="https://example.com/article",
            summary="",
            description="Fallback description text",
            published_parsed=(2024, 1, 15, 10, 30, 0, 0, 15, 0),
        )
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles[0].raw_summary == "Fallback description text"

    def test_entry_raw_summary_empty_when_both_missing(self):
        entry = SimpleNamespace(
            title="Title",
            link="https://example.com/article",
            summary="",
            description="",
            published_parsed=(2024, 1, 15, 10, 30, 0, 0, 15, 0),
        )
        with patch("feedparser.parse", return_value=_make_feed_result([entry])):
            articles = fetch_feed("https://example.com/feed.xml")
        assert articles[0].raw_summary == ""
