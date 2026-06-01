"""Shared data structures: Article and FeedError."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Article:
    """A parsed RSS article within the time window."""

    source: str
    title: str
    link: str
    description: Optional[str]
    published: datetime
    summary: Optional[str] = None
    score: Optional[int] = None


@dataclass
class FeedError:
    """An error collected during feed fetching or parsing."""

    source: str
    message: str
    jina_content: Optional[str] = None
