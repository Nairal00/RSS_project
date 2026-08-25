"""Tests for html_generator.generate_html."""

from datetime import datetime, timezone
from unittest.mock import patch

from config import TIME_RANGE_HOURS
from html_generator import generate_html, open_digest, write_digest
from models import Article, FeedError


def _article(
    title: str = 'Title',
    link: str = 'https://example.com/post',
    summary: str | None = 'Summary text',
    description: str | None = 'Description text',
    source: str = 'Example Source',
) -> Article:
    return Article(
        source=source,
        title=title,
        link=link,
        description=description,
        published=datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
        summary=summary,
        score=1,
    )


def test_generate_html_contains_required_structure() -> None:
    html = generate_html(
        articles=[_article()],
        errors=[],
        silent_sources=[],
        title='Daily Digest',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert '<!DOCTYPE html>' in html
    assert '<meta charset="UTF-8">' in html
    assert 'max-width:600px' in html
    assert '#dcdcdc' in html
    assert '#286ed0' in html
    assert '@media (max-width:480px)' in html
    assert f'Updates from the past {TIME_RANGE_HOURS} hours, sorted by AI.' in html
    assert 'May 26, 2026' in html


def test_generate_html_escapes_external_strings() -> None:
    article = _article(
        title='<script>alert(1)</script>',
        link='https://evil.example.com/?q="x"<y>',
        summary='sum <b>unsafe</b> & stuff',
        source='source <img src=x onerror=alert(1)>',
    )
    error = FeedError(source='err<source>', message='bad <tag> & "quote"')

    html = generate_html(
        articles=[article],
        errors=[error],
        silent_sources=['silent <feed>'],
        title='Digest <unsafe>',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'source <img src=x onerror=alert(1)>' not in html
    assert 'source &lt;img src=x onerror=alert(1)&gt;' in html
    assert 'bad <tag>' not in html
    assert 'bad &lt;tag&gt; &amp; &quot;quote&quot;' in html
    assert 'silent <feed>' not in html
    assert 'silent &lt;feed&gt;' in html
    assert 'https://evil.example.com/?q="x"<y>' not in html
    assert 'href="https://evil.example.com/?q=&quot;x&quot;&lt;y&gt;"' in html


def test_generate_html_handles_empty_articles() -> None:
    html = generate_html(
        articles=[],
        errors=[],
        silent_sources=[],
        title='Daily Digest',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert 'No updates in the selected time window.' in html


def test_generate_html_uses_description_when_summary_is_none() -> None:
    article = _article(summary=None, description='Fallback description from feed')
    html = generate_html(
        articles=[article],
        errors=[],
        silent_sources=[],
        title='Daily Digest',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert 'Fallback description from feed' in html


def test_generate_html_details_heading() -> None:
    html = generate_html(
        articles=[],
        errors=[FeedError(source='Feed A', message='timeout')],
        silent_sources=['Feed B'],
        title='Daily Digest',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert 'Notes:' in html
    


def test_generate_html_rejects_non_http_href_scheme() -> None:
    article = _article(link='javascript:alert(1)')
    html = generate_html(
        articles=[article],
        errors=[],
        silent_sources=[],
        title='Daily Digest',
        now=datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc),
    )

    assert 'javascript:alert(1)' not in html
    assert 'href=""' in html


# ---------------------------------------------------------------------------
# write_digest
# ---------------------------------------------------------------------------


def test_write_digest_writes_html_to_resolved_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output_file = tmp_path / 'output.html'
    result = write_digest('<html>test</html>', str(output_file))
    assert result == output_file.resolve()
    assert output_file.read_text(encoding='utf-8') == '<html>test</html>'


def test_write_digest_returns_absolute_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output_file = tmp_path / 'digest.html'
    result = write_digest('<html/>', str(output_file))
    assert result.is_absolute()


def test_write_digest_overwrites_existing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output_file = tmp_path / 'digest.html'
    output_file.write_text('old content', encoding='utf-8')
    write_digest('new content', str(output_file))
    assert output_file.read_text(encoding='utf-8') == 'new content'


# ---------------------------------------------------------------------------
# open_digest
# ---------------------------------------------------------------------------


def test_open_digest_calls_webbrowser_open(tmp_path) -> None:
    path = tmp_path / 'digest.html'
    path.write_text('<html/>', encoding='utf-8')
    with patch('html_generator.webbrowser.open') as mock_open_browser:
        open_digest(path)
    mock_open_browser.assert_called_once_with(path.as_uri())


def test_open_digest_uses_file_uri(tmp_path) -> None:
    path = tmp_path / 'digest.html'
    path.write_text('<html/>', encoding='utf-8')
    captured_uri = []
    with patch('html_generator.webbrowser.open', side_effect=lambda uri: captured_uri.append(uri)):
        open_digest(path)
    assert captured_uri[0].startswith('file://')
