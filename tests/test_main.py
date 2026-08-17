"""Route tests: valid single URL, valid batch, partial failure, validation, zip contents."""

from __future__ import annotations

import re
import zipfile
from collections.abc import AsyncIterator
from io import BytesIO

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from PIL import Image

from app.config import Settings
from app.main import create_app
from tests.conftest import FIXTURES

# Skips DNS resolution in the SSRF guard (already covered by test_fetching.py) so
# route tests only need respx, never real network.
TEST_SETTINGS = Settings(allow_private_urls=True, max_urls_per_batch=25)


def _fake_jpeg() -> bytes:
    image = Image.new("RGB", (50, 50), color=(200, 50, 50))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


async def make_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async for test_client in make_client(TEST_SETTINGS):
        yield test_client


def _fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text()


def _zip_names(content: bytes) -> set[str]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return set(archive.namelist())


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_index_renders_the_form(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert "recipe2md" in response.text
    assert "scrape-form" in response.text


@respx.mock
async def test_scrape_single_url_returns_a_zip(client: httpx.AsyncClient) -> None:
    respx.get("https://example.com/fluffy-pancakes").mock(
        return_value=httpx.Response(200, text=_fixture_html("english_basic.html"))
    )
    respx.get("https://example.com/img/fluffy-pancakes.jpg").mock(
        return_value=httpx.Response(200, content=_fake_jpeg())
    )

    response = await client.post("/scrape", data={"urls": "https://example.com/fluffy-pancakes"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert re.match(
        r'attachment; filename="recipes-\d{8}-\d{6}\.zip"',
        response.headers["content-disposition"],
    )
    names = _zip_names(response.content)
    assert names == {"Fluffy Pancakes.md", "_attachments/Fluffy Pancakes.jpg"}


@respx.mock
async def test_scrape_batch_of_urls(client: httpx.AsyncClient) -> None:
    respx.get("https://example.com/fluffy-pancakes").mock(
        return_value=httpx.Response(200, text=_fixture_html("english_basic.html"))
    )
    respx.get("https://example.com/img/fluffy-pancakes.jpg").mock(
        return_value=httpx.Response(200, content=_fake_jpeg())
    )
    respx.get("https://example.com/simple-tomato-soup").mock(
        return_value=httpx.Response(200, text=_fixture_html("no_image.html"))
    )

    urls = "https://example.com/fluffy-pancakes\nhttps://example.com/simple-tomato-soup"
    response = await client.post("/scrape", data={"urls": urls})

    assert response.status_code == 200
    names = _zip_names(response.content)
    assert "Fluffy Pancakes.md" in names
    assert "Simple Tomato Soup.md" in names
    assert "_errors.txt" not in names


@respx.mock
async def test_scrape_batch_with_one_failure_still_returns_the_others(
    client: httpx.AsyncClient,
) -> None:
    respx.get("https://example.com/fluffy-pancakes").mock(
        return_value=httpx.Response(200, text=_fixture_html("english_basic.html"))
    )
    respx.get("https://example.com/img/fluffy-pancakes.jpg").mock(
        return_value=httpx.Response(200, content=_fake_jpeg())
    )
    respx.get("https://example.com/broken").mock(return_value=httpx.Response(500))

    urls = "https://example.com/fluffy-pancakes\nhttps://example.com/broken"
    response = await client.post("/scrape", data={"urls": urls})

    assert response.status_code == 200
    names = _zip_names(response.content)
    assert "Fluffy Pancakes.md" in names
    assert "_errors.txt" in names

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        errors_text = archive.read("_errors.txt").decode("utf-8")
    assert "https://example.com/broken" in errors_text


@respx.mock
async def test_scrape_image_fetch_failure_is_a_warning_not_a_failure(
    client: httpx.AsyncClient,
) -> None:
    respx.get("https://example.com/fluffy-pancakes").mock(
        return_value=httpx.Response(200, text=_fixture_html("english_basic.html"))
    )
    respx.get("https://example.com/img/fluffy-pancakes.jpg").mock(return_value=httpx.Response(403))

    response = await client.post("/scrape", data={"urls": "https://example.com/fluffy-pancakes"})

    assert response.status_code == 200
    names = _zip_names(response.content)
    assert "Fluffy Pancakes.md" in names
    assert not any(name.startswith("_attachments/") for name in names)
    assert "_errors.txt" in names
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        errors_text = archive.read("_errors.txt").decode("utf-8")
    assert "image fetch failed" in errors_text
    assert "fluffy-pancakes.jpg" in errors_text


async def test_scrape_warns_when_no_directions_are_found(client: httpx.AsyncClient) -> None:
    html = """
    <!doctype html><html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Recipe",
      "name": "Directionless Soup",
      "recipeIngredient": ["1 kg tomatoes"]
    }
    </script>
    </head><body></body></html>
    """

    with respx.mock:
        response = await client.post(
            "/scrape",
            data={"urls": "https://example.com/directionless-soup", "html": html},
        )

    assert response.status_code == 200
    names = _zip_names(response.content)
    assert "Directionless Soup.md" in names
    assert "_errors.txt" in names
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        errors_text = archive.read("_errors.txt").decode("utf-8")
    assert "no directions found" in errors_text


async def test_scrape_uses_pasted_html_without_fetching_the_page(
    client: httpx.AsyncClient,
) -> None:
    # No respx mock is registered for the page itself -- if the route tried to fetch
    # it anyway, httpx would raise for an unmocked request outside of respx.mock.
    with respx.mock:
        response = await client.post(
            "/scrape",
            data={
                "urls": "https://example.com/simple-tomato-soup",
                "html": _fixture_html("no_image.html"),
            },
        )

    assert response.status_code == 200
    names = _zip_names(response.content)
    assert "Simple Tomato Soup.md" in names


async def test_scrape_rejects_multiple_urls_with_pasted_html(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/scrape",
        data={
            "urls": "https://example.com/a\nhttps://example.com/b",
            "html": "<html>some pasted markup</html>",
        },
    )

    assert response.status_code == 400
    assert "exactly one URL" in response.text
    # The user's input is preserved so they don't have to re-copy it.
    assert "https://example.com/a" in response.text
    assert "some pasted markup" in response.text


async def test_scrape_rejects_oversize_pasted_html(client: httpx.AsyncClient) -> None:
    tiny_limit_settings = Settings(allow_private_urls=True, max_html_bytes=10)
    async for tiny_client in make_client(tiny_limit_settings):
        response = await tiny_client.post(
            "/scrape",
            data={"urls": "https://example.com/a", "html": "x" * 100},
        )
        assert response.status_code == 400
        assert "exceeds" in response.text


async def test_scrape_accepts_pasted_html_over_one_megabyte(client: httpx.AsyncClient) -> None:
    # Regression test: Starlette's request.form() rejects any single field over 1MB by
    # default, regardless of our own (much larger) max_html_bytes setting. Before the
    # fix, this returned a raw `{"detail": "..."}` 400 instead of ever reaching our
    # validation or the scraper.
    padded_html = _fixture_html("no_image.html") + ("<!-- " + "x" * 1_100_000 + " -->")
    assert len(padded_html.encode("utf-8")) > 1_048_576

    with respx.mock:
        response = await client.post(
            "/scrape",
            data={"urls": "https://example.com/simple-tomato-soup", "html": padded_html},
        )

    assert response.status_code == 200
    assert "Simple Tomato Soup.md" in _zip_names(response.content)


async def test_scrape_accepts_multipart_html_over_one_megabyte(
    client: httpx.AsyncClient,
) -> None:
    # Same as above, but forcing multipart/form-data encoding (what a real browser
    # sends via `new FormData(form)`), since Starlette enforces the 1MB-per-field
    # default on both the urlencoded and multipart parsers independently.
    padded_html = _fixture_html("no_image.html") + ("<!-- " + "x" * 1_100_000 + " -->")

    with respx.mock:
        response = await client.post(
            "/scrape",
            files={
                "urls": (None, "https://example.com/simple-tomato-soup"),
                "html": (None, padded_html),
            },
        )

    assert response.status_code == 200
    assert "Simple Tomato Soup.md" in _zip_names(response.content)


async def test_scrape_rejects_empty_submission(client: httpx.AsyncClient) -> None:
    response = await client.post("/scrape", data={"urls": ""})

    assert response.status_code == 400
    assert "at least one URL" in response.text


async def test_scrape_rejects_too_many_urls(client: httpx.AsyncClient) -> None:
    tiny_batch_settings = Settings(allow_private_urls=True, max_urls_per_batch=2)
    async for tiny_client in make_client(tiny_batch_settings):
        urls = "\n".join(f"https://example.com/{i}" for i in range(3))
        response = await tiny_client.post("/scrape", data={"urls": urls})
        assert response.status_code == 400
        assert "Too many URLs" in response.text


@respx.mock
async def test_scrape_all_urls_failing_re_renders_the_form(client: httpx.AsyncClient) -> None:
    respx.get("https://example.com/broken").mock(return_value=httpx.Response(500))

    response = await client.post("/scrape", data={"urls": "https://example.com/broken"})

    assert response.status_code == 400
    assert "Every URL failed" in response.text
    assert "https://example.com/broken" in response.text
