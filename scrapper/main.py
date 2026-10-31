"""Punto de entrada: python main.py [--db articles.db] [--check-feeds]"""
from __future__ import annotations
import argparse
import asyncio
import logging
from dataclasses import replace
from feeds import CANDIDATE_FEEDS
from http_client import PoliteHttpClient
from scraper import FeedScraper
from settings import Settings
from sqlite_repository import SqliteArticleRepository


async def check_feeds(settings: Settings) -> None:
    from feed_parser import FeedParser, validate_feed_content_type
    parser = FeedParser()
    async with PoliteHttpClient(settings) as client:
        for name, url in settings.rss_sources.items():
            try:
                data, content_type = await client.get_bytes(url)
                validate_feed_content_type(url, content_type)
                print(f"OK    {name}: {len(parser.parse(data, name))} items")
            except Exception as exc:
                print(f"FALLA {name}: {exc}")


async def run(db_path: str, check: bool) -> None:
    settings = replace(Settings(), rss_sources=CANDIDATE_FEEDS)
    if check:
        await check_feeds(settings)
        return
    repo = SqliteArticleRepository(db_path)
    try:
        async with PoliteHttpClient(settings) as client:
            articles = await FeedScraper(settings, client, repo).fetch_relevant_articles()
    finally:
        repo.close()
    for a in articles:
        print(f"[{a.source}] {a.title}\n  {a.url}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="articles.db")
    ap.add_argument("--check-feeds", action="store_true", help="valida los feeds y sale")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(args.db, args.check_feeds))
