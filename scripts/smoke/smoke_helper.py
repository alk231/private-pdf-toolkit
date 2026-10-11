#!/usr/bin/env python3
"""Helper for the PDF Toolkit smoke tests: sample files and output validation.

Needs pikepdf, PyMuPDF and Pillow (all are in backend/requirements.txt).
Every file argument is relative to --workdir.
Prints "OK: ..." or "FAIL: ..." and exits 0 (ok) or 1 (check failed).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import zipfile

try:
    import fitz  # PyMuPDF
    import pikepdf
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    print(
        f"FAIL: missing Python package ({exc.name}); run "
        "pip install -r backend/requirements.txt or use -HelperMode docker"
    )
    sys.exit(2)

WORKDIR = "."


def p(name: str) -> str:
    return name if os.path.isabs(name) else os.path.join(WORKDIR, name)


def ok(message: str) -> int:
    print("OK: " + message)
    return 0


def fail(messages) -> int:
    print("FAIL: " + "; ".join(messages))
    return 1


def norm(text: str) -> str:
    return " ".join(text.split())


# --------------------------------------------------------------------------
# sample generation
# --------------------------------------------------------------------------

def make_pdf(name, pages, label, password=None, meta=None):
    """Page n is 100+10n pt wide and 200 pt tall, with the text 'SRC <label> p<n>'."""
    path = p(name)
    doc = fitz.open()
    for n in range(1, pages + 1):
        page = doc.new_page(width=100 + 10 * n, height=200)
        page.insert_text((8, 24), f"SRC {label} p{n}", fontsize=9)
    if meta:
        doc.set_metadata(meta)
    if password is None:
        doc.save(path)
        doc.close()
        return
    tmp = path + ".tmp"
    doc.save(tmp)
    doc.close()
    with pikepdf.open(tmp) as pdf:
        pdf.save(
            path,
            encryption=pikepdf.Encryption(user=password, owner=password + "-owner", R=6),
        )
    os.remove(tmp)


def sample_image(w, h, mode, bg, fg, fg2):
    img = Image.new(mode, (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([w // 10, h // 10, w * 9 // 10, h * 9 // 10], fill=fg)
    d.line([(0, 0), (w, h)], fill=fg2, width=max(2, w // 60))
    d.line([(0, h), (w, 0)], fill=fg2, width=max(2, w // 60))
    return img


def noisy_jpeg(w, h, sigma, quality):
    """A JPEG that does not compress well (random noise blended with a tint)."""
    base = Image.effect_noise((w, h), sigma).convert("RGB")
    tint = Image.new(
        "RGB", (w, h),
        (random.randint(40, 215), random.randint(40, 215), random.randint(40, 215)),
    )
    img = Image.blend(base, tint, 0.5)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def cmd_samples(a):
    make_pdf("a.pdf", 5, "a")
    make_pdf("b.pdf", 3, "b")
    make_pdf("c.pdf", 12, "c")
    make_pdf("locked.pdf", 4, "locked", password="open-sesame")
    make_pdf(
        "meta.pdf", 2, "meta",
        meta={"title": "Smoke Title", "author": "Smoke Author", "subject": "Smoke Subject"},
    )

    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=noisy_jpeg(2000, 2800, 30, 85))
    doc.save(p("scan.pdf"))
    doc.close()

    sample_image(800, 600, "RGB", (240, 240, 255), (30, 90, 200), (255, 140, 0)).save(
        p("photo1.jpg"), "JPEG", quality=90)
    sample_image(640, 480, "RGBA", (255, 255, 255, 0), (200, 40, 40, 255), (0, 0, 0, 255)).save(
        p("photo2.png"), "PNG")
    sample_image(400, 700, "RGB", (255, 250, 230), (20, 140, 80), (120, 0, 120)).save(
        p("photo3.jpg"), "JPEG", quality=90)
    sample_image(160, 80, "RGBA", (0, 0, 0, 0), (220, 30, 30, 255), (255, 255, 255, 255)).save(
        p("logo.png"), "PNG")

    with open(p("notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("this is plain text, not a PDF\n")

    names = sorted(n for n in os.listdir(WORKDIR) if os.path.isfile(p(n)))
    return ok("samples ready: " + ", ".join(names))


def cmd_heavy(a):
    """Large inputs for the real-limits test (Part 4)."""
    target = int(a.mb * 1024 * 1024)
    images, total = [], 0
    while total < target and len(images) < 60:
        data = noisy_jpeg(1654, 2339, 50, 88)
        images.append(data)
        total += len(data)
    doc = fitz.open()
    for n in range(a.pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(30, 50, 565, 806), stream=images[n % len(images)])
        page.insert_text((36, 30), f"HEAVY page {n + 1}", fontsize=10)
    doc.save(p("heavy_doc.pdf"))
    doc.close()
    lines = [f"heavy_doc.pdf {os.path.getsize(p('heavy_doc.pdf')) / 1048576:.1f} MiB, {a.pages} pages"]
    for i in range(1, a.photos + 1):
        name = f"photo_big_{i}.jpg"
        with open(p(name), "wb") as fh:
            fh.write(noisy_jpeg(a.photo_w, a.photo_h, 20, 88))
        lines.append(f"{name} {os.path.getsize(p(name)) / 1048576:.1f} MiB")
    return ok("; ".join(lines))


def cmd_bigfile(a):
    """A file starting with %PDF- that is (over_mb + 1) MiB large."""
    size = int((a.over_mb + 1) * 1024 * 1024)
    chunk = (b"%" + b"x" * 1022 + b"\n") * 64  # 64 KiB
    with open(p(a.name), "wb") as fh:
        fh.write(b"%PDF-1.4\n")
        written = 9
        while written < size:
            fh.write(chunk)
            written += len(chunk)
    return ok(f"{a.name} is {os.path.getsize(p(a.name)) / 1048576:.1f} MiB")


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def cmd_has_magic(a):
    path = p(a.name)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return fail([f"{a.name} is missing or empty"])
    with open(path, "rb") as fh:
        head = fh.read(8)
    magic = {
        "pdf": b"%PDF-",
        "zip": b"PK\x03\x04",
        "png": b"\x89PNG",
        "jpg": b"\xff\xd8\xff",
    }[a.kind]
    if head.startswith(magic):
        return ok(f"{a.name} looks like {a.kind}")
    return fail([f"{a.name} is not {a.kind} (first bytes {head[:6]!r})"])


def cmd_check_pdf(a):
    path = p(a.name)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return fail([f"{a.name} is missing or empty"])
    with open(path, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            return fail(["not a PDF (bad magic bytes)"])

    errors, notes = [], []
    opens_plain = True
    try:
        pikepdf.open(path).close()
    except pikepdf.PasswordError:
        opens_plain = False
    except Exception as exc:
        return fail([f"pikepdf cannot open the file: {exc}"])
    if a.encrypted and opens_plain:
        errors.append("expected a password but the file opens without one")

    password = a.password or ""
    try:
        pdf = pikepdf.open(path, password=password)
    except pikepdf.PasswordError:
        return fail(errors + ["cannot open with the given password"])
    except Exception as exc:
        return fail(errors + [f"pikepdf cannot open the file: {exc}"])

    with pdf:
        n = len(pdf.pages)
        still_encrypted = bool(pdf.is_encrypted)
        docinfo = {}
        try:
            for key, value in pdf.docinfo.items():
                docinfo[str(key).lstrip("/").lower()] = str(value)
        except Exception:
            pass

    if a.plain and still_encrypted:
        errors.append("expected no encryption but the file is still encrypted")
    if a.pages is not None and n != a.pages:
        errors.append(f"pages={n}, expected {a.pages}")
    notes.append(f"pages={n}")

    for spec in a.meta or []:
        key, _, want = spec.partition("=")
        got = docinfo.get(key.lower())
        if got != want:
            errors.append(f"{key}={got!r}, expected {want!r}")
    for key in a.no_meta or []:
        if docinfo.get(key.lower()):
            errors.append(f"{key} should be absent but is {docinfo[key.lower()]!r}")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return fail(errors + [f"PyMuPDF cannot open the file: {exc}"])
    try:
        authed = True
        if doc.needs_pass:
            authed = bool(doc.authenticate(password))
            if not authed:
                errors.append("PyMuPDF cannot authenticate with the given password")
        if authed:
            if doc.page_count != n:
                errors.append("pikepdf and PyMuPDF disagree about the page count")
            try:
                if n:
                    doc[0].get_pixmap(dpi=20)
            except Exception as exc:
                errors.append(f"cannot render page 1: {exc}")
            try:
                errors.extend(page_checks(a, doc, notes))
            except Exception as exc:
                errors.append(f"check error: {exc}")
    finally:
        doc.close()

    if errors:
        return fail(errors)
    return ok(" ".join(notes))


def page_checks(a, doc, notes):
    errors = []
    count = doc.page_count

    if a.widths or a.widths_start:
        got = [doc[i].mediabox.width for i in range(count)]
        if a.widths:
            want = [float(x) for x in a.widths.split(",")]
            if len(got) != len(want) or any(abs(g - w) > 0.6 for g, w in zip(got, want)):
                errors.append(f"widths={[round(g, 1) for g in got]}, expected {want}")
        if a.widths_start:
            want = [float(x) for x in a.widths_start.split(",")]
            head = got[: len(want)]
            if len(head) != len(want) or any(abs(g - w) > 0.6 for g, w in zip(head, want)):
                errors.append(f"widths start {[round(g, 1) for g in head]}, expected {want}")

    if a.rotations:
        want = [int(x) for x in a.rotations.split(",")]
        got = [doc[i].rotation for i in range(count)]
        if got != want:
            errors.append(f"rotations={got}, expected {want}")

    for spec in a.box or []:
        num, w, h = spec.split(":")
        rect = doc[int(num) - 1].cropbox
        if abs(rect.width - float(w)) > 1.0 or abs(rect.height - float(h)) > 1.0:
            errors.append(f"page {num} box={rect.width:.1f}x{rect.height:.1f}, expected {w}x{h}")

    if a.a4:
        for i in range(count):
            rect = doc[i].cropbox
            dims = sorted((rect.width, rect.height))
            if abs(dims[0] - 595) > 1.5 or abs(dims[1] - 842) > 1.5:
                errors.append(f"page {i + 1} is {rect.width:.1f}x{rect.height:.1f}, not A4")

    for spec in a.text or []:
        num, _, needle = spec.partition(":")
        txt = norm(doc[int(num) - 1].get_text())
        if norm(needle) not in txt:
            errors.append(f"page {num} text {txt[:60]!r} does not contain {needle!r}")
    for spec in a.no_text or []:
        num, _, needle = spec.partition(":")
        txt = norm(doc[int(num) - 1].get_text())
        if norm(needle) in txt:
            errors.append(f"page {num} text unexpectedly contains {needle!r}")

    if a.differs:
        orig = fitz.open(p(a.differs))
        try:
            for pg in [int(x) for x in a.differs_pages.split(",")]:
                pa = doc[pg - 1].get_pixmap(dpi=40)
                pb = orig[pg - 1].get_pixmap(dpi=40)
                if (pa.width, pa.height) != (pb.width, pb.height):
                    errors.append(f"page {pg} has a different size from the original")
                    continue
                changed = sum(1 for x, y in zip(pa.samples, pb.samples) if x != y)
                if changed == 0:
                    errors.append(f"page {pg} looks identical to the original")
                notes.append(f"p{pg}_changed_bytes={changed}")
        finally:
            orig.close()
    return errors


def cmd_check_zip(a):
    path = p(a.name)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return fail([f"{a.name} is missing or empty"])
    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        return fail([f"not a valid zip: {exc}"])
    errors, pages = [], []
    with zf:
        bad = zf.testzip()
        if bad:
            errors.append(f"corrupt zip entry {bad}")
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if a.entries is not None and len(names) != a.entries:
            errors.append(f"{len(names)} entries {names}, expected {a.entries}")
        for name in names:
            if a.ext and not name.lower().endswith("." + a.ext.lower()):
                errors.append(f"{name} does not end with .{a.ext}")
            if a.contains and a.contains not in name:
                errors.append(f"{name} does not contain {a.contains!r}")
            data = zf.read(name)
            if a.kind == "pdf":
                try:
                    with pikepdf.open(io.BytesIO(data)) as pdf:
                        pages.append(len(pdf.pages))
                except Exception as exc:
                    errors.append(f"{name}: invalid PDF ({exc})")
            elif a.kind == "image":
                try:
                    img = Image.open(io.BytesIO(data))
                    img.load()
                    if a.format and img.format != a.format.upper():
                        errors.append(f"{name}: format {img.format}, expected {a.format}")
                except Exception as exc:
                    errors.append(f"{name}: invalid image ({exc})")
    if a.pages is not None:
        want = sorted(int(x) for x in a.pages.split(","))
        if sorted(pages) != want:
            errors.append(f"entry page counts {sorted(pages)}, expected {want}")
    if errors:
        return fail(errors)
    return ok(f"{len(names)} entries" + (f", pages={sorted(pages)}" if pages else ""))


def cmd_check_image(a):
    path = p(a.name)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return fail([f"{a.name} is missing or empty"])
    try:
        with Image.open(path) as img:
            img.load()
            fmt, size = img.format, img.size
    except Exception as exc:
        return fail([f"not a valid image: {exc}"])
    errors = []
    if a.format and fmt != a.format.upper():
        errors.append(f"format {fmt}, expected {a.format}")
    if a.size:
        w, h = (int(x) for x in a.size.split(":"))
        if abs(size[0] - w) > a.tolerance or abs(size[1] - h) > a.tolerance:
            errors.append(f"size {size[0]}x{size[1]}, expected {w}x{h} (+/-{a.tolerance})")
    if errors:
        return fail(errors)
    return ok(f"{fmt} {size[0]}x{size[1]}")


def cmd_json_get(a):
    try:
        with open(p(a.name), "r", encoding="utf-8") as fh:
            cur = json.load(fh)
    except Exception:
        return 1
    for part in a.path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return 1
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return 1
    if isinstance(cur, bool):
        print("true" if cur else "false")
    elif cur is None:
        print("null")
    elif isinstance(cur, (dict, list)):
        print(json.dumps(cur))
    else:
        print(cur)
    return 0


# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("samples").set_defaults(func=cmd_samples)

    s = sub.add_parser("heavy")
    s.add_argument("--mb", type=float, default=20.0)
    s.add_argument("--pages", type=int, default=60)
    s.add_argument("--photos", type=int, default=6)
    s.add_argument("--photo-w", dest="photo_w", type=int, default=4000)
    s.add_argument("--photo-h", dest="photo_h", type=int, default=3000)
    s.set_defaults(func=cmd_heavy)

    s = sub.add_parser("bigfile")
    s.add_argument("name")
    s.add_argument("--over-mb", dest="over_mb", type=float, required=True)
    s.set_defaults(func=cmd_bigfile)

    s = sub.add_parser("has-magic")
    s.add_argument("name")
    s.add_argument("kind", choices=["pdf", "zip", "png", "jpg"])
    s.set_defaults(func=cmd_has_magic)

    s = sub.add_parser("check-pdf")
    s.add_argument("name")
    s.add_argument("--pages", type=int)
    s.add_argument("--password")
    s.add_argument("--encrypted", action="store_true")
    s.add_argument("--plain", action="store_true")
    s.add_argument("--widths")
    s.add_argument("--widths-start", dest="widths_start")
    s.add_argument("--rotations")
    s.add_argument("--box", action="append")
    s.add_argument("--a4", action="store_true")
    s.add_argument("--text", action="append")
    s.add_argument("--no-text", dest="no_text", action="append")
    s.add_argument("--differs")
    s.add_argument("--differs-pages", dest="differs_pages", default="1")
    s.add_argument("--meta", action="append")
    s.add_argument("--no-meta", dest="no_meta", action="append")
    s.set_defaults(func=cmd_check_pdf)

    s = sub.add_parser("check-zip")
    s.add_argument("name")
    s.add_argument("--entries", type=int)
    s.add_argument("--kind", choices=["pdf", "image"])
    s.add_argument("--pages")
    s.add_argument("--ext")
    s.add_argument("--contains")
    s.add_argument("--format")
    s.set_defaults(func=cmd_check_zip)

    s = sub.add_parser("check-image")
    s.add_argument("name")
    s.add_argument("--format")
    s.add_argument("--size")
    s.add_argument("--tolerance", type=int, default=2)
    s.set_defaults(func=cmd_check_image)

    s = sub.add_parser("json-get")
    s.add_argument("name")
    s.add_argument("path")
    s.set_defaults(func=cmd_json_get)
    return ap


def main():
    global WORKDIR
    args = build_parser().parse_args()
    WORKDIR = args.workdir
    os.makedirs(WORKDIR, exist_ok=True)
    try:
        code = args.func(args)
    except Exception as exc:  # never crash without a FAIL line
        code = fail([f"helper error: {type(exc).__name__}: {exc}"])
    sys.exit(code)


if __name__ == "__main__":
    main()
