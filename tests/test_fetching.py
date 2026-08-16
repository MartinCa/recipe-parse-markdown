"""Unit tests for the SSRF guard and the size/redirect-capped fetcher."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from app.fetching import FetchError, fetch_bytes


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


async def _public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/secret",
        "http://127.5.5.5/secret",
        "http://[::1]/secret",
        "http://10.0.0.5/internal",
        "http://172.16.0.9/internal",
        "http://192.168.1.1/internal",
        "http://169.254.169.254/latest/meta-data/",  # link-local, e.g. cloud metadata
        "http://0.0.0.0/x",
        "http://0.5.5.5/x",
        "http://[fc00::1]/internal",  # RFC 4193 unique local
        "http://[fe80::1]/internal",  # link-local
    ],
)
async def test_fetch_bytes_rejects_disallowed_literal_addresses(url: str) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(client, url, settings=_settings())


async def test_fetch_bytes_rejects_unsupported_scheme() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(client, "ftp://example.com/recipe", settings=_settings())


async def test_fetch_bytes_rejects_hostnames_that_resolve_privately() -> None:
    async def private_resolver(host: str) -> list[str]:
        return ["10.0.0.5"]

    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(
                client,
                "http://internal.example.com/recipe",
                settings=_settings(),
                resolver=private_resolver,
            )


@respx.mock
async def test_fetch_bytes_allows_hostnames_that_resolve_publicly() -> None:
    respx.get("https://recipes.example.com/pancakes").mock(
        return_value=httpx.Response(200, content=b"<html>ok</html>")
    )

    async with httpx.AsyncClient() as client:
        result = await fetch_bytes(
            client,
            "https://recipes.example.com/pancakes",
            settings=_settings(),
            resolver=_public_resolver,
        )

    assert result == b"<html>ok</html>"


async def test_fetch_bytes_allow_private_urls_bypasses_the_guard() -> None:
    with respx.mock:
        respx.get("http://127.0.0.1/recipe").mock(
            return_value=httpx.Response(200, content=b"local")
        )
        async with httpx.AsyncClient() as client:
            result = await fetch_bytes(
                client,
                "http://127.0.0.1/recipe",
                settings=_settings(allow_private_urls=True),
            )

    assert result == b"local"


@respx.mock
async def test_fetch_bytes_caps_the_response_size() -> None:
    respx.get("https://recipes.example.com/huge").mock(
        return_value=httpx.Response(200, content=b"x" * 100)
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(
                client,
                "https://recipes.example.com/huge",
                settings=_settings(max_html_bytes=10),
                resolver=_public_resolver,
            )


@respx.mock
async def test_fetch_bytes_rechecks_the_guard_after_every_redirect() -> None:
    """A redirect that lands on 127.0.0.1 is the classic SSRF bypass -- must be rejected."""
    respx.get("https://recipes.example.com/redirect").mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(
                client,
                "https://recipes.example.com/redirect",
                settings=_settings(),
                resolver=_public_resolver,
            )


@respx.mock
async def test_fetch_bytes_follows_safe_redirects() -> None:
    respx.get("https://recipes.example.com/old").mock(
        return_value=httpx.Response(302, headers={"Location": "https://recipes.example.com/new"})
    )
    respx.get("https://recipes.example.com/new").mock(
        return_value=httpx.Response(200, content=b"moved")
    )

    async with httpx.AsyncClient() as client:
        result = await fetch_bytes(
            client,
            "https://recipes.example.com/old",
            settings=_settings(),
            resolver=_public_resolver,
        )

    assert result == b"moved"


@respx.mock
async def test_fetch_bytes_caps_redirects() -> None:
    for i in range(10):
        respx.get(f"https://recipes.example.com/hop{i}").mock(
            return_value=httpx.Response(
                302, headers={"Location": f"https://recipes.example.com/hop{i + 1}"}
            )
        )

    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError, match="too many redirects"):
            await fetch_bytes(
                client,
                "https://recipes.example.com/hop0",
                settings=_settings(),
                resolver=_public_resolver,
            )


@respx.mock
async def test_fetch_bytes_raises_fetch_error_on_http_error_status() -> None:
    respx.get("https://recipes.example.com/missing").mock(return_value=httpx.Response(404))

    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchError):
            await fetch_bytes(
                client,
                "https://recipes.example.com/missing",
                settings=_settings(),
                resolver=_public_resolver,
            )
