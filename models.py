from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Article:
    title: str
    url: str
    raw_summary: str
    clean_summary: str
    published: datetime  # always timezone-aware UTC
    source_feed: str
    is_techmeme: bool
    is_ai_related: bool | None = None
    ai_summary: str | None = None
