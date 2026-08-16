"""Environment-driven configuration. Env vars only -- no .env file ships in the image."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_user_agent() -> str:
    try:
        version = _pkg_version("recipe2md")
    except PackageNotFoundError:
        version = "0.0.0"
    return f"recipe2md/{version}"


class Settings(BaseSettings):
    """Application settings, read once at startup. Tests construct their own instead."""

    model_config = SettingsConfigDict(extra="ignore")

    max_html_bytes: int = Field(default=5_242_880, gt=0)
    max_urls_per_batch: int = Field(default=25, gt=0)
    request_timeout: float = Field(default=20.0, gt=0)
    scrape_concurrency: int = Field(default=4, gt=0)
    user_agent: str = Field(default_factory=_default_user_agent)
    image_max_edge: int = Field(default=1600, gt=0)
    image_quality: int = Field(default=85, ge=1, le=100)
    allow_private_urls: bool = False
    log_level: str = "INFO"
