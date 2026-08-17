"""Pure image processing: raw bytes in, a web-safe JPEG out.

Fetching is elsewhere (fetching.py, SSRF-guarded); this module never touches the
network. Uncapped hero images get committed to a synced vault forever, so every
image is downsized and re-encoded before it ever reaches disk.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps


def process_image(data: bytes, *, max_edge: int, quality: int) -> bytes:
    """Convert to JPEG, cap the long edge at ``max_edge`` px, strip EXIF, re-encode.

    Raises whatever Pillow raises (e.g. UnidentifiedImageError) on unusable input --
    callers treat a failed image as a non-fatal warning, not a failed scrape.
    """
    with Image.open(io.BytesIO(data)) as opened:
        # Apply EXIF orientation before dropping the EXIF data that encodes it, and
        # convert to RGB so palette/CMYK/RGBA sources encode cleanly as JPEG.
        transposed = ImageOps.exif_transpose(opened)
        image: Image.Image = transposed if transposed is not None else opened
        if image.mode != "RGB":
            image = image.convert("RGB")

        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
