"""Tests for pipeline.collect_scored_articles."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from models import Article, FeedError
from pipeline import collect_scored_articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(hours=24)


def _article(
    source: str = 'TestSource',
    title: str = 'Test Article',
    link: str = 'https://example.com/article',
    published: datetime | None = None,
) -> Article:
    return Article(
        source=source,
        title=title,
        link=link,
        description='desc',
        published=published or (NOW - timedelta(hours=1)),
    )


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.api_key = 'sk-test'
    return client


# ---------------------------------------------------------------------------
# collect_scored_articles — basic happy path
# ---------------------------------------------------------------------------


class TestCollectScoredArticlesHappyPath:
    def test_returns_scored_articles(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('Src=https://example.com/rss\n', encoding='utf-8')
        art = _article()

        with (
            patch('pipeline.load_feeds', return_value={'Src': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([art], [])),
            patch('pipeline.fetch_article_content', return_value=('content text', None)),
            patch('pipeline.call_deepseek', return_value=('A summary', 1, None)),
        ):
            articles, errors, silent = collect_scored_articles(
                str(feeds_file), _mock_client(), SINCE, NOW
            )

        assert len(articles) == 1
        assert articles[0].summary == 'A summary'
        assert articles[0].score == 1
        assert errors == []
        assert silent == []

    def test_silent_source_when_no_articles_no_errors(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        feeds_file.write_text('Silent=https://example.com/rss\n', encoding='utf-8')

        with (
            patch('pipeline.load_feeds', return_value={'Silent': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([], [])),
        ):
            articles, errors, silent = collect_scored_articles(
                str(feeds_file), _mock_client(), SINCE, NOW
            )

        assert articles == []
        assert errors == []
        assert 'Silent' in silent

    def test_jina_error_skips_article(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        art = _article()
        jina_err = FeedError(source='Src', message='Jina failed')

        with (
            patch('pipeline.load_feeds', return_value={'Src': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([art], [])),
            patch('pipeline.fetch_article_content', return_value=(None, jina_err)),
        ):
            articles, errors, silent = collect_scored_articles(
                str(feeds_file), _mock_client(), SINCE, NOW
            )

        assert articles == []
        assert len(errors) == 1
        assert errors[0].message == 'Jina failed'

    def test_api_error_skips_article_and_attaches_content(self, tmp_path):
        feeds_file = tmp_path / 'feeds.txt'
        art = _article()
        api_err = FeedError(source='Src', message='API failed')

        with (
            patch('pipeline.load_feeds', return_value={'Src': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([art], [])),
            patch('pipeline.fetch_article_content', return_value=('cleaned text', None)),
            patch('pipeline.call_deepseek', return_value=(None, None, api_err)),
        ):
            articles, errors, silent = collect_scored_articles(
                str(feeds_file), _mock_client(), SINCE, NOW
            )

        assert articles == []
        assert len(errors) == 1
        assert errors[0].jina_content == 'cleaned text'


# ---------------------------------------------------------------------------
# collect_scored_articles — sorting
# ---------------------------------------------------------------------------


class TestCollectScoredArticlesSorting:
    def test_sorted_by_score_descending(self, tmp_path):
        art1 = _article(title='Low Score', published=NOW - timedelta(hours=1))
        art2 = _article(title='High Score', published=NOW - timedelta(hours=2))

        call_results = iter([
            ('Summary low', 0, None),
            ('Summary high', 1, None),
        ])

        with (
            patch('pipeline.load_feeds', return_value={'Src': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([art1, art2], [])),
            patch('pipeline.fetch_article_content', return_value=('content', None)),
            patch('pipeline.call_deepseek', side_effect=call_results),
        ):
            articles, _, _ = collect_scored_articles(
                'feeds.txt', _mock_client(), SINCE, NOW
            )

        assert articles[0].title == 'High Score'
        assert articles[1].title == 'Low Score'

    def test_tiebreaker_is_recency(self, tmp_path):
        recent = _article(title='Recent', published=NOW - timedelta(hours=1))
        older = _article(title='Older', published=NOW - timedelta(hours=5))

        call_results = iter([
            ('Summary', 1, None),
            ('Summary', 1, None),
        ])

        with (
            patch('pipeline.load_feeds', return_value={'Src': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([recent, older], [])),
            patch('pipeline.fetch_article_content', return_value=('content', None)),
            patch('pipeline.call_deepseek', side_effect=call_results),
        ):
            articles, _, _ = collect_scored_articles(
                'feeds.txt', _mock_client(), SINCE, NOW
            )

        assert articles[0].title == 'Recent'
        assert articles[1].title == 'Older'


# ---------------------------------------------------------------------------
# collect_scored_articles — same-source throttle
# ---------------------------------------------------------------------------


class TestCollectScoredArticlesThrottle:
    def test_sleep_called_between_same_source_articles(self):
        art1 = _article(source='SameSrc', title='Article 1')
        art2 = _article(source='SameSrc', title='Article 2')

        with (
            patch('pipeline.load_feeds', return_value={'SameSrc': 'https://example.com/rss'}),
            patch('pipeline.fetch_feed', return_value=([art1, art2], [])),
            patch('pipeline.fetch_article_content', return_value=('content', None)),
            patch('pipeline.call_deepseek', return_value=('Summary', 1, None)),
            patch('pipeline.time.sleep') as mock_sleep,
        ):
            collect_scored_articles('feeds.txt', _mock_client(), SINCE, NOW)

        mock_sleep.assert_called_once()

    def test_no_sleep_for_different_sources(self):
        art1 = _article(source='SrcA', title='Article 1')
        art2 = _article(source='SrcB', title='Article 2')

        with (
            patch('pipeline.load_feeds', return_value={
                'SrcA': 'https://a.example.com/rss',
                'SrcB': 'https://b.example.com/rss',
            }),
            patch('pipeline.fetch_feed', side_effect=[([art1], []), ([art2], [])]),
            patch('pipeline.fetch_article_content', return_value=('content', None)),
            patch('pipeline.call_deepseek', return_value=('Summary', 1, None)),
            patch('pipeline.time.sleep') as mock_sleep,
        ):
            collect_scored_articles('feeds.txt', _mock_client(), SINCE, NOW)

        mock_sleep.assert_not_called()
