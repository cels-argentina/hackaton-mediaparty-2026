import asyncio
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feed_parser import (  # noqa: E402
    FeedParseError,
    FeedParser,
    validate_feed_content_type,
)
from http_client import PoliteHttpClient, _PublicResolver  # noqa: E402
from keywords import KeywordMatcher  # noqa: E402
from privacy import redact_pii  # noqa: E402
from settings import Settings  # noqa: E402
from url_utils import UnsafeURLError, assert_public_http_url, normalize_url  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Caso de <b>gatillo f&#225;cil</b></title>
<link>https://Ejemplo.com/nota/?utm_source=x&amp;id=3#frag</link>
<description>&lt;p&gt;Bajada &amp;amp; detalle&lt;/p&gt;</description>
<dc:creator>Ana</dc:creator><pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_rss():
    [a] = FeedParser().parse(RSS, "ej")
    assert a.url == "https://ejemplo.com/nota/?id=3"
    assert a.title == "Caso de gatillo fácil"
    assert a.author == "Ana" and a.published is not None
    assert "&" in a.description and "<" not in a.description


def test_parse_atom_uses_html_alternate_link():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Caso</title>
        <link rel="self" type="application/atom+xml" href="https://ejemplo.com/item.xml"/>
        <link type="text/html" href="https://ejemplo.com/nota/"/>
      </entry>
    </feed>"""
    [article] = FeedParser().parse(atom, "ej")
    assert article.url == "https://ejemplo.com/nota/"


def test_xxe_and_dtd_rejected():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><rss>&a;</rss>'
    with pytest.raises(FeedParseError):
        FeedParser().parse(evil, "ej")


def test_keywords_accents_and_word_boundary():
    m = KeywordMatcher(("gatillo fácil", "violencia policial", "tortura"))
    assert m.matches_text("Denuncian GATILLO FACIL en Rosario")
    assert m.matches_text("Denuncian violencia\npolicial en Rosario")
    assert not m.matches_text("la distorturaba")


def test_normalize_url():
    assert normalize_url("HTTP://A.com/x/?fbclid=1&utm_term=2") == "http://a.com/x/"


def test_html_feed_content_type_is_rejected():
    with pytest.raises(FeedParseError):
        validate_feed_content_type("https://example.com/feed", "text/html")
    validate_feed_content_type("https://example.com/feed", "application/rss+xml")


def test_redact():
    out = redact_pii("Escribir a juan@mail.com, DNI 30.123.456")
    assert "juan@" not in out and "30.123" not in out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://127.0.0.1/", "http://169.254.169.254/", "http://u:p@a.com/"]
)
async def test_ssrf_blocked(url):
    with pytest.raises(UnsafeURLError):
        await assert_public_http_url(url)


@pytest.mark.asyncio
async def test_public_resolver_validates_and_pins_resolved_addresses(monkeypatch):
    loop = asyncio.get_running_loop()
    addresses = ["8.8.8.8"]

    async def getaddrinfo(host, port, family, type):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)
    resolver = _PublicResolver(frozenset({"example.com"}))
    result = await resolver.resolve("example.com", 443)
    assert result[0]["host"] == "8.8.8.8"

    addresses[:] = ["8.8.8.8", "127.0.0.1"]
    with pytest.raises(OSError):
        await resolver.resolve("example.com", 443)

    with pytest.raises(OSError):
        await resolver.resolve("other.example", 443)


@pytest.mark.asyncio
async def test_client_connects_with_public_resolver():
    async with PoliteHttpClient(Settings()) as client:
        assert isinstance(client._session.connector._resolver, _PublicResolver)


@pytest.mark.asyncio
async def test_redirect_destinations_are_checked_for_robots(monkeypatch):
    class Response:
        def __init__(self, status, headers=None):
            self.status = status
            self.headers = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

    class Session:
        def __init__(self):
            self.responses = [
                Response(302, {"Location": "/blocked"}),
                Response(200, {"Content-Type": "text/html"}),
            ]

        def get(self, *args, **kwargs):
            return self.responses.pop(0)

    client = PoliteHttpClient(Settings(respect_robots=True))
    client._session = Session()
    client._session.connector = SimpleNamespace(
        _resolver=_PublicResolver(frozenset())
    )
    checked = []

    async def check_robots(url):
        checked.append(url)

    async def no_wait(url):
        pass

    async def read_limited(response):
        return b"ok"

    monkeypatch.setattr(client, "_check_robots", check_robots)
    monkeypatch.setattr(client, "_throttle", no_wait)
    monkeypatch.setattr(client, "_read_limited", read_limited)
    monkeypatch.setattr(
        "http_client.assert_public_http_url",
        lambda *args: asyncio.sleep(0),
    )
    await client._get_once("https://example.com/start", "*/*")
    assert checked == ["https://example.com/start", "https://example.com/blocked"]
