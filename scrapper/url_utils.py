"""Normalización de URLs y protección SSRF."""
from __future__ import annotations
import asyncio
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}
)


class UnsafeURLError(ValueError):
    pass


def normalize_url(url: str) -> str:
    """Forma canónica: host en minúsculas, sin fragmento ni parámetros de tracking."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def _is_public(ip: str) -> bool:
    return ipaddress.ip_address(ip).is_global


async def assert_public_http_url(url: str, allowed_hosts: frozenset[str] = frozenset()) -> None:
    """Rechaza esquemas no HTTP(S), credenciales embebidas e IPs privadas/loopback/link-local."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Esquema no permitido: {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeURLError("URL con credenciales embebidas")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL sin host")
    if allowed_hosts and host.lower() not in allowed_hosts:
        raise UnsafeURLError(f"Host fuera de allowlist: {host}")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"No resuelve: {host}") from exc
    for info in infos:
        if not _is_public(info[4][0]):
            raise UnsafeURLError(f"{host} resuelve a IP no pública")
