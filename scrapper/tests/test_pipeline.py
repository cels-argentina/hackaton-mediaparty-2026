import sys
from dataclasses import replace
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from http_client import FetchError  # noqa: E402
from models import Article  # noqa: E402
from scraper import FeedScraper  # noqa: E402
from settings import Settings  # noqa: E402
from sqlite_repository import SqliteArticleRepository  # noqa: E402

RSS = b"""<rss><channel>
<item><title>Gatillo f\xc3\xa1cil en La Plata</title><link>https://a.com/1</link></item>
<item><title>Deportes</title><link>https://a.com/2</link></item>
</channel></rss>"""


class FakeClient:
    async def get_bytes(self, url, accept="*/*"):
        if url.endswith("feed"):
            return RSS, "application/rss+xml"
        return b"<html><body><article>Texto. Mail: x@y.com</article></body></html>", "text/html"


@pytest.mark.asyncio
async def test_repository_roundtrip(tmp_path):
    repo = SqliteArticleRepository(str(tmp_path / "t.db"))
    art = Article(source="s", url="https://a.com/1", title="t")
    assert not await repo.is_seen(art.url)
    await repo.mark_seen(art)
    await repo.mark_seen(art)  # idempotente
    assert await repo.is_seen(art.url)
    await repo.mark_seen(Article(source="s", url="https://a.com/2", title="other"), relevant=False)
    assert repo._conn.execute(
        "SELECT relevant FROM articles WHERE url = ?", ("https://a.com/2",)
    ).fetchone() == (0,)
    repo.close()


@pytest.mark.asyncio
async def test_pipeline_filters_dedups_and_redacts(tmp_path):
    settings = replace(Settings(), rss_sources={"a": "https://a.com/feed"})
    repo = SqliteArticleRepository(str(tmp_path / "t.db"))
    scraper = FeedScraper(settings, FakeClient(), repo)
    result = await scraper.fetch_relevant_articles()
    assert [a.url for a in result] == ["https://a.com/1"]
    assert "x@y.com" not in result[0].body
    assert await scraper.fetch_relevant_articles() == []  # ya vistos
    repo.close()


@pytest.mark.asyncio
async def test_failed_article_is_retryable_and_later_candidate_is_processed():
    feed = b"""<rss><channel>
      <item><title>Gatillo f&#225;cil</title><link>https://a.com/1</link></item>
      <item><title>Sin coincidencia</title><link>https://a.com/2</link></item>
    </channel></rss>"""

    class FlakyClient:
        def __init__(self):
            self.failed_once = False
            self.article_requests = []

        async def get_bytes(self, url, accept="*/*"):
            if url.endswith("/feed"):
                return feed, "application/rss+xml"
            self.article_requests.append(url)
            if url.endswith("/1") and not self.failed_once:
                self.failed_once = True
                raise FetchError("fallo temporal")
            return b"<html><article>Texto</article></html>", "text/html"

    settings = replace(
        Settings(), rss_sources={"a": "https://a.com/feed"}, max_articles_per_run=1
    )
    client = FlakyClient()
    scraper = FeedScraper(settings, client)
    assert await scraper.fetch_relevant_articles() == []
    assert client.article_requests == ["https://a.com/1", "https://a.com/2"]

    one_item_feed = b"""<rss><channel>
      <item><title>Gatillo f&#225;cil</title><link>https://a.com/1</link></item>
    </channel></rss>"""

    class RetryClient:
        def __init__(self):
            self.failed = True

        async def get_bytes(self, url, accept="*/*"):
            if url.endswith("/feed"):
                return one_item_feed, "application/rss+xml"
            if self.failed:
                self.failed = False
                raise FetchError("fallo temporal")
            return b"<html><article>Texto</article></html>", "text/html"

    repo = SqliteArticleRepository(":memory:")
    retry_scraper = FeedScraper(settings, RetryClient(), repo)
    assert await retry_scraper.fetch_relevant_articles() == []
    assert not await repo.is_seen("https://a.com/1")
    assert len(await retry_scraper.fetch_relevant_articles()) == 1
    repo.close()


@pytest.mark.asyncio
async def test_charset_and_metadata_are_preserved_and_redacted(tmp_path):
    feed = b"""<rss><channel><item>
      <title>Contacto ana@example.org</title><link>https://a.com/1</link>
      <description>DNI 30.123.456</description><author>autor@example.org</author>
    </item></channel></rss>"""

    class EncodedClient:
        async def get_bytes(self, url, accept="*/*"):
            if url.endswith("/feed"):
                return feed, "application/rss+xml"
            return (
                "<html><article>gatillo fácil teléfono 11 1234-5678</article></html>".encode(
                    "iso-8859-1"
                ),
                "text/html; charset=iso-8859-1",
            )

    settings = replace(Settings(), rss_sources={"a": "https://a.com/feed"})
    repo = SqliteArticleRepository(str(tmp_path / "private.db"))
    result = await FeedScraper(settings, EncodedClient(), repo).fetch_relevant_articles()
    [article] = result
    assert "fácil" in article.body
    assert "ana@" not in article.title
    assert "30.123" not in article.description
    assert "autor@" not in article.author
    saved = repo._conn.execute(
        "SELECT title, description, author, excerpt FROM articles"
    ).fetchone()
    assert all(value is not None for value in saved)
    assert not any("@" in value or "30.123" in value for value in saved)
    assert repo._conn.execute("SELECT relevant FROM articles").fetchone() == (1,)
    repo.close()
