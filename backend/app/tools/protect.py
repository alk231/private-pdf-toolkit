"""Protect a PDF with a password (AES-256 by default; AES-128 for old readers)."""
from __future__ import annotations

import secrets

import pikepdf

from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.pdfutil import get_password, open_pdf, single_result

MAX_PASSWORD = 100


def _password(ctx: ToolContext, key: str, *, required: bool) -> str:
    value = ctx.options.get(key)
    if value is None or value == "":
        if required:
            raise ToolError("invalid_options", "Enter a password to protect the PDF.")
        return ""
    if not isinstance(value, str) or len(value) > MAX_PASSWORD:
        raise ToolError(
            "invalid_options",
            f"The password must be text of up to {MAX_PASSWORD} characters.",
        )
    return value


def run(ctx: ToolContext) -> ToolResult:
    item = ctx.inputs[0]
    new_password = _password(ctx, "password", required=True)
    owner = _password(ctx, "owner_password", required=False) or secrets.token_urlsafe(24)
    strength = ctx.opt_str("strength", "256", allowed=("256", "128"))
    allow_print = ctx.opt_bool("allow_print", True)
    allow_copy = ctx.opt_bool("allow_copy", True)
    allow_modify = ctx.opt_bool("allow_modify", True)

    permissions = pikepdf.Permissions(
        accessibility=True,
        extract=allow_copy,
        modify_annotation=allow_modify,
        modify_assembly=allow_modify,
        modify_form=allow_modify,
        modify_other=allow_modify,
        print_lowres=allow_print,
        print_highres=allow_print,
    )
    encryption = pikepdf.Encryption(
        user=new_password,
        owner=owner,
        allow=permissions,
        R=6 if strength == "256" else 4,
    )

    dest = ctx.out_path("protected.pdf")
    with open_pdf(item.path, get_password(ctx, "current_password")) as pdf:
        total = len(pdf.pages)
        ctx.progress(40)
        pdf.save(
            dest,
            encryption=encryption,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )

    result = single_result(ctx, dest, "protected", total, total)
    result.meta["encryption"] = f"AES-{strength}"
    return result
