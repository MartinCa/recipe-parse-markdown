"""FastAPI application: one form, one scrape endpoint, nothing written to disk."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.models import ScrapeOutcome
from app.packaging import build_zip
from app.pipeline import process_url

BASE_DIR = Path(__file__).parent

BOOKMARKLET = (
    "javascript:(()=>{navigator.clipboard.writeText(document.documentElement.outerHTML)"
    ".then(()=>alert('HTML copied'))})();"
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings instead of using the env."""
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level.upper())
    templates = Jinja2Templates(directory=BASE_DIR / "templates")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own a single shared HTTP client for the app's lifetime."""
        async with httpx.AsyncClient() as http_client:
            app.state.http_client = http_client
            yield

    app = FastAPI(title="recipe2md", lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    def form_context(
        urls_text: str = "", html_text: str = "", error: str | None = None
    ) -> dict[str, str | None]:
        return {
            "urls_text": urls_text,
            "html_text": html_text,
            "error": error,
            "bookmarklet": BOOKMARKLET,
        }

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", form_context())

    @app.post("/scrape")
    async def do_scrape(request: Request, urls: str = Form(""), html: str = Form("")) -> Response:
        url_list = [line.strip() for line in urls.splitlines() if line.strip()]
        html_text = html.strip()

        error = _validate(url_list, html_text, settings)
        if error:
            return templates.TemplateResponse(
                request,
                "index.html",
                form_context(urls, html, error),
                status_code=400,
            )

        semaphore = asyncio.Semaphore(settings.scrape_concurrency)
        supplied_html = html_text if html_text and len(url_list) == 1 else None
        http_client: httpx.AsyncClient = request.app.state.http_client

        async def bounded(url: str) -> ScrapeOutcome:
            async with semaphore:
                try:
                    return await process_url(
                        url, supplied_html, client=http_client, settings=settings
                    )
                except Exception as exc:  # a bug in one URL must never sink the batch
                    logger.exception("unexpected error scraping %s", url)
                    return ScrapeOutcome(url=url, error=f"unexpected error: {exc}")

        outcomes = await asyncio.gather(*(bounded(url) for url in url_list))

        successes = [outcome for outcome in outcomes if outcome.ok and outcome.files]
        if not successes:
            summary = "\n".join(f"{outcome.url}: {outcome.error}" for outcome in outcomes)
            return templates.TemplateResponse(
                request,
                "index.html",
                form_context(urls, html, f"Every URL failed:\n{summary}"),
                status_code=400,
            )

        errors = [f"{outcome.url}: {outcome.error}" for outcome in outcomes if not outcome.ok]
        errors.extend(
            f"{outcome.url}: {warning}" for outcome in outcomes for warning in outcome.warnings
        )

        zip_bytes = build_zip([outcome.files for outcome in successes if outcome.files], errors)
        filename = f"recipes-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


def _validate(urls: list[str], html: str, settings: Settings) -> str | None:
    if not urls:
        return "Provide at least one URL."
    if len(urls) > settings.max_urls_per_batch:
        return f"Too many URLs: max {settings.max_urls_per_batch} per batch."
    if html and len(urls) != 1:
        return "Pasted HTML is only valid together with exactly one URL."
    if html and len(html.encode("utf-8")) > settings.max_html_bytes:
        return f"Pasted HTML exceeds the {settings.max_html_bytes}-byte limit."
    return None


app = create_app()
