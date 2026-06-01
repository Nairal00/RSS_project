"""Tests for html_generator.generate_html."""

from datetime import datetime, timezone

from html_generator import generate_html
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
    assert 'Top stories from the past 24 hours, sorted by AI.' in html
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

    assert 'No scored stories in the selected time window.' in html
    assert 'Errors: 0.' in html


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
