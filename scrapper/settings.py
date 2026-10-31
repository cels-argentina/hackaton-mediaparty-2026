"""Configuración inmutable, inyectable y leída del entorno (sin globals mutables)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Identificación honesta del bot: permite a los medios contactarnos / bloquearnos.
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "SCRAPER_USER_AGENT",
            "ViolenciaPolicialResearchBot/1.0 (+https://example.org/bot; contacto@example.org)",
        )
    )
    # nombre -> URL del feed. Completar con medios argentinos.
    rss_sources: dict[str, str] = field(default_factory=dict)
    keywords: tuple[str, ...] = (
        "gatillo fácil",
        "violencia institucional",
        "violencia policial",
        "abuso policial",
        "apremios ilegales",
        "detención arbitraria",
        "muerte bajo custodia",
        "tortura",
    )
    max_articles_per_run: int = field(default_factory=lambda: _env_int("MAX_ARTICLES_PER_RUN", 50))
    request_timeout: int = 20
    max_response_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    domain_delay: float = 1.5
    feed_concurrency: int = 5
    article_concurrency: int = 8
    retry_attempts: int = 3
    respect_robots: bool = True
    # Privacidad: por defecto NO persistimos el texto completo (derechos de autor + datos personales).
    store_body: bool = False
    body_excerpt_chars: int = 500
    match_chars: int = 5000
    # Solo se permiten estos hosts si se define (allowlist); vacío = cualquiera público.
    allowed_hosts: frozenset[str] = frozenset()
