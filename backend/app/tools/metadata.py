"""Read or edit PDF document properties (title, author, subject, keywords, creator, producer).

Fields you send are set; an empty string removes that field; fields you omit (or send as null) stay as they are.
clear_all removes every property. Changing anything also removes the XMP packet, which would otherwise
override the edited values in some viewers. action "read" changes nothing and reports the current values.
"""
from __future__ import annotations

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pdfutil import get_password, open_pdf, save_pdf, single_result

FIELDS = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
    "creator": "/Creator",
    "producer": "/Producer",
}
MAX_VALUE = 500
REPORT_LIMIT = 200


def _read(pdf) -> dict[str, str]:
    info = pdf.docinfo
    result: dict[str, str] = {}
    for key, name in FIELDS.items():
        if name in info:
            try:
                text = str(info[name])
            except Exception:
                continue
            if text:
                result[key] = text[:REPORT_LIMIT]
    return result


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    action = ctx.opt_str("action", "edit", allowed=("edit", "read"))
    clear_all = ctx.opt_bool("clear_all", False)

    changes: dict[str, str] = {}
    for key in FIELDS:
        if key not in ctx.options or ctx.options[key] is None:
            continue
        value = ctx.options[key]
        if not isinstance(value, str) or len(value) > MAX_VALUE:
            raise ToolError("invalid_options", f"The option '{key}' must be text of up to {MAX_VALUE} characters.")
        changes[key] = value.replace("\x00", "").strip()
    if action == "edit" and not changes and not clear_all:
        raise ToolError(
            "invalid_options",
            "Enter at least one property to change, or choose to remove all metadata.",
        )

    dest = ctx.out_path("metadata.pdf")
    with open_pdf(item.path, get_password(ctx)) as pdf:
        total = len(pdf.pages)
        xmp_removed = False
        if action == "edit":
            info = pdf.docinfo
            if clear_all:
                for name in list(info.keys()):
                    del info[name]
            for key, value in changes.items():
                name = FIELDS[key]
                if value:
                    info[name] = value
                elif name in info:
                    del info[name]
            if "/Metadata" in pdf.Root:
                del pdf.Root["/Metadata"]
                xmp_removed = True
        ctx.progress(50)
        current = _read(pdf)
        save_pdf(pdf, dest)

    result = single_result(ctx, dest, "metadata", total, total)
    result.meta["metadata"] = current
    result.meta["action"] = action
    result.meta["xmp_removed"] = xmp_removed
    return result
