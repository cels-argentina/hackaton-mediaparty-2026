import sys
from dataclasses import replace
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
