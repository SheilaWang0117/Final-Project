"""SSRF-safe public HTTP retrieval.

Every request (and every redirect hop):
- must use http/https on the default port, without embedded credentials;
- must resolve only to globally routable IP addresses (private, loopback,
  link-local, metadata, multicast and reserved ranges are rejected);
- is connected to the vetted IP (Host header + TLS SNI keep the original
  name), so a second DNS answer cannot redirect it to an internal address;
- is size-capped while streaming, time-limited, retried a bounded number of
  times, and limited by a global concurrency semaphore.
Response bodies are treated as untrusted data by all callers.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..config import get_settings

USER_AGENT = "OcraPipelineIntelligence/0.1 (+local research prototype; respects robots and rate limits)"
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp")
_semaphore: asyncio.Semaphore | None = None


class UnsafeURL(ValueError):
    pass


class FetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    retrieved_at: str
    sha256: str
    from_cache: bool = False

    @property
    def text(self) -> str:
        enc = "utf-8"
        if "charset=" in self.content_type:
            enc = self.content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(enc, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().http_concurrency)
    return _semaphore


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return is_public_ip(str(addr.ipv4_mapped))
        if addr.sixtofour:
            return is_public_ip(str(addr.sixtofour))
        if addr.teredo:
            return False
    return addr.is_global and not (addr.is_multicast or addr.is_reserved or addr.is_loopback or addr.is_link_local or addr.is_private)


def check_url_syntax(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme '{parts.scheme}' is not allowed")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURL("URL has no host")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeURL(f"host '{host}' is internal")
    default = 443 if parts.scheme == "https" else 80
    port = parts.port or default
    if port != default:
        raise UnsafeURL("non-default ports are not allowed")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal and not is_public_ip(host):
        raise UnsafeURL("private or reserved IP address")
    return parts.scheme, host, port


async def resolve_public(host: str, port: int) -> str:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"DNS lookup failed for {host}") from exc
    ips = sorted({i[4][0] for i in infos})
    if not ips:
        raise FetchError(f"no addresses for {host}")
    bad = [ip for ip in ips if not is_public_ip(ip)]
    if bad:
        raise UnsafeURL(f"{host} resolves to a non-public address")
    v4 = [ip for ip in ips if ":" not in ip]
    return (v4 or ips)[0]


async def validate_url(url: str) -> tuple[str, str, int, str]:
    scheme, host, port = check_url_syntax(url)
    ip = await resolve_public(host, port)
    return scheme, host, port, ip


async def fetch(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: float | None = None,
    retries: int | None = None,
    headers: dict | None = None,
    max_redirects: int = 5,
) -> FetchResult:
    s = get_settings()
    max_bytes = max_bytes or s.http_max_bytes
    timeout = timeout or s.http_timeout_seconds
    retries = s.http_retries if retries is None else retries
    attempt = 0
    while True:
        try:
            async with _sem():
                return await _fetch_once(url, max_bytes, timeout, headers or {}, max_redirects)
        except UnsafeURL:
            raise
        except (httpx.TimeoutException, httpx.TransportError, FetchError) as exc:
            if isinstance(exc, FetchError) and "status 4" in str(exc):
                raise
            attempt += 1
            if attempt > retries:
                raise FetchError(f"{type(exc).__name__}: {exc}"[:300]) from exc
            await asyncio.sleep(min(2 ** attempt, 8))


async def _fetch_once(url: str, max_bytes: int, timeout: float, headers: dict, max_redirects: int) -> FetchResult:
    current = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for _hop in range(max_redirects + 1):
            scheme, host, port, ip = await validate_url(current)
            parts = urlsplit(current)
            ip_host = f"[{ip}]" if ":" in ip else ip
            pinned = urlunsplit((scheme, ip_host, parts.path or "/", parts.query, ""))
            req_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, identity", "Host": host, **headers}
            request = client.build_request("GET", pinned, headers=req_headers, extensions={"sni_hostname": host} if scheme == "https" else {})
            response = await client.send(request, stream=True)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    loc = response.headers.get("location")
                    if not loc:
                        raise FetchError("redirect without location")
                    current = urljoin(current, loc)
                    continue
                if response.status_code >= 500:
                    raise FetchError(f"status {response.status_code}")
                if response.status_code >= 400:
                    raise FetchError(f"status {response.status_code} for {host}")
                ce = response.headers.get("content-encoding", "identity").lower()
                if ce not in ("identity", "gzip", ""):
                    raise FetchError(f"unsupported content-encoding {ce}")
                chunks, total = [], 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(f"response larger than {max_bytes} bytes")
                    chunks.append(chunk)
                body = b"".join(chunks)
                return FetchResult(
                    url=url, final_url=current, status=response.status_code,
                    content_type=response.headers.get("content-type", ""), body=body,
                    retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    sha256=hashlib.sha256(body).hexdigest(),
                )
            finally:
                await response.aclose()
    raise FetchError("too many redirects")
