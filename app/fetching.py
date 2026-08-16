"""URL fetching with an SSRF guard: resolve-then-check, redirect-safe, size-capped.

This app fetches user-supplied URLs from inside a homelab -- treat every URL as
hostile input. The same guard covers both recipe pages and their images.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable

import httpx

from app.config import Settings

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 5
_ZERO_NETWORK = ipaddress.ip_network("0.0.0.0/8")

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchError(Exception):
    """Raised when a URL can't be fetched safely or successfully."""


async def default_resolver(host: str) -> list[str]:
    """Resolve a hostname to every address it maps to, via the system resolver."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except OSError as exc:
        raise FetchError(f"could not resolve host {host!r}: {exc}") from exc
    return [str(info[4][0]) for info in infos]


def _is_disallowed_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv4Address) and addr in _ZERO_NETWORK:
        return True
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_private
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


async def _check_url_is_safe(url: str, *, allow_private: bool, resolver: Resolver) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise FetchError(f"unsupported URL scheme {parsed.scheme!r} in {url}")
    if not parsed.host:
        raise FetchError(f"URL has no host: {url}")

    if allow_private:
        return

    try:
        # A literal IP in the URL needs no DNS resolution -- and no resolver-based
        # test double would see it either, so this has to be checked directly.
        ipaddress.ip_address(parsed.host)
        addresses = [parsed.host]
    except ValueError:
        addresses = await resolver(parsed.host)

    if not addresses:
        raise FetchError(f"host {parsed.host!r} did not resolve to any address")

    for ip in addresses:
        if _is_disallowed_address(ip):
            raise FetchError(f"host {parsed.host!r} resolves to disallowed address {ip}")


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    """Stream the body, aborting as soon as it exceeds ``limit`` -- never buffer first."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise FetchError(f"response from {response.url} exceeded {limit} bytes")
    return bytes(body)


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    settings: Settings,
    resolver: Resolver = default_resolver,
) -> bytes:
    """GET url, enforcing the SSRF guard on every hop and capping the response size.

    Raises FetchError for anything that goes wrong -- a disallowed address, a
    connection failure, a non-2xx response, or too many redirects -- so callers only
    ever have one exception type to catch for "this URL didn't work out".
    """
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        await _check_url_is_safe(
            current_url, allow_private=settings.allow_private_urls, resolver=resolver
        )

        try:
            async with client.stream(
                "GET",
                current_url,
                headers={"User-Agent": settings.user_agent},
                timeout=settings.request_timeout,
                follow_redirects=False,
            ) as response:
                if response.has_redirect_location:
                    current_url = str(response.url.join(response.headers["location"]))
                    continue

                response.raise_for_status()
                return await _read_capped(response, settings.max_html_bytes)
        except httpx.HTTPError as exc:
            raise FetchError(f"could not fetch {current_url}: {exc}") from exc

    raise FetchError(f"too many redirects fetching {url}")
