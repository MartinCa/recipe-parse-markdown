"""Thin wrapper around recipe-scrapers: (HTML, URL) -> Recipe.

recipe-scrapers parses HTML only -- it never fetches. Most getters raise
(NotImplementedError, a SchemaOrgException subclass, AttributeError, ...) when a site
doesn't provide that field, so every getter is called through ``maybe``.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from recipe_scrapers import AbstractScraper, scrape_html

from app.models import IngredientGroup, Recipe
from app.normalise import (
    contains_imperial_units,
    normalise_language,
    normalise_quantities,
    parse_servings,
)


class ScrapeError(Exception):
    """Raised when a page has no usable title or ingredients."""


def maybe[T](fn: Callable[[], T], default: T | None = None) -> T | None:
    """Call a fragile scraper getter, swallowing whatever it raises."""
    try:
        return fn()
    except Exception:
        return default


def scrape(html: str, url: str) -> Recipe:
    """Parse ``html`` (originating from ``url``) into a Recipe.

    Raises ScrapeError when there is no title or no ingredients -- the two fields
    every downstream Markdown file needs, and everything else is optional.
    """
    host = urlparse(url).hostname or url

    try:
        # supported_only=False allows sites recipe-scrapers doesn't recognise by domain
        # to still parse via the generic schema.org fallback -- the whole point of this
        # tool is working with sites Mealie's importer would also have to guess at. This
        # raises outright (rather than a per-getter failure) when there's no schema.org
        # data on the page at all -- also just "no title or ingredients", from a user's
        # point of view.
        scraper = scrape_html(html, org_url=url, supported_only=False)
    except Exception as exc:
        raise ScrapeError(
            f"no title or ingredients found on {host} (html supplied: {html is not None}): {exc}"
        ) from exc

    title = maybe(scraper.title)
    ingredient_groups = _ingredient_groups(scraper)
    has_ingredients = any(group.items for group in ingredient_groups)

    if not title or not has_ingredients:
        raise ScrapeError(
            f"no title or ingredients found on {host} (html supplied: {html is not None})"
        )

    raw_directions = maybe(scraper.instructions_list) or []
    directions = [normalise_quantities(step) for step in raw_directions]

    all_text = [item for group in ingredient_groups for item in group.items] + directions

    return Recipe(
        title=title,
        source_url=maybe(scraper.canonical_url) or url,
        ingredient_groups=ingredient_groups,
        directions=directions,
        author=maybe(scraper.author),
        language=normalise_language(maybe(scraper.language)),
        cuisine=maybe(scraper.cuisine),
        servings=parse_servings(maybe(scraper.yields)),
        time_minutes=maybe(scraper.total_time),
        description=maybe(scraper.description),
        nutrients=maybe(scraper.nutrients) or {},
        needs_metric=contains_imperial_units(all_text),
        image_url=maybe(scraper.image),
    )


def _ingredient_groups(scraper: AbstractScraper) -> list[IngredientGroup]:
    """Prefer ingredient_groups() -- groups become bold sub-headings. Fall back to one group."""
    groups = maybe(scraper.ingredient_groups)
    if groups:
        cleaned = [
            IngredientGroup(
                name=group.purpose,
                items=[normalise_quantities(item) for item in group.ingredients],
            )
            for group in groups
            if group.ingredients
        ]
        if cleaned:
            return cleaned

    ingredients = maybe(scraper.ingredients) or []
    if not ingredients:
        return []
    return [IngredientGroup(name=None, items=[normalise_quantities(item) for item in ingredients])]
