"""HTML digest generation for newsletter-style output."""

import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path

from config import TIME_RANGE_HOURS
from validators import is_http_url
from models import Article, FeedError


def _format_date(now: datetime) -> str:
    """Format a human-readable date (for example: "May 26, 2026")."""
    return now.strftime('%B %d, %Y')


_CSS = (
    'body{margin:0;padding:0;background:#f5f6f8;color:#111;font-family:georgia,serif;}'
    'table{border-collapse:collapse;}'
    '.wrap{width:100%;max-width:600px;margin:24px auto;background:#fff;}'
    '.header{padding:18px 0 12px 0;border-bottom:1px solid #dcdcdc;}'
    '.title{margin:0;font:700 32px/36px georgia,serif;color:#286ed0;}'
    '.date{margin:6px 0 0 0;font:400 14px/20px arial,sans-serif;color:#666;}'
    '.intro{margin:14px 0 8px 0;font:italic 400 18px/24px georgia,serif;color:#333;}'
    '@media (max-width:480px){'
    '.wrap{margin:0 auto;}'
    '.pad{padding-left:14px!important;padding-right:14px!important;}'
    '.title{font-size:28px;line-height:32px;}'
    '}'
)


def _safe_href(link: str) -> str:
    """Allow only http/https links for anchors; return empty string otherwise."""
    if is_http_url(link):
        return link
    return ''


def _render_head(title: str, date_str: str) -> str:
    """Render the <head> block and opening body/wrapper tags."""
    escaped_title = escape(title)
    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<!--[if gte mso 9]><xml>'
        '<o:OfficeDocumentSettings><o:AllowPNG/></o:OfficeDocumentSettings>'
        '</xml><![endif]-->'
        f'<style>{_CSS}</style>'
        '</head>'
        '<body>'
        '<table role="presentation" width="100%"><tr><td align="center">'
        '<table role="presentation" class="wrap"><tr><td class="pad" style="padding:0 24px;">'
        f'<div class="header"><h1 class="title">{escaped_title}</h1>'
        f'<p class="date">{date_str}</p></div>'
        f'<p class="intro">Updates from the past {TIME_RANGE_HOURS} hours, sorted by AI.</p>'
    )


def _render_article_row(article: Article) -> str:
    """Render a single article as a table row."""
    article_title = escape(article.title or '')
    article_link = escape(_safe_href(article.link or ''))
    summary_text = article.summary if article.summary is not None else (article.description or '')
    article_summary = escape(summary_text)
    article_source = escape(article.source or '')
    return (
        '<tr><td style="border-top:1px solid #dcdcdc;padding:20px 0 18px 0;">'
        '<h3 style="margin:0 0 10px 0;font:700 20px/25px georgia,serif;color:#000;">'
        f'<a href="{article_link}" style="color:#000;text-decoration:none;">{article_title}</a>'
        '</h3>'
        '<p style="margin:0 0 10px 0;font:400 17px/22.5px georgia,serif;color:#333;">'
        f'{article_summary}</p>'
        '<p style="margin:0;font:600 13px/18px arial,sans-serif;color:#000;">'
        f'Source: {article_source}</p>'
        '</td></tr>'
    )


def _render_articles(articles: list[Article]) -> str:
    """Render all article rows, or a placeholder when the list is empty."""
    if not articles:
        return (
            '<tr><td style="border-top:1px solid #dcdcdc;padding:20px 0 18px 0;">'
            '<p style="margin:0;font:400 17px/22.5px georgia,serif;color:#333;">'
            'No updates in the selected time window.</p></td></tr>'
        )
    return ''.join(_render_article_row(a) for a in articles)


def _render_details(errors: list[FeedError], silent_sources: list[str]) -> str:
    """Render the no-update / error block, or empty string when both lists are empty."""
    rows: list[str] = []
    for source in silent_sources:
        rows.append(
            '<li style="margin:0 0 6px 0;">'
            f'{escape(source)}: No update in the past {TIME_RANGE_HOURS} hours.</li>'
        )
    for error in errors:
        rows.append(
            '<li style="margin:0 0 6px 0;">'
            f'{escape(error.source)}: {escape(error.message)}</li>'
        )
    if not rows:
        return ''
    return (
        '<tr><td style="border-top:1px solid #dcdcdc;padding:14px 0 6px 0;">'
        '<p style="margin:0 0 8px 0;font:600 13px/18px arial,sans-serif;color:#000;">'
        'Notes:</p>'
        '<ul style="margin:0;padding-left:20px;font:400 13px/18px arial,sans-serif;color:#333;">'
        + ''.join(rows)
        + '</ul></td></tr>'
    )


def generate_html(
    articles: list[Article],
    errors: list[FeedError],
    silent_sources: list[str],
    title: str,
    now: datetime,
) -> str:
    """Assemble a styled HTML digest page and return it as a string."""
    return (
        _render_head(title, _format_date(now))
        + '<table role="presentation" width="100%">'
        + _render_articles(articles)
        + _render_details(errors, silent_sources)
        + '</table>'
        + '</td></tr></table></td></tr></table></body></html>'
    )


def write_digest(html: str, output_path: str) -> Path:
    """Write *html* to *output_path* and return the resolved path.

    The resolved path must remain inside the current working directory to
    prevent path-traversal attacks when a future CLI ``--output`` flag is added.

    Raises :class:`ValueError` if *output_path* escapes the working directory.
    """
    path: Path = Path(output_path).resolve()
    allowed_dir: Path = Path.cwd().resolve()
    if not path.is_relative_to(allowed_dir):
        raise ValueError(f'Output path escapes working directory: {path}')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


def open_digest(path: Path) -> None:
    """Open *path* in the system default browser via a ``file://`` URI."""
    webbrowser.open(path.as_uri())
