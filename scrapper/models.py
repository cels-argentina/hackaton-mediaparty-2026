from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Article:
    source: str
    url: str
    title: str
    description: str = ""
    author: str = ""
    published: datetime | None = None
    body: str = ""
    body_truncated: bool = False

    def with_body(self, body: str) -> "Article":
        return replace(self, body=body)


class ArticleRepository(Protocol):
    """Contrato de persistencia (DIP): el scraper no conoce la DB concreta."""

    async def is_seen(self, url: str) -> bool: ...

    async def mark_seen(self, article: Article, relevant: bool = True) -> None: ...
