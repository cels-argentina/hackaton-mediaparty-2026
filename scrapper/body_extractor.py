"""Extracción del texto principal (estrategia intercambiable: OCP/DIP)."""
from __future__ import annotations
from typing import Protocol
from bs4 import BeautifulSoup

_NOISE = ["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe"]
_BODY_CLASSES = ["article-body", "post-content", "entry-content", "story-body", "content"]


class BodyExtractor(Protocol):
    def extract(self, html: str) -> str: ...


class BeautifulSoupExtractor:
    def extract(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(_NOISE):
            tag.decompose()
        target = (
                soup.find("article")
                or soup.find(class_=_BODY_CLASSES)
                or soup.find("main")
                or soup.find("body")
        )
        if target is None:
            return ""
        lines = (ln.strip() for ln in target.get_text("\n", strip=True).splitlines())
        return "\n".join(ln for ln in lines if ln)
