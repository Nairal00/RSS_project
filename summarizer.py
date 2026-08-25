"""DeepSeek API summarization and scoring."""

import json
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, MAX_CONTENT_CHARS, SCORE_PROMPT
from models import FeedError


def _redact(text: str, secret: str) -> str:
    """Replace *secret* in *text* with ``'<redacted>'`` to prevent credential leaks."""
    if not secret:
        return text
    return text.replace(secret, '<redacted>')


def build_deepseek_client_from_env() -> OpenAI:
    """Load API key from env and return a configured OpenAI client for DeepSeek.

    Calls ``load_dotenv()`` first so a local ``.env`` file is honoured.
    Exits with ``sys.exit(1)`` if the key is missing or if the SDK constructor
    raises (exception message is redacted before printing).
    """
    load_dotenv()
    api_key: Optional[str] = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        print('Error: DEEPSEEK_API_KEY environment variable is not set.')
        sys.exit(1)
    try:
        return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
        print(f'Error initializing DeepSeek client: {_redact(str(exc), api_key)}')
        sys.exit(1)


def call_deepseek(
    client: OpenAI,
    content: str,
    source: str,
    title: str,
) -> tuple[Optional[str], Optional[int], Optional[FeedError]]:
    """Summarize and score *content* via the DeepSeek API. Retries once on any failure.

    Returns ``(summary, score, None)`` on success or ``(None, None, FeedError)`` after
    two failed attempts.  *score* is guaranteed to be ``0`` or ``1``.
    """
    content = content[:MAX_CONTENT_CHARS]
    last_error: str = f'[{source}] No attempts made for "{title}"'
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {'role': 'system', 'content': SCORE_PROMPT},
                    {'role': 'user', 'content': f'<article>\n{content.replace("</article>", "<\\/article>")}\n</article>'},
                ],
                response_format={'type': 'json_object'},
            )
            raw: str = response.choices[0].message.content or ''
            data: dict = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = (
                f'[{source}] Malformed JSON response for "{title}"'
                f' (attempt {attempt + 1}): {exc}'
            )
            print(last_error)
            continue
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            last_error = (
                f'[{source}] API error for "{title}"'
                f' (attempt {attempt + 1}): {_redact(str(exc), client.api_key)}'
            )
            print(last_error)
            continue

        summary = data.get('summary')
        score = data.get('score')

        if summary is None or score is None:
            last_error = (
                f'[{source}] Null summary or score for "{title}"'
                f' (attempt {attempt + 1})'
            )
            print(last_error)
            continue

        if score not in (0, 1):
            last_error = (
                f'[{source}] Score {score!r} out of range (0 or 1) for "{title}"'
                f' (attempt {attempt + 1})'
            )
            print(last_error)
            continue

        return str(summary), int(score), None

    return None, None, FeedError(source=source, message=last_error)
