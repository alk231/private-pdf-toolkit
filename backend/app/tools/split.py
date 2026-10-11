"""Split one PDF into several: by page ranges (one file per range) or every N pages."""
from __future__ import annotations

import pikepdf

from app.tools.base import OutputFile, ToolContext, ToolError, ToolResult
from app.tools.pagespec import parse_groups, unique
from app.tools.pdfutil import (
    PDF_MIME,
    copy_pages,
    get_password,
    make_meta,
    open_pdf,
    pages_option,
    save_pdf,
)

MAX_PARTS = 200


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    mode = ctx.opt_str("mode", "ranges", allowed=("ranges", "every"))
    password = get_password(ctx)

    with open_pdf(item.path, password) as source:
        total = len(source.pages)

        if mode == "every":
            step = ctx.opt_int("every", 1, minimum=1, maximum=100_000)
            groups = [list(range(start, min(start + step, total))) for start in range(0, total, step)]
            if len(groups) < 2:
                raise ToolError(
                    "invalid_options",
                    f"Splitting every {step} page(s) would give only one file. "
                    f"This PDF has {total} page(s).",
                )
        else:
            groups = [
                unique(group)
                for group in parse_groups(pages_option(ctx, "ranges"), total, allow_reverse=False)
            ]

        if len(groups) > MAX_PARTS:
            raise ToolError(
                "invalid_options",
                f"That would create more than {MAX_PARTS} files. Choose fewer ranges or a larger number.",
            )

        stem = item.stem[:80]
        width = len(str(len(groups)))
        outputs: list[OutputFile] = []
        for number, group in enumerate(groups, start=1):
            dest = ctx.out_path(f"part_{number:03d}.pdf")
            with copy_pages(source, group) as part:
                save_pdf(part, dest)
            outputs.append(OutputFile(dest, f"{stem}_part{str(number).zfill(width)}.pdf", PDF_MIME))
            ctx.progress(5 + 90 * number // len(groups))

    meta = make_meta(ctx, [o.path for o in outputs], total, sum(len(g) for g in groups))
    meta["parts"] = len(outputs)
    return ToolResult(outputs=outputs, meta=meta, zip_name=f"{stem}_split.zip")
