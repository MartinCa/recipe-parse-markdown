"""Unit tests for images.py: resizing, format conversion, EXIF stripping."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.images import process_image


def _make_image(size: tuple[int, int], mode: str = "RGB", fmt: str = "PNG") -> bytes:
    image = Image.new(mode, size, color=(120, 40, 200) if mode == "RGB" else 100)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_process_image_converts_to_jpeg() -> None:
    data = _make_image((100, 100))

    result = process_image(data, max_edge=1600, quality=85)

    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"


def test_process_image_caps_the_long_edge() -> None:
    data = _make_image((3000, 1000))

    result = process_image(data, max_edge=1600, quality=85)

    with Image.open(io.BytesIO(result)) as image:
        assert max(image.size) <= 1600
        # Aspect ratio is preserved.
        assert image.size[0] / image.size[1] == pytest.approx(3000 / 1000, rel=0.02)


def test_process_image_leaves_small_images_unresized() -> None:
    data = _make_image((400, 300))

    result = process_image(data, max_edge=1600, quality=85)

    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (400, 300)


def test_process_image_converts_non_rgb_modes() -> None:
    data = _make_image((200, 200), mode="L")

    result = process_image(data, max_edge=1600, quality=85)

    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGB"


def test_process_image_strips_exif() -> None:
    image = Image.new("RGB", (100, 100), color=(10, 20, 30))
    exif = image.getexif()
    exif[0x0112] = 3  # Orientation tag
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)

    result = process_image(buffer.getvalue(), max_edge=1600, quality=85)

    with Image.open(io.BytesIO(result)) as processed:
        assert not processed.getexif()


def test_process_image_raises_on_garbage_input() -> None:
    with pytest.raises(Exception):  # noqa: B017 -- whatever Pillow throws for bad input
        process_image(b"not an image", max_edge=1600, quality=85)
