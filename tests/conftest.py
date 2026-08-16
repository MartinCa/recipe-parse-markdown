from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

_SETTINGS_ENV_VARS = (
    "MAX_HTML_BYTES",
    "MAX_URLS_PER_BATCH",
    "REQUEST_TIMEOUT",
    "SCRAPE_CONCURRENCY",
    "USER_AGENT",
    "IMAGE_MAX_EDGE",
    "IMAGE_QUALITY",
    "ALLOW_PRIVATE_URLS",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the host environment from leaking into Settings under test."""
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
