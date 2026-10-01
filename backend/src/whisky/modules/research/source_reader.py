"""Bounded HTTPS reader for human-reviewed source references.

The caller supplies a catalog source ID; the URL comes from the sealed catalog.
Every redirect is checked, and the resolver returns only validated public IPs.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult

ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "shop.us.glenfiddich.com",
        "www.theglenlivet.com",
        "www.drinks.com.tw",
        "www.my9.com.tw",
    }
)
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_CHARS = 2_000
MAX_REDIRECTS = 3
SOURCE_TIMEOUT_SECONDS = 20.0


class SourceReadError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def validate_source_url(url: str) -> str:
    if not url or url != url.strip() or any(ord(char) < 32 for char in url):
        raise SourceReadError("SOURCE_URL_REJECTED")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourceReadError("SOURCE_URL_REJECTED") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise SourceReadError("SOURCE_URL_REJECTED")
    return url


class SafeResolver(AbstractResolver):
    """Pin each connection to the same public DNS answer that was checked."""

    def __init__(self, delegate: AbstractResolver | None = None) -> None:
        self.delegate = delegate or aiohttp.resolver.DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        if host not in ALLOWED_SOURCE_HOSTS or port != 443:
            raise SourceReadError("SOURCE_DNS_REJECTED")
        records = await self.delegate.resolve(host, port, family)
        if not records:
            raise SourceReadError("SOURCE_DNS_REJECTED")
        for record in records:
            try:
                address = ipaddress.ip_address(record["host"])
            except ValueError as error:
                raise SourceReadError("SOURCE_DNS_REJECTED") from error
            mapped = getattr(address, "ipv4_mapped", None)
            if not address.is_global or (mapped is not None and not mapped.is_global):
                raise SourceReadError("SOURCE_DNS_REJECTED")
        return records

    async def close(self) -> None:
        await self.delegate.close()


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


@dataclass(frozen=True)
class SourcePage:
    final_url: str
    text: str


type Fetch = Callable[[str, int], Awaitable[tuple[int, Mapping[str, str], bytes]]]


async def safe_https_fetch(
    url: str, byte_limit: int
) -> tuple[int, Mapping[str, str], bytes]:
    """One request; no automatic redirect, proxy, credential, or DNS bypass."""
    validate_source_url(url)
    connector = aiohttp.TCPConnector(
        resolver=SafeResolver(), use_dns_cache=False, force_close=True, limit=1
    )
    timeout = aiohttp.ClientTimeout(
        total=SOURCE_TIMEOUT_SECONDS, connect=5, sock_read=10
    )
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=True,
        ) as session:
            async with session.get(
                url,
                allow_redirects=False,
                headers={
                    "Accept": "text/html,text/plain",
                    "User-Agent": "WhiskyDiscoveryReader/1",
                },
            ) as response:
                headers = dict(response.headers)
                length = headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > byte_limit:
                            raise SourceReadError("SOURCE_TOO_LARGE")
                    except ValueError as error:
                        raise SourceReadError("SOURCE_INVALID_LENGTH") from error
                body = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body) > byte_limit:
                        raise SourceReadError("SOURCE_TOO_LARGE")
                return response.status, headers, bytes(body)
    except (aiohttp.ClientError, OSError) as error:
        raise SourceReadError("SOURCE_NETWORK_ERROR", retryable=True) from error


class SourceReader:
    def __init__(
        self,
        *,
        fetch: Fetch = safe_https_fetch,
        max_bytes: int = MAX_SOURCE_BYTES,
        timeout_seconds: float = SOURCE_TIMEOUT_SECONDS,
    ) -> None:
        self.fetch = fetch
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    async def read(self, url: str) -> SourcePage:
        current = validate_source_url(url)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                for _ in range(MAX_REDIRECTS + 1):
                    status, headers, body = await self.fetch(current, self.max_bytes)
                    if status in {301, 302, 303, 307, 308}:
                        location = headers.get("Location") or headers.get("location")
                        if not location:
                            raise SourceReadError("SOURCE_BAD_REDIRECT")
                        current = validate_source_url(urljoin(current, location))
                        continue
                    if status != 200:
                        raise SourceReadError(
                            "SOURCE_HTTP_ERROR",
                            retryable=status in {429, 502, 503, 504},
                        )
                    if len(body) > self.max_bytes:
                        raise SourceReadError("SOURCE_TOO_LARGE")
                    content_type = (
                        (
                            headers.get("Content-Type")
                            or headers.get("content-type")
                            or ""
                        )
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    if content_type not in {
                        "text/html",
                        "text/plain",
                        "application/xhtml+xml",
                    }:
                        raise SourceReadError("SOURCE_CONTENT_TYPE_REJECTED")
                    decoded = body.decode("utf-8-sig", errors="replace")
                    if content_type in {"text/html", "application/xhtml+xml"}:
                        parser = _VisibleText()
                        parser.feed(decoded)
                        decoded = " ".join(parser.parts)
                    text = " ".join(decoded.split())[:MAX_SOURCE_CHARS]
                    return SourcePage(current, text)
                raise SourceReadError("SOURCE_REDIRECT_LIMIT")
        except TimeoutError as error:
            raise SourceReadError("SOURCE_TIMEOUT", retryable=True) from error
