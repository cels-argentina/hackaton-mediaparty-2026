"""Repositorio SQLite (implementa ArticleRepository). Consultas parametrizadas;
sqlite3 se ejecuta en un hilo para no bloquear el event loop."""
from __future__ import annotations
import asyncio
import sqlite3
from datetime import datetime, timezone
from models import Article

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    author TEXT NOT NULL,
    published TEXT,
    excerpt TEXT NOT NULL,
    body_truncated INTEGER NOT NULL,
    relevant INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL
)
"""


class SqliteArticleRepository:
    def __init__(self, path: str = "articles.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(articles)")
        }
        if "relevant" not in columns:
            self._conn.execute(
                "ALTER TABLE articles ADD COLUMN relevant INTEGER NOT NULL DEFAULT 1"
            )
        self._conn.commit()
        self._lock = asyncio.Lock()

    async def is_seen(self, url: str) -> bool:
        def q() -> bool:
            return self._conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone() is not None

        async with self._lock:
            return await asyncio.to_thread(q)

    async def mark_seen(self, article: Article, relevant: bool = True) -> None:
        def w() -> None:
            self._conn.execute(
                """INSERT OR IGNORE INTO articles
                   (url, source, title, description, author, published, excerpt,
                    body_truncated, relevant, first_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    article.url, article.source, article.title, article.description,
                    article.author,
                    article.published.isoformat() if article.published else None,
                    article.body, int(article.body_truncated), int(relevant),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(w)

    def close(self) -> None:
        self._conn.close()
