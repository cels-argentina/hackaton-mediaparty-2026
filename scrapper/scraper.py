"""Orquestador: feeds RSS -> artículos nuevos -> cuerpo -> filtro por keywords.
Cada colaborador se inyecta (cliente HTTP, parser, extractor, matcher, repositorio),
de modo que el orquestador solo coordina (SRP/DIP) y es testeable con dobles.
"""
from __future__ import annotations
import asyncio
import logging
from body_extractor import BodyExtractor, BeautifulSoupExtractor
from feed_parser import FeedParseError, FeedParser
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
        enriched = await asyncio.gather(*(self._enrich(a) for a in fresh))
        relevant: list[Article] = []
        for article in enriched:
            matched = self._matcher.matches(article)
            # Se marca visto aunque no coincida (evita reprocesar), salvo que falló la descarga.
            if self._repo and (matched or article.body):
                await self._repo.mark_seen(self._to_storable(article))
            if matched:
                relevant.append(self._to_storable(article))
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
        if "html" in content_type and "xml" not in content_type:
            raise FeedParseError(f"{url} devolvió HTML ({content_type})")
        return self._parser.parse(data, name)

    async def _filter_unseen(self, candidates: list[Article]) -> list[Article]:
        fresh: list[Article] = []
        for article in candidates:
            if len(fresh) >= self._s.max_articles_per_run:
                break
            if self._repo and await self._repo.is_seen(article.url):
                continue
            fresh.append(article)
        return fresh

    async def _enrich(self, article: Article) -> Article:
        async with self._article_sem:
            try:
                raw, _ = await self._client.get_bytes(article.url, accept="text/html")
                body = await asyncio.to_thread(
                    self._extractor.extract, raw.decode("utf-8", errors="replace")
                )
            except FetchError as exc:
                logger.debug("Sin cuerpo para %s: %s", article.url, exc)
                return article
            except Exception:
                logger.exception("Error inesperado extrayendo %s", article.url)
                return article
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
            **{**article.__dict__, "body": body, "body_truncated": truncated}
        )
