import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feed_parser import FeedParseError, FeedParser  # noqa: E402
from keywords import KeywordMatcher  # noqa: E402
from privacy import redact_pii  # noqa: E402
from url_utils import UnsafeURLError, assert_public_http_url, normalize_url  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Caso de <b>gatillo f&#225;cil</b></title>
<link>https://Ejemplo.com/nota/?utm_source=x&amp;id=3#frag</link>
<description>&lt;p&gt;Bajada &amp;amp; detalle&lt;/p&gt;</description>
<dc:creator>Ana</dc:creator><pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_rss():
    [a] = FeedParser().parse(RSS, "ej")
    assert a.url == "https://ejemplo.com/nota?id=3"
    assert a.author == "Ana" and a.published is not None
    assert "&" in a.description and "<" not in a.description


def test_xxe_and_dtd_rejected():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><rss>&a;</rss>'
    with pytest.raises(FeedParseError):
        FeedParser().parse(evil, "ej")


def test_keywords_accents_and_word_boundary():
    m = KeywordMatcher(("gatillo fácil", "tortura"))
    assert m.matches_text("Denuncian GATILLO FACIL en Rosario")
    assert not m.matches_text("la distorturaba")


def test_normalize_url():
    assert normalize_url("HTTP://A.com/x/?fbclid=1&utm_term=2") == "http://a.com/x"


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
