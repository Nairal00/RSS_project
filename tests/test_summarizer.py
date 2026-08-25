"""Tests for summarizer: call_deepseek, _redact, and build_deepseek_client_from_env."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from summarizer import _redact, build_deepseek_client_from_env, call_deepseek


# ---------------------------------------------------------------------------
# _redact
# ---------------------------------------------------------------------------


class TestRedact:
    def test_replaces_secret_in_text(self):
        assert _redact('error: sk-abc123 is invalid', 'sk-abc123') == 'error: <redacted> is invalid'

    def test_empty_secret_returns_text_unchanged(self):
        assert _redact('some message', '') == 'some message'


# ---------------------------------------------------------------------------
# build_deepseek_client_from_env
# ---------------------------------------------------------------------------


class TestBuildDeepseekClientFromEnv:
    def test_missing_key_exits_with_code_1(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch('summarizer.load_dotenv'):
                with pytest.raises(SystemExit) as exc_info:
                    build_deepseek_client_from_env()
        assert exc_info.value.code == 1

    def test_missing_key_prints_error(self, capsys):
        with patch.dict(os.environ, {}, clear=True):
            with patch('summarizer.load_dotenv'):
                with pytest.raises(SystemExit):
                    build_deepseek_client_from_env()
        assert 'DEEPSEEK_API_KEY' in capsys.readouterr().out

    def test_returns_client_when_key_present(self):
        mock_client = MagicMock()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test-key'}):
            with patch('summarizer.load_dotenv'):
                with patch('summarizer.OpenAI', return_value=mock_client) as mock_ctor:
                    result = build_deepseek_client_from_env()
        assert result is mock_client
        mock_ctor.assert_called_once()

    def test_sdk_exception_is_redacted_before_print(self, capsys):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-secret'}):
            with patch('summarizer.load_dotenv'):
                with patch('summarizer.OpenAI', side_effect=Exception('bad sk-secret token')):
                    with pytest.raises(SystemExit):
                        build_deepseek_client_from_env()
        output = capsys.readouterr().out
        assert 'sk-secret' not in output
        assert '<redacted>' in output

    def test_sdk_exception_exits_with_code_1(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('summarizer.load_dotenv'):
                with patch('summarizer.OpenAI', side_effect=Exception('init failed')):
                    with pytest.raises(SystemExit) as exc_info:
                        build_deepseek_client_from_env()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# call_deepseek
# ---------------------------------------------------------------------------


def _mock_client(api_key: str = 'sk-test') -> MagicMock:
    client = MagicMock()
    client.api_key = api_key
    return client


def _mock_response(summary: str = 'A summary', score: int = 1) -> MagicMock:
    """Build a minimal mock of the OpenAI chat completion response."""
    msg = MagicMock()
    msg.content = json.dumps({'summary': summary, 'score': score})
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestCallDeepseek:
    def test_valid_response_returns_summary_and_score(self):
        client = _mock_client()
        client.chat.completions.create.return_value = _mock_response('Great article', 1)
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert summary == 'Great article'
        assert score == 1
        assert error is None

    def test_score_zero_accepted(self):
        client = _mock_client()
        client.chat.completions.create.return_value = _mock_response('Boring article', 0)
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert score == 0
        assert error is None

    def test_malformed_json_retries_then_returns_error(self):
        client = _mock_client()
        msg = MagicMock()
        msg.content = 'not json {'
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert summary is None
        assert score is None
        assert error is not None
        assert client.chat.completions.create.call_count == 2

    def test_null_summary_retries_then_returns_error(self):
        client = _mock_client()
        msg = MagicMock()
        msg.content = json.dumps({'summary': None, 'score': 1})
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert summary is None
        assert error is not None
        assert client.chat.completions.create.call_count == 2

    def test_score_out_of_range_retries_then_returns_error(self):
        client = _mock_client()
        msg = MagicMock()
        msg.content = json.dumps({'summary': 'ok', 'score': 5})
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert summary is None
        assert error is not None
        assert 'out of range' in error.message or '5' in error.message
        assert client.chat.completions.create.call_count == 2

    def test_api_exception_retries_then_returns_error(self):
        client = _mock_client()
        client.chat.completions.create.side_effect = Exception('connection refused')
        summary, score, error = call_deepseek(client, 'content', 'Src', 'Title')
        assert summary is None
        assert error is not None
        assert client.chat.completions.create.call_count == 2

    def test_api_exception_redacts_key_in_error(self, capsys):
        client = _mock_client(api_key='sk-secret-key')
        client.chat.completions.create.side_effect = Exception('invalid sk-secret-key token')
        call_deepseek(client, 'content', 'Src', 'Title')
        output = capsys.readouterr().out
        assert 'sk-secret-key' not in output
        assert '<redacted>' in output

    def test_content_truncated_to_max_chars(self):
        from config import MAX_CONTENT_CHARS
        client = _mock_client()
        client.chat.completions.create.return_value = _mock_response()
        long_content = 'x' * (MAX_CONTENT_CHARS + 1000)
        call_deepseek(client, long_content, 'Src', 'Title')
        call_args = client.chat.completions.create.call_args
        user_msg = call_args[1]['messages'][1]['content']
        assert len(user_msg) <= MAX_CONTENT_CHARS + 50  # allow for <article> tags

    def test_error_message_contains_source_and_title(self):
        client = _mock_client()
        client.chat.completions.create.side_effect = Exception('fail')
        _, _, error = call_deepseek(client, 'content', 'MySrc', 'MyTitle')
        assert 'MySrc' in error.message
        assert 'MyTitle' in error.message
