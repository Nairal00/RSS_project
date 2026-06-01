"""Tests for content_extractor: strip_markdown and fetch_article_content."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from content_extractor import fetch_article_content, strip_markdown
from models import Article, FeedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)


def _make_article(
    source: str = 'TestSource',
    title: str = 'Test Article',
    link: str = 'https://example.com/article',
) -> Article:
    """Build a minimal Article for testing."""
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


# ---------------------------------------------------------------------------
# fetch_article_content
# ---------------------------------------------------------------------------


class TestFetchArticleContent:
    def test_successful_fetch_returns_content(self):
        article = _make_article()
        mock_resp = _mock_jina_response(text='# Article\n\nSome content here.')
        with patch('content_extractor.requests.get', return_value=mock_resp):
            content, error = fetch_article_content(article.source, article)
        assert content is not None
        assert error is None

    def test_successful_fetch_strips_markdown(self):
        article = _make_article()
        raw = 'Check ![img](https://img.example.com/a.png) and [click](https://x.com).'
        mock_resp = _mock_jina_response(text=raw)
        with patch('content_extractor.requests.get', return_value=mock_resp):
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
        with patch('content_extractor.requests.get', return_value=mock_response):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert '503' in error.message

    def test_jina_request_exception_returns_feed_error(self):
        article = _make_article()
        with patch('content_extractor.requests.get', side_effect=requests.ConnectionError('timeout')):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert 'Jina request error' in error.message

    def test_private_ip_rejected_before_jina(self):
        article = _make_article(link='http://192.168.1.1/article')
        with patch('content_extractor.requests.get') as mock_get:
            content, error = fetch_article_content(article.source, article)
            mock_get.assert_not_called()
        assert content is None
        assert error is not None
        assert 'Rejected' in error.message

    def test_empty_jina_response_returns_error(self):
        article = _make_article()
        mock_resp = _mock_jina_response(text='   ')
        with patch('content_extractor.requests.get', return_value=mock_resp):
            content, error = fetch_article_content(article.source, article)
        assert content is None
        assert error is not None
        assert 'Jina无法读取网页信息' in error.message

    def test_empty_jina_response_no_file_saved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        article = _make_article()
        mock_resp = _mock_jina_response(text='')
        with patch('content_extractor.requests.get', return_value=mock_resp):
            fetch_article_content(article.source, article)
        assert list(tmp_path.iterdir()) == []

    def test_jina_url_constructed_correctly(self):
        article = _make_article(link='https://example.com/some-article')
        mock_resp = _mock_jina_response(text='content')
        with patch('content_extractor.requests.get', return_value=mock_resp) as mock_get:
            fetch_article_content(article.source, article)
        called_url = mock_get.call_args[0][0]
        assert called_url == 'https://r.jina.ai/https://example.com/some-article'

    def test_private_ip_prints_message(self, capsys):
        article = _make_article(link='http://10.0.0.1/article')
        fetch_article_content(article.source, article)
        captured = capsys.readouterr()
        assert 'Rejected' in captured.out

    def test_link_with_newline_control_char_rejected(self):
        """Links with \\r\\n must be blocked before Jina call."""
        article = _make_article(link='https://example.com/article\r\nX-Injected: value')
        with patch('content_extractor.requests.get') as mock_get:
            content, error = fetch_article_content(article.source, article)
            mock_get.assert_not_called()
        assert content is None
        assert error is not None
        assert 'control characters' in error.message

    def test_link_with_null_byte_rejected(self):
        article = _make_article(link='https://example.com/article\x00')
        with patch('content_extractor.requests.get') as mock_get:
            content, error = fetch_article_content(article.source, article)
            mock_get.assert_not_called()
        assert content is None
        assert error is not None
