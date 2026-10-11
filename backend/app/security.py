"""Upload safety helpers: filename sanitising, magic-byte detection, device id, client IP."""
from __future__ import annotations

import ipaddress
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

_UNSAFE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')
_DROP_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}  # control, format (e.g. bidi override), etc.
_MAX_NAME_LEN = 100
_MAX_EXT_LEN = 10

def sanitize_filename(name: str | None, default: str = "file") -> str:
    """Return a safe, short file name (no path parts, no control characters)."""
    if not name:
        return default
    text = unicodedata.normalize("NFKC", str(name))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _DROP_CATEGORIES)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = _UNSAFE_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"_{2,}", "_", text)
    text = text.strip(" .")
    if not text:
        return default
    stem, ext = os.path.splitext(text)
    ext = ext[:_MAX_EXT_LEN]
    stem = stem[: _MAX_NAME_LEN - len(ext)].strip(" .")
    if not stem:
        return default
    return stem + ext

@dataclass(frozen=True)
class Detected:
    kind: str  # "pdf" or "image" (Wave 2 adds "office" and "html")
    ext: str  # extension used for the on-disk copy

def detect_file_type(header: bytes) -> Detected | None:
    """Identify a file from its first bytes. Extensions and client MIME types are never trusted."""
    if b"%PDF-" in header[:1024]:
        return Detected("pdf", ".pdf")
    if header.startswith(b"\xff\xd8\xff"):
        return Detected("image", ".jpg")
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detected("image", ".png")
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return Detected("image", ".webp")
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return Detected("image", ".gif")
    if header[:2] == b"BM" and len(header) >= 14 and header[6:10] == b"\x00\x00\x00\x00":
        return Detected("image", ".bmp")
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return Detected("image", ".tiff")
    return None

def parse_device_id(value: str | None) -> str | None:
    """Return a normalised UUID string, or None if the header is missing or malformed."""
    if not value or len(value) > 64:
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return None

def client_ip(request: Any, trust_proxy: bool) -> str:
    """Best-effort client IP for rate limiting (duck-typed so it is easy to unit test)."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(first))
            except ValueError:
                pass
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or "unknown"
