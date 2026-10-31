"""Cliente HTTP educado y seguro: una sola sesión, rate limit por dominio, robots.txt,
reintentos, tope de tamaño y redirecciones validadas salto a salto (anti-SSRF)."""
from __future__ import annotations
import asyncio
import ipaddress
import logging
import socket
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import aiohttp
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from settings import Settings
from url_utils import assert_public_http_url

logger = logging.getLogger(__name__)
_REDIRECTS = {301, 302, 303, 307, 308}


class _PublicResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, allowed_hosts: frozenset[str]):
        self._allowed_hosts = allowed_hosts

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_UNSPEC
    ) -> list[dict[str, object]]:
        if self._allowed_hosts and host.lower() not in self._allowed_hosts:
            raise OSError(f"Host fuera de allowlist: {host}")
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                host, port, family=family, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise OSError(f"No resuelve: {host}") from exc
        if not infos:
            raise OSError(f"No resuelve: {host}")
        if any(not ipaddress.ip_address(info[4][0]).is_global for info in infos):
            raise OSError(f"{host} resuelve a IP no pública")
        return [
            {
                "hostname": host,
                "host": info[4][0],
                "port": port,
                "family": info[0],
                "proto": info[2],
                "flags": info[3],
            }
            for info in infos
        ]

    async def close(self) -> None:
        pass


class FetchError(Exception):
    pass


class BlockedByRobots(FetchError):
    pass


class _Transient(Exception):
    """Error reintentable."""


class PoliteHttpClient:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession | None = None):
        self._s = settings
        self._session = session
        self._owns_session = session is None
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    async def __aenter__(self) -> "PoliteHttpClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self._s.user_agent},
                timeout=aiohttp.ClientTimeout(total=self._s.request_timeout),
                connector=aiohttp.TCPConnector(
                    resolver=_PublicResolver(self._s.allowed_hosts)
                ),
            )
        else:
            self._require_public_resolver()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    async def get_bytes(self, url: str, accept: str = "*/*") -> tuple[bytes, str]:
        """Devuelve (contenido, content_type). Reintenta solo errores transitorios."""
        try:
            return await self._get_with_retry(url, accept)
        except _Transient as exc:
            raise FetchError(str(exc)) from exc

    async def _get_with_retry(self, url: str, accept: str) -> tuple[bytes, str]:
        @retry(
            stop=stop_after_attempt(self._s.retry_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(_Transient),
            reraise=True,
        )
        async def attempt() -> tuple[bytes, str]:
            return await self._get_once(url, accept)

        return await attempt()

    async def _get_once(
        self, url: str, accept: str, check_robots: bool = True
    ) -> tuple[bytes, str]:
        assert self._session is not None, "Usar dentro de 'async with'"
        self._require_public_resolver()
        current = url
        for _ in range(self._s.max_redirects + 1):
            if check_robots:
                await self._check_robots(current)
            await assert_public_http_url(current, self._s.allowed_hosts)
            await self._throttle(current)
            try:
                async with self._session.get(
                        current, allow_redirects=False, headers={"Accept": accept}
                ) as resp:
                    if resp.status in _REDIRECTS and "Location" in resp.headers:
                        current = urljoin(current, resp.headers["Location"])
                        continue
                    if resp.status in (429, 500, 502, 503, 504):
                        raise _Transient(f"HTTP {resp.status} en {current}")
                    if resp.status >= 400:
                        raise FetchError(f"HTTP {resp.status} en {current}")
                    return await self._read_limited(resp), resp.headers.get("Content-Type", "").lower()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise _Transient(f"{type(exc).__name__} en {current}") from exc
        raise FetchError(f"Demasiadas redirecciones: {url}")

    def _require_public_resolver(self) -> None:
        connector = getattr(self._session, "connector", None)
        if not isinstance(getattr(connector, "_resolver", None), _PublicResolver):
            raise FetchError("La sesión debe usar _PublicResolver")

    async def _read_limited(self, resp: aiohttp.ClientResponse) -> bytes:
        limit = self._s.max_response_bytes
        if resp.content_length and resp.content_length > limit:
            raise FetchError("Respuesta demasiado grande")
        chunks, size = [], 0
        async for chunk in resp.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise FetchError("Respuesta demasiado grande")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _throttle(self, url: str) -> None:
        """Espacia requests por dominio; el lock evita la condición de carrera."""
        domain = urlsplit(url).netloc.lower()
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            wait = self._s.domain_delay - (time.monotonic() - self._last.get(domain, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[domain] = time.monotonic()

    async def _check_robots(self, url: str) -> None:
        if not self._s.respect_robots:
            return
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        if parser and not parser.can_fetch(self._s.user_agent, url):
            raise BlockedByRobots(f"robots.txt prohíbe {url}")

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        try:
            data, _ = await self._get_once(
                f"{origin}/robots.txt", "text/plain", check_robots=False
            )
        except Exception:  # robots inaccesible => se asume permitido
            return None
        parser = RobotFileParser()
        parser.parse(data.decode("utf-8", errors="replace").splitlines())
        return parser
