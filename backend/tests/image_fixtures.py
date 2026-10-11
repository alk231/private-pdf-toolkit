"""Generated images for the tests."""
from __future__ import annotations

import io
from typing import Any

from PIL import Image


def make_image(width: int = 120, height: int = 80, color: Any = (200, 40, 40), fmt: str = "PNG", mode: str = "RGB") -> bytes:
    image = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def image_mode(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        return image.mode
