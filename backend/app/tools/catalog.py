"""Declarative list of tools. Light on purpose: the API process imports this, never the tool code."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class ToolSpec:
    name: str  # URL segment: POST /v1/tools/{name}
    module: str  # module with run(ctx: ToolContext) -> ToolResult (imported only in the worker)
    accepts: tuple[str, ...]  # allowed file kinds: "pdf", "image", ...
    min_files: int = 1
    max_files: int = 1
    fast: bool = False  # may answer directly when called with ?wait=true
    timeout_factor: float = 1.0  # multiplies JOB_TIMEOUT_SEC
    memory_mb: int | None = None  # overrides WORKER_MEMORY_MB
    internal: bool = False  # test-only tools, hidden unless ENABLE_SELFTEST_TOOLS=1

_SELFTEST_MODULE = "app.tools.selftest"

def _selftest(name: str, *, fast: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        module=_SELFTEST_MODULE,
        accepts=("pdf",),
        min_files=1,
        max_files=3,
        fast=fast,
        internal=True,
    )

def _page_tool(
    name: str,
    module: str,
    *,
    min_files: int = 1,
    max_files: int = 1,
    fast: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        module=f"app.tools.{module}",
        accepts=("pdf",),
        min_files=min_files,
        max_files=max_files,
        fast=fast,
    )

def _tool(
    name: str,
    module: str,
    accepts: tuple[str, ...] = ("pdf",),
    *,
    min_files: int = 1,
    max_files: int = 1,
    fast: bool = False,
    timeout_factor: float = 1.0,
    memory_mb: int | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        module=f"app.tools.{module}",
        accepts=accepts,
        min_files=min_files,
        max_files=max_files,
        fast=fast,
        timeout_factor=timeout_factor,
        memory_mb=memory_mb,
    )

_SELFTEST_TOOLS: tuple[ToolSpec, ...] = (
    _selftest("selftest-copy", fast=True),
    _selftest("selftest-multi"),
    _selftest("selftest-fail"),
    _selftest("selftest-sleep"),
    _selftest("selftest-crash"),
)

# Stage 2: page tools.
_PAGE_TOOLS: tuple[ToolSpec, ...] = (
    _page_tool("merge", "merge", min_files=2, max_files=20),
    _page_tool("split", "split", fast=False),
    _page_tool("extract-pages", "extract_pages"),
    _page_tool("remove-pages", "remove_pages"),
    _page_tool("reorder", "reorder"),
    _page_tool("rotate", "rotate"),
    _page_tool("crop", "crop"),
)

# Stage 3: conversion, optimisation, security and editing tools.
_STAGE3_TOOLS: tuple[ToolSpec, ...] = (
    _tool("images-to-pdf", "images_to_pdf", ("image",), max_files=30, timeout_factor=1.5, memory_mb=1536),
    _tool("pdf-to-images", "pdf_to_images", timeout_factor=2.0, memory_mb=1536),
    _tool("compress", "compress", timeout_factor=2.0, memory_mb=1536),
    _tool("protect", "protect", fast=True),
    _tool("unlock", "unlock", fast=True),
    _tool("page-numbers", "page_numbers", fast=True, memory_mb=1536),
    _tool("watermark", "watermark", ("pdf", "image"), max_files=2, fast=True, memory_mb=1536),
    _tool("metadata", "metadata"),
)

_ALL_TOOLS: tuple[ToolSpec, ...] = _SELFTEST_TOOLS + _PAGE_TOOLS + _STAGE3_TOOLS

_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in _ALL_TOOLS}

def get_tool(name: str, *, include_internal: bool = False) -> ToolSpec | None:
    spec = _BY_NAME.get(name)
    if spec is None or (spec.internal and not include_internal):
        return None
    return spec

def list_tools(*, include_internal: bool = False) -> list[ToolSpec]:
    return [t for t in _ALL_TOOLS if include_internal or not t.internal]
