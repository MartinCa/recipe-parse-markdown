"""Tests for the Mealie migration: JSON-to-Recipe mapping and the API client."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from app.mealie import (
    MealieError,
    _image_url,
    _ingredient_groups,
    _parse_minutes,
    fetch_recipe,
    list_slugs,
    migrate_from_mealie,
    to_recipe,
)
from app.models import IngredientGroup


def test_to_recipe_maps_the_documented_fields() -> None:
    data = {
        "name": "Boller i Karry",
        "orgURL": "https://example.com/boller-i-karry",
        "recipeYield": "4 servings",
        "totalTime": "PT45M",
        "description": "A classic.",
        "recipeIngredient": [
            {"display": "500 g hakket svinekød", "title": ""},
        ],
        "recipeInstructions": [{"text": "Rør farsen sammen."}],
        "nutrition": {"calories": "420 kcal"},
    }

    recipe = to_recipe(data)

    assert recipe.title == "Boller i Karry"
    assert recipe.source_url == "https://example.com/boller-i-karry"
    assert recipe.servings == 4
    assert recipe.time_minutes == 45
    assert recipe.description == "A classic."
    assert recipe.directions == ["Rør farsen sammen."]
    assert recipe.nutrients == {"calories": "420 kcal"}


def test_to_recipe_raises_without_a_name() -> None:
    with pytest.raises(MealieError):
        to_recipe({"slug": "no-name"})


def test_ingredient_groups_splits_on_titled_items() -> None:
    items = [
        {"title": "Boller", "display": "500 g pork"},
        {"title": "", "display": "1 onion"},
        {"title": "Sauce", "display": "3 dl coconut milk"},
    ]

    groups = _ingredient_groups(items)

    assert groups == [
        IngredientGroup(name="Boller", items=["500 g pork", "1 onion"]),
        IngredientGroup(name="Sauce", items=["3 dl coconut milk"]),
    ]


def test_ingredient_groups_with_no_titles_is_one_unnamed_group() -> None:
    items = [{"title": "", "display": "1 egg"}, {"title": "", "display": "2 eggs"}]

    groups = _ingredient_groups(items)

    assert groups == [IngredientGroup(name=None, items=["1 egg", "2 eggs"])]


def test_ingredient_groups_normalises_quantities() -> None:
    items = [{"title": "", "display": "1,5 dl mælk"}]

    groups = _ingredient_groups(items)

    assert groups[0].items == ["1.5 dl mælk"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("PT45M", 45),
        ("PT1H15M", 75),
        ("45 minutes", 45),
        ("not a duration", None),
    ],
)
def test_parse_minutes(raw: str | None, expected: int | None) -> None:
    assert _parse_minutes(raw) == expected


def test_image_url_only_accepts_absolute_urls() -> None:
    assert _image_url({"image": "https://example.com/img.jpg"}) == "https://example.com/img.jpg"
    assert _image_url({"image": "some-asset-key.webp"}) is None
    assert _image_url({}) is None


@respx.mock
async def test_list_slugs_pages_through_results() -> None:
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(
            200, json={"items": [{"slug": "a"}, {"slug": "b"}], "next": "page2"}
        )
    )
    respx.get("https://mealie.example.com/api/recipes", params={"page": "2", "perPage": "50"}).mock(
        return_value=httpx.Response(200, json={"items": [{"slug": "c"}], "next": None})
    )

    async with httpx.AsyncClient(base_url="https://mealie.example.com") as client:
        slugs = await list_slugs(client)

    assert slugs == ["a", "b", "c"]


@respx.mock
async def test_fetch_recipe_gets_the_detail_payload() -> None:
    respx.get("https://mealie.example.com/api/recipes/boller-i-karry").mock(
        return_value=httpx.Response(200, json={"name": "Boller i Karry", "slug": "boller-i-karry"})
    )

    async with httpx.AsyncClient(base_url="https://mealie.example.com") as client:
        data = await fetch_recipe(client, "boller-i-karry")

    assert data["name"] == "Boller i Karry"


@respx.mock
async def test_migrate_from_mealie_writes_rendered_files(tmp_path: Path) -> None:
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(200, json={"items": [{"slug": "boller-i-karry"}], "next": None})
    )
    respx.get("https://mealie.example.com/api/recipes/boller-i-karry").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Boller i Karry",
                "orgURL": "https://example.com/boller-i-karry",
                "recipeYield": "4 servings",
                "totalTime": "PT45M",
                "recipeIngredient": [{"title": "", "display": "500 g pork"}],
                "recipeInstructions": [{"text": "Cook it."}],
            },
        )
    )

    failures = await migrate_from_mealie(
        "https://mealie.example.com", "test-token", tmp_path, Settings()
    )

    assert failures == 0
    assert (tmp_path / "Boller i Karry.md").exists()
    content = (tmp_path / "Boller i Karry.md").read_text()
    assert "source: https://example.com/boller-i-karry" in content


@respx.mock
async def test_migrate_from_mealie_counts_failures_without_aborting(tmp_path: Path) -> None:
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(
            200, json={"items": [{"slug": "broken"}, {"slug": "ok-one"}], "next": None}
        )
    )
    respx.get("https://mealie.example.com/api/recipes/broken").mock(
        return_value=httpx.Response(200, json={"slug": "broken"})  # no "name" -> MealieError
    )
    respx.get("https://mealie.example.com/api/recipes/ok-one").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "OK One",
                "recipeIngredient": [{"title": "", "display": "1 egg"}],
                "recipeInstructions": [{"text": "Boil it."}],
            },
        )
    )

    failures = await migrate_from_mealie(
        "https://mealie.example.com", "test-token", tmp_path, Settings()
    )

    assert failures == 1
    assert (tmp_path / "OK One.md").exists()


@respx.mock
async def test_migrate_from_mealie_raises_when_the_list_call_fails(tmp_path: Path) -> None:
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(500)
    )

    with pytest.raises(MealieError):
        await migrate_from_mealie("https://mealie.example.com", "test-token", tmp_path, Settings())
