"""Per-URL pipeline: fetch (or use pasted HTML), scrape, fetch+process the image, render.

Shared by the web route and the CLI so there is exactly one place wiring
fetching.py, scrape.py, images.py, and render.py together.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings
from app.fetching import FetchError, fetch_bytes
from app.images import process_image
from app.models import ScrapeOutcome
from app.render import render
from app.scrape import ScrapeError, scrape

logger = logging.getLogger(__name__)


async def process_url(
    url: str,
    html: str | None,
    *,
    client: httpx.AsyncClient,
    settings: Settings,
) -> ScrapeOutcome:
    """Turn one URL (optionally with pasted HTML) into a rendered recipe."""
    try:
        page_html = html if html is not None else await _fetch_html(url, client, settings)
    except FetchError as exc:
        return ScrapeOutcome(url=url, error=f"could not fetch page: {exc}")

    try:
        # recipe-scrapers is synchronous; run it off the event loop.
        recipe = await asyncio.to_thread(scrape, page_html, url)
    except ScrapeError as exc:
        return ScrapeOutcome(url=url, error=str(exc))

    warnings: list[str] = []
    if not recipe.directions:
        warnings.append("no directions found on page -- Directions section left empty")
    if recipe.image_url:
        try:
            raw = await fetch_bytes(client, recipe.image_url, settings=settings)
            recipe.image = await asyncio.to_thread(
                process_image,
                raw,
                max_edge=settings.image_max_edge,
                quality=settings.image_quality,
            )
        except Exception as exc:  # a failed image fetch is not a failed scrape -- 403s are common
            logger.info("image fetch failed for %s: %s", recipe.image_url, exc)
            warnings.append(f"image fetch failed ({exc}), original: {recipe.image_url}")

    files = render(recipe)
    return ScrapeOutcome(url=url, files=files, warnings=warnings)


async def _fetch_html(url: str, client: httpx.AsyncClient, settings: Settings) -> str:
    raw = await fetch_bytes(client, url, settings=settings)
    return raw.decode("utf-8", errors="replace")
