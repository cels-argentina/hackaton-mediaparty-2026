"""Filtro por palabras clave insensible a mayúsculas y tildes."""
from __future__ import annotations
import re
import unicodedata
from models import Article


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", unaccented).strip()


class KeywordMatcher:
    def __init__(self, keywords: tuple[str, ...], max_chars: int = 5000):
        # \b evita falsos positivos por subcadena (p. ej. "tortura" dentro de otra palabra).
        self._patterns = [re.compile(rf"\b{re.escape(fold(k))}\b") for k in keywords]
        self._max = max_chars

    def matches_text(self, text: str) -> bool:
        folded = fold(text)
        return any(p.search(folded) for p in self._patterns)

    def matches(self, article: Article) -> bool:
        return self.matches_text(
            f"{article.title} {article.description} {article.body[: self._max]}"
        )
