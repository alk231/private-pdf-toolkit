"""PyMuPDF helpers shared by the tools. Imports PyMuPDF: import this only from tool modules (worker)."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from app.tools.base import ToolError

_COLOR = re.compile(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def open_doc(path: Path, password: str = "", label: str = "this PDF") -> pymupdf.Document:
    """Open a PDF with PyMuPDF; map password problems to friendly errors."""
    try:
        doc = pymupdf.open(str(path), filetype="pdf")
    except MemoryError:
        raise
    except Exception as exc:
        raise ToolError("corrupted_file") from exc
    try:
        if doc.needs_pass:
            if not password:
                first = label[:1].upper() + label[1:]
                raise ToolError(
                    "password_required",
                    f"{first} is password-protected. Enter its password to continue.",
                )
            if not doc.authenticate(password):
                raise ToolError("wrong_password", f"The password for {label} is incorrect.")
        if doc.page_count == 0:
            raise ToolError("corrupted_file")
    except BaseException:
        doc.close()
        raise
    return doc


def save_doc(doc: pymupdf.Document, dest: Path) -> None:
    """Save compactly and without encryption (outputs are always unencrypted)."""
    doc.save(str(dest), garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_NONE)


def parse_color(text: str) -> tuple[float, float, float]:
    match = _COLOR.fullmatch(text.strip())
    if match is None:
        raise ToolError("invalid_options", "Colors must look like #RRGGBB, for example #808080.")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return (
        int(digits[0:2], 16) / 255.0,
        int(digits[2:4], 16) / 255.0,
        int(digits[4:6], 16) / 255.0,
    )


def latin_text(text: str) -> str:
    """Text for the built-in Helvetica font: Latin-1 only. Whitespace is collapsed to single spaces."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ToolError("invalid_options", "Enter the text to add.")
    if any(ord(ch) > 255 or not ch.isprintable() for ch in cleaned):
        raise ToolError(
            "invalid_options",
            "Text can use Latin letters, digits and common symbols. "
            "For other alphabets, use an image watermark instead.",
        )
    return cleaned


def text_width(text: str, size: float) -> float:
    return float(pymupdf.get_text_length(text, fontname="helv", fontsize=size))
