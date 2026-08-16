"""Unit tests for normalise.py -- the regex/decimal/fraction logic where silent
wrongness lives."""

from __future__ import annotations

import pytest

from app.normalise import (
    InvalidFilenameError,
    contains_imperial_units,
    convert_decimal_commas,
    convert_fractions,
    format_time,
    normalise_language,
    parse_servings,
    sanitise_filename,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,5 dl", "1.5 dl"),
        ("3,25 kg", "3.25 kg"),
        ("salt, peber", "salt, peber"),
        ("1 løg, finthakket", "1 løg, finthakket"),
        ("1,5 dl and 2,25 kg", "1.5 dl and 2.25 kg"),
    ],
)
def test_convert_decimal_commas(raw: str, expected: str) -> None:
    assert convert_decimal_commas(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("½ tsp salt", "0.5 tsp salt"),
        ("¼ cup sugar", "0.25 cup sugar"),
        ("¾ cup flour", "0.75 cup flour"),
        ("⅓ cup oil", "0.333 cup oil"),
        ("⅔ cup water", "0.667 cup water"),
        ("⅛ tsp cinnamon", "0.125 tsp cinnamon"),
        ("1 1/2 cups milk", "1.5 cups milk"),
        ("1½ cups milk", "1.5 cups milk"),
        ("3/4 cup butter", "0.75 cup butter"),
        ("2 eggs", "2 eggs"),
        ("10/20 ratio", "0.5 ratio"),
    ],
)
def test_convert_fractions(raw: str, expected: str) -> None:
    assert convert_fractions(raw) == expected


@pytest.mark.parametrize(
    "texts",
    [
        ["1 cup flour"],
        ["2 Cups flour"],
        ["8 oz chocolate"],
        ["1 lb butter"],
        ["1 lbs butter"],
        ["Bake at 350°F"],
    ],
)
def test_contains_imperial_units_detects(texts: list[str]) -> None:
    assert contains_imperial_units(texts) is True


@pytest.mark.parametrize(
    "texts",
    [
        ["300 g flour"],
        ["1 dl milk"],
        ["500 ml stock"],
        ["a cupcake tin"],  # "cup" must not match inside another word
        ["scoop of ice cream"],
    ],
)
def test_contains_imperial_units_ignores_metric_and_partial_words(texts: list[str]) -> None:
    assert contains_imperial_units(texts) is False


def test_normalise_language_defaults_to_en() -> None:
    assert normalise_language(None) == "en"
    assert normalise_language("") == "en"


def test_normalise_language_takes_first_two_letters_lowercased() -> None:
    assert normalise_language("DA") == "da"
    assert normalise_language("en-US") == "en"
    assert normalise_language("da-DK") == "da"


@pytest.mark.parametrize(
    ("minutes", "lang", "expected"),
    [
        (None, "en", None),
        (0, "en", None),
        (45, "en", "45 min"),
        (60, "en", "60 min"),
        (75, "en", "1 h 15 min"),
        (75, "da", "1 t 15 min"),
        (120, "en", "2 h"),
        (120, "da", "2 t"),
    ],
)
def test_format_time(minutes: int | None, lang: str, expected: str | None) -> None:
    assert format_time(minutes, lang) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("4 servings", 4),
        ("Serves 4-6", 4),
        ("12", 12),
    ],
)
def test_parse_servings(raw: str | None, expected: int | None) -> None:
    assert parse_servings(raw) == expected


def test_sanitise_filename_keeps_danish_letters_and_spaces() -> None:
    assert sanitise_filename("Boller i Karry") == "Boller i Karry"
    assert sanitise_filename("Rødgrød med Fløde") == "Rødgrød med Fløde"


def test_sanitise_filename_strips_forbidden_characters() -> None:
    assert sanitise_filename('Mac & Cheese: "The Best"') == "Mac & Cheese The Best"
    assert sanitise_filename("A/B Test Recipe?") == "AB Test Recipe"


def test_sanitise_filename_collapses_whitespace_and_trims() -> None:
    assert sanitise_filename("  Too   Many   Spaces  ") == "Too Many Spaces"
    assert sanitise_filename("x" * 150) == "x" * 100


def test_sanitise_filename_rejects_empty_result() -> None:
    with pytest.raises(InvalidFilenameError):
        sanitise_filename("***///???")
    with pytest.raises(InvalidFilenameError):
        sanitise_filename("   ")
