"""Parseo seguro de RSS 2.0 / Atom (responsabilidad única: XML -> Article)."""
from __future__ import annotations
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from models import Article
from url_utils import normalize_url

logger = logging.getLogger(__name__)
_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


class FeedParseError(Exception):
    pass


def strip_html(text: str) -> str:
    return html.unescape(BeautifulSoup(text or "", "lxml").get_text(" ", strip=True))


def parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _text(item, *tags: str) -> str:
    for tag in tags:
        node = item.find(tag)
        if node is not None:
            text = re.sub(r"\s+", " ", " ".join(node.itertext())).strip()
            if text:
                return text
    return ""


def validate_feed_content_type(url: str, content_type: str) -> None:
    if "html" in content_type and "xml" not in content_type:
        raise FeedParseError(f"{url} devolvió HTML ({content_type})")


class FeedParser:
    def __init__(self, description_chars: int = 500):
        self._desc_chars = description_chars

    def parse(self, xml_bytes: bytes, source: str) -> list[Article]:
        try:
            root = ET.fromstring(xml_bytes, forbid_dtd=True)
        except (ET.ParseError, DefusedXmlException) as exc:
            raise FeedParseError(f"XML inválido o inseguro: {exc}") from exc
        items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
        articles = (self._to_article(i, source) for i in items)
        return [a for a in articles if a is not None]

    def _to_article(self, item, source: str) -> Article | None:
        url = _text(item, "link")
        if not url:
            for link in item.findall(f"{_ATOM}link"):
                rel = link.get("rel", "alternate").lower()
                media_type = link.get("type", "").split(";", 1)[0].strip().lower()
                if (
                    rel == "alternate"
                    and media_type in ("", "text/html", "application/xhtml+xml")
                    and link.get("href")
                ):
                    url = link.get("href", "")
                    break
        if not url:
            return None
        try:
            url = normalize_url(url)
        except ValueError:
            return None
        description = strip_html(
            _text(item, "description", f"{_ATOM}summary", f"{_CONTENT}encoded")
        )
        author = _text(item, "author", f"{_DC}creator", f"{_ATOM}author/{_ATOM}name")
        return Article(
            source=source,
            url=url,
            title=strip_html(_text(item, "title", f"{_ATOM}title")) or "Sin título",
            description=description[: self._desc_chars],
            author=author,
            published=parse_date(_text(item, "pubDate", f"{_ATOM}published", f"{_ATOM}updated")),
        )
