"""Orquestador: feeds RSS -> artículos nuevos -> cuerpo -> filtro por keywords.
Cada colaborador se inyecta (cliente HTTP, parser, extractor, matcher, repositorio),
de modo que el orquestador solo coordina (SRP/DIP) y es testeable con dobles.
"""
from __future__ import annotations
import asyncio
import logging
from email.message import Message
from body_extractor import BodyExtractor, BeautifulSoupExtractor
from feed_parser import FeedParser, validate_feed_content_type
from http_client import FetchError, PoliteHttpClient
from keywords import KeywordMatcher
from models import Article, ArticleRepository
from privacy import redact_pii
from settings import Settings

logger = logging.getLogger(__name__)


class FeedScraper:
    def __init__(
            self,
            settings: Settings,
            client: PoliteHttpClient,
            repository: ArticleRepository | None = None,
            parser: FeedParser | None = None,
            extractor: BodyExtractor | None = None,
            matcher: KeywordMatcher | None = None,
    ):
        self._s = settings
        self._client = client
        self._repo = repository
        self._parser = parser or FeedParser(settings.body_excerpt_chars)
        self._extractor = extractor or BeautifulSoupExtractor()
        self._matcher = matcher or KeywordMatcher(settings.keywords, settings.match_chars)
        self._feed_sem = asyncio.Semaphore(settings.feed_concurrency)
        self._article_sem = asyncio.Semaphore(settings.article_concurrency)

    async def fetch_relevant_articles(self) -> list[Article]:
        candidates = await self._collect_candidates()
        fresh = await self._filter_unseen(candidates)
        relevant: list[Article] = []
        limit = self._s.max_articles_per_run
        processed = 0
        offset = 0
        while offset < len(fresh) and processed < limit:
            batch = fresh[offset : offset + limit - processed]
            offset += len(batch)
            enriched = await asyncio.gather(*(self._enrich(a) for a in batch))
            for article in enriched:
                if article is None:
                    continue
                processed += 1
                matched = self._matcher.matches(article)
                storable = self._to_storable(article)
                if self._repo:
                    await self._repo.mark_seen(storable, relevant=matched)
                if matched:
                    relevant.append(storable)
                if processed >= limit:
                    break
        logger.info("%d artículos relevantes de %d nuevos.", len(relevant), len(fresh))
        return relevant

    async def _collect_candidates(self) -> list[Article]:
        results = await asyncio.gather(
            *(self._fetch_feed(n, u) for n, u in self._s.rss_sources.items()),
            return_exceptions=True,
        )
        seen: set[str] = set()
        out: list[Article] = []
        for name, result in zip(self._s.rss_sources, results):
            if isinstance(result, Exception):
                logger.warning("Feed %s falló: %s", name, result)
                continue
            for article in result:
                if article.url not in seen:
                    seen.add(article.url)
                    out.append(article)
        return out

    async def _fetch_feed(self, name: str, url: str) -> list[Article]:
        async with self._feed_sem:
            data, content_type = await self._client.get_bytes(
                url, accept="application/rss+xml, application/atom+xml, application/xml, text/xml"
            )
        validate_feed_content_type(url, content_type)
        return self._parser.parse(data, name)

    async def _filter_unseen(self, candidates: list[Article]) -> list[Article]:
        fresh: list[Article] = []
        for article in candidates:
            if self._repo and await self._repo.is_seen(article.url):
                continue
            fresh.append(article)
        return fresh

    async def _enrich(self, article: Article) -> Article | None:
        async with self._article_sem:
            try:
                raw, content_type = await self._client.get_bytes(
                    article.url, accept="text/html"
                )
                message = Message()
                message["content-type"] = content_type
                charset = message.get_content_charset() or "utf-8"
                try:
                    html = raw.decode(charset, errors="replace")
                except LookupError:
                    html = raw.decode("utf-8", errors="replace")
                body = await asyncio.to_thread(
                    self._extractor.extract, html
                )
            except FetchError as exc:
                logger.debug("Sin cuerpo para %s: %s", article.url, exc)
                return None
            except Exception:
                logger.exception("Error inesperado extrayendo %s", article.url)
                return None
        return article.with_body(body)

    def _to_storable(self, article: Article) -> Article:
        """Minimización: por defecto solo un extracto con PII redactada."""
        if self._s.store_body:
            body, truncated = redact_pii(article.body), False
        else:
            full = redact_pii(article.body)
            body = full[: self._s.body_excerpt_chars]
            truncated = len(full) > len(body)
        return Article(
            **{
                **article.__dict__,
                "title": redact_pii(article.title),
                "description": redact_pii(article.description),
                "author": redact_pii(article.author),
                "body": body,
                "body_truncated": truncated,
            }
        )
