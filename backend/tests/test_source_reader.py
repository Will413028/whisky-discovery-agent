"""The source reader treats reviewed source IDs as data, never network authority."""

import asyncio
import socket

import pytest

from whisky.modules.research.source_reader import (
    SafeResolver,
    SourceReader,
    SourceReadError,
    safe_https_fetch,
    validate_source_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.drinks.com.tw/product.aspx?Id=1753",
        "https://127.0.0.1/private",
        "https://169.254.169.254/latest/meta-data",
        "https://www.drinks.com.tw.evil.test/product",
        "https://user:pass@www.drinks.com.tw/product",
        "https://www.drinks.com.tw:8443/product",
    ],
)
def test_url_policy_rejects_unapproved_origin(url):
    with pytest.raises(SourceReadError):
        validate_source_url(url)


def test_url_policy_accepts_only_selected_https_source_hosts():
    assert validate_source_url("https://www.drinks.com.tw/product.aspx?Id=1753")


class StubResolver:
    def __init__(self, addresses: list[str]):
        self.addresses = addresses

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_dns_policy_rejects_entire_answer_if_one_address_is_private():
    resolver = SafeResolver(StubResolver(["8.8.8.8", "10.0.0.2"]))
    with pytest.raises(SourceReadError):
        await resolver.resolve("www.drinks.com.tw", 443)


@pytest.mark.asyncio
async def test_http_adapter_keeps_private_dns_rejection_non_retryable(monkeypatch):
    from whisky.modules.research import source_reader

    resolver = SafeResolver(StubResolver(["127.0.0.1"]))
    monkeypatch.setattr(source_reader, "SafeResolver", lambda: resolver)
    with pytest.raises(SourceReadError) as captured:
        await safe_https_fetch("https://www.drinks.com.tw/product", 128)
    assert captured.value.code == "SOURCE_DNS_REJECTED"
    assert not captured.value.retryable


@pytest.mark.asyncio
async def test_reader_rejects_private_redirect_before_next_request():
    requested: list[str] = []

    async def fetch(url: str, byte_limit: int):
        requested.append(url)
        return 302, {"Location": "https://127.0.0.1/internal"}, b""

    reader = SourceReader(fetch=fetch)
    with pytest.raises(SourceReadError):
        await reader.read("https://www.drinks.com.tw/product.aspx?Id=1753")
    assert requested == ["https://www.drinks.com.tw/product.aspx?Id=1753"]


@pytest.mark.asyncio
async def test_reader_rejects_oversized_and_timed_out_response():
    async def large_fetch(url: str, byte_limit: int):
        return 200, {"Content-Type": "text/html"}, b"x" * (byte_limit + 1)

    with pytest.raises(SourceReadError, match="TOO_LARGE"):
        await SourceReader(fetch=large_fetch, max_bytes=32).read(
            "https://www.drinks.com.tw/product.aspx?Id=1753"
        )

    async def slow_fetch(url: str, byte_limit: int):
        await asyncio.sleep(0.05)
        return 200, {"Content-Type": "text/html"}, b"okay"

    with pytest.raises(SourceReadError, match="TIMEOUT"):
        await SourceReader(fetch=slow_fetch, timeout_seconds=0.01).read(
            "https://www.drinks.com.tw/product.aspx?Id=1753"
        )


@pytest.mark.asyncio
async def test_reader_bounds_untrusted_text_added_to_each_model_turn():
    async def fetch(url: str, byte_limit: int):
        return 200, {"Content-Type": "text/plain"}, b"a" * 3000

    page = await SourceReader(fetch=fetch).read(
        "https://www.drinks.com.tw/product.aspx?Id=1753"
    )
    assert len(page.text) == 2000


@pytest.mark.asyncio
async def test_default_reader_accepts_bounded_large_markup_without_model_text_growth():
    body = (
        b"<html><script>"
        + b"x" * 1_151_728
        + b"</script><p>synthetic 12-year 40% ABV</p></html>"
    )

    async def fetch(url: str, byte_limit: int):
        return 200, {"Content-Type": "text/html"}, body

    page = await SourceReader(fetch=fetch).read(
        "https://www.theglenlivet.com/zh-tw/whisky/synthetic/"
    )
    assert page.text == "synthetic 12-year 40% ABV"
    assert len(page.text) <= 2000


@pytest.mark.asyncio
async def test_default_reader_still_rejects_content_above_two_mebibytes():
    async def fetch(url: str, byte_limit: int):
        return 200, {"Content-Type": "text/html"}, b"x" * (2 * 1024 * 1024 + 1)

    with pytest.raises(SourceReadError, match="SOURCE_TOO_LARGE"):
        await SourceReader(fetch=fetch).read(
            "https://www.theglenlivet.com/zh-tw/whisky/synthetic/"
        )
