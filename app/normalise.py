"""Text and metadata normalisation: decimals, fractions, units, language, time, filenames.

The Obsidian Recipe View plugin's scaling parser silently skips comma decimals and
never converts imperial units, so getting this wrong doesn't error -- it just quietly
produces a wrong recipe. See the brief's "Normalisation" section for the rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Comma between two digits is a decimal separator ("1,5 dl" -> "1.5 dl"); a comma
# between anything else (e.g. "salt, peber") is untouched.
_COMMA_DECIMAL = re.compile(r"(?<=\d),(?=\d)")

_UNICODE_FRACTIONS: dict[str, float] = {
    "½": 1 / 2,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "¼": 1 / 4,
    "¾": 3 / 4,
    "⅕": 1 / 5,
    "⅖": 2 / 5,
    "⅗": 3 / 5,
    "⅘": 4 / 5,
    "⅙": 1 / 6,
    "⅚": 5 / 6,
    "⅛": 1 / 8,
    "⅜": 3 / 8,
    "⅝": 5 / 8,
    "⅞": 7 / 8,
}
_UNICODE_FRACTION_CHARS = "".join(_UNICODE_FRACTIONS)
_WHOLE_PLUS_UNICODE_FRACTION = re.compile(rf"(\d+)\s*([{_UNICODE_FRACTION_CHARS}])")
_BARE_UNICODE_FRACTION = re.compile(f"[{_UNICODE_FRACTION_CHARS}]")
_WHOLE_PLUS_ASCII_FRACTION = re.compile(r"(\d+)[ \t]+(\d+)/(\d+)")
_BARE_ASCII_FRACTION = re.compile(r"(?<!\d)(\d+)/(\d+)(?!\d)")

_IMPERIAL_PATTERNS = (
    re.compile(r"\bcups?\b", re.IGNORECASE),
    re.compile(r"\boz\b", re.IGNORECASE),
    re.compile(r"\blbs?\b", re.IGNORECASE),
    re.compile(r"°f\b", re.IGNORECASE),
)

_FORBIDDEN_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RUN = re.compile(r"\s+")

_LEADING_INT = re.compile(r"\d+")


def _format_decimal(value: float) -> str:
    """Render a float to 3 decimal places, trimmed: 0.5, not 0.500; 0.125, not 0.12."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def convert_fractions(text: str) -> str:
    """Unicode and ASCII fractions -> decimals. '1 1/2' and '1 ½' both become '1.5'."""

    def whole_unicode(m: re.Match[str]) -> str:
        return _format_decimal(int(m.group(1)) + _UNICODE_FRACTIONS[m.group(2)])

    def whole_ascii(m: re.Match[str]) -> str:
        return _format_decimal(int(m.group(1)) + int(m.group(2)) / int(m.group(3)))

    def bare_unicode(m: re.Match[str]) -> str:
        return _format_decimal(_UNICODE_FRACTIONS[m.group(0)])

    def bare_ascii(m: re.Match[str]) -> str:
        return _format_decimal(int(m.group(1)) / int(m.group(2)))

    text = _WHOLE_PLUS_UNICODE_FRACTION.sub(whole_unicode, text)
    text = _BARE_UNICODE_FRACTION.sub(bare_unicode, text)
    text = _WHOLE_PLUS_ASCII_FRACTION.sub(whole_ascii, text)
    text = _BARE_ASCII_FRACTION.sub(bare_ascii, text)
    return text


def convert_decimal_commas(text: str) -> str:
    """'1,5 dl' -> '1.5 dl'. A comma not flanked by digits on both sides is untouched."""
    return _COMMA_DECIMAL.sub(".", text)


def normalise_quantities(text: str) -> str:
    """Apply both fraction and decimal-comma conversion, in the order that composes safely."""
    return convert_decimal_commas(convert_fractions(text))


def contains_imperial_units(texts: Iterable[str]) -> bool:
    """True if any text mentions cups, oz, lb, or °F. Detection only -- never convert."""
    return any(pattern.search(text) for text in texts for pattern in _IMPERIAL_PATTERNS)


def normalise_language(raw: str | None) -> str:
    """First two letters of the scraper's language code, lowercased. Defaults to 'en'."""
    if not raw:
        return "en"
    code = raw.strip()[:2].lower()
    return code or "en"


def format_time(minutes: int | None, lang: str) -> str | None:
    """45 -> '45 min'. Over 60 -> '1 t 15 min' in Danish, '1 h 15 min' otherwise."""
    if not minutes:
        return None
    if minutes <= 60:
        return f"{minutes} min"

    hours, rest = divmod(minutes, 60)
    unit = "t" if lang == "da" else "h"
    if rest:
        return f"{hours} {unit} {rest} min"
    return f"{hours} {unit}"


def parse_servings(raw: str | None) -> int | None:
    """Pull the leading integer out of a yields string like '4 servings'."""
    if not raw:
        return None
    match = _LEADING_INT.search(raw)
    return int(match.group()) if match else None


class InvalidFilenameError(ValueError):
    """Raised when a title sanitises down to nothing usable as a filename."""


def sanitise_filename(title: str) -> str:
    """Turn a recipe title into a filesystem-safe stem. Keeps æøåÆØÅ and spaces."""
    text = _FORBIDDEN_FILENAME_CHARS.sub("", title)
    text = _CONTROL_CHARS.sub("", text)
    text = _WHITESPACE_RUN.sub(" ", text).strip()
    text = text[:100].strip()
    if not text:
        raise InvalidFilenameError(f"title {title!r} sanitises to an empty filename")
    return text
