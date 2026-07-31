"""Export Acrobat-accurate verified appearance — matched to user reference stamp."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .verifier import SignatureResult, VerificationReport, verify_pdf

IST = timezone(timedelta(hours=5, minutes=30))
# Exact green from reference pixels: (0, 178, 59)
ADOBE_GREEN = (0, 178, 59, 255)


def is_cryptographically_verified(report: VerificationReport) -> bool:
    return any(sig.intact and sig.trusted for sig in report.signatures)


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    # Prefer Nimbus Sans (Helvetica metric-compatible — closest to Acrobat)
    bundled = []
    try:
        from .trust_store import PACKAGE_ROOT

        fonts = PACKAGE_ROOT / "fonts"
        if bold:
            bundled = [fonts / "NimbusSans-Bold.otf", fonts / "LiberationSans-Bold.ttf"]
        else:
            bundled = [fonts / "NimbusSans-Regular.otf", fonts / "LiberationSans-Regular.ttf"]
    except Exception:
        pass

    if bold:
        paths = [
            *bundled,
            "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        paths = [
            *bundled,
            "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in paths:
        path = Path(path)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _format_adobe_date(signing_time: str) -> str:
    raw = (signing_time or "").strip()
    if not raw:
        return datetime.now(IST).strftime("%Y.%m.%d %H:%M:%S IST")
    try:
        if "UTC" in raw:
            dt = datetime.strptime(raw.replace(" UTC", "").strip(), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        elif "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y.%m.%d %H:%M:%S IST")


def _line_intersect(
    p: tuple[float, float],
    r: tuple[float, float],
    q: tuple[float, float],
    s: tuple[float, float],
) -> tuple[float, float]:
    """Intersection of line p+r*t and q+s*u."""
    rx, ry = r
    sx, sy = s
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-9:
        return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    qx, qy = q[0] - p[0], q[1] - p[1]
    t = (qx * sy - qy * sx) / denom
    return (p[0] + t * rx, p[1] + t * ry)


def _check_polygon(cx: float, cy: float, scale: float) -> list[tuple[float, float]]:
    """
    Square-ended Acrobat check fitted to reference green silhouette.
    Tips/vertex measured from reference mask (vertex-centered, +y down).
    """
    # Measured from reference green mask skeleton
    p0 = (cx + scale * (-0.30), cy + scale * (-0.47))  # short tip
    p1 = (cx, cy)  # outer vertex
    p2 = (cx + scale * 0.50, cy + scale * (-0.98))  # long tip (top)
    # Match required Adobe reference — deliberately slim arms
    half = scale * 0.025

    def dir_vec(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        return (dx / length, dy / length)

    def normal(d):
        return (-d[1] * half, d[0] * half)

    d1 = dir_vec(p0, p1)
    d2 = dir_vec(p1, p2)
    n1 = normal(d1)
    n2 = normal(d2)

    # Square tip ends (perpendicular to arm)
    a_o = (p0[0] + n1[0], p0[1] + n1[1])
    a_i = (p0[0] - n1[0], p0[1] - n1[1])
    c_o = (p2[0] + n2[0], p2[1] + n2[1])
    c_i = (p2[0] - n2[0], p2[1] - n2[1])

    # Miter joins at vertex (outer = bottom point, inner = crook)
    outer = _line_intersect(a_o, d1, c_o, (-d2[0], -d2[1]))
    inner = _line_intersect(a_i, d1, c_i, (-d2[0], -d2[1]))

    return [a_o, outer, c_o, c_i, inner, a_i]


def _draw_hard_3d_check(img: Image.Image, cx: float, cy: float, scale: float) -> None:
    """Opaque green check + hard black bottom-right extrusion (no full outline)."""
    poly = _check_polygon(cx, cy, scale)
    # Very slim bottom-right ledge only
    extrude = [(x + scale * 0.014, y + scale * 0.014) for x, y in poly]

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon(extrude, fill=(0, 0, 0, 255))
    d.polygon(poly, fill=ADOBE_GREEN)
    img.alpha_composite(layer)


def build_adobe_valid_stamp(signer_name: str, signing_time: str) -> bytes:
    """
    Match user reference crop (measured from image-c9f7c260…):
      title @ y0; Digitally @ +42; name @ +62; Date @ +82; Contact @ +105
      green check ~98×97 at (+94, +9) from title; vertex near Contact
      text drawn ON TOP of check (Acrobat readability)
    """
    # Render at 4× then downscale for clean edges
    scale = 4
    # Reference content crop ~296×119 — keep same aspect
    W, H = 300 * scale, 122 * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Size fonts so title fills ~same visual weight as reference (Acrobat-like)
    font_title = _load_font(23 * scale, bold=False)
    font_body = _load_font(14 * scale, bold=False)

    tx = 2 * scale
    title_y = 1 * scale

    parts = (signer_name or "Unknown").strip().split()
    if len(parts) >= 2:
        lines = [
            (36, f"Digitally signed by {parts[0]}"),
            (52, " ".join(parts[1:])),
            (68, f"Date: {_format_adobe_date(signing_time)}"),
            (86, "Contact:"),
        ]
    else:
        lines = [
            (36, f"Digitally signed by {parts[0] if parts else 'Unknown'}"),
            (56, f"Date: {_format_adobe_date(signing_time)}"),
            (76, "Contact:"),
        ]

    # Check spans title→Contact; vertex near Date/Contact; left of mid-block
    check_scale = 96 * scale
    cx = tx + 112 * scale
    cy = title_y + 90 * scale
    _draw_hard_3d_check(img, cx, cy, check_scale)

    draw = ImageDraw.Draw(img)
    draw.text((tx, title_y), "Signature valid", fill=(0, 0, 0, 255), font=font_title)
    for rel_y, line in lines:
        draw.text((tx, title_y + rel_y * scale), line, fill=(0, 0, 0, 255), font=font_body)

    final = img.resize((300, 122), Image.Resampling.LANCZOS)
    buf = BytesIO()
    final.save(buf, format="PNG")
    return buf.getvalue()


def _pick_sig(report: VerificationReport) -> SignatureResult:
    trusted = [s for s in report.signatures if s.intact and s.trusted]
    if not trusted:
        raise ValueError("Signature is not cryptographically verified (intact + trusted)")
    trusted.sort(key=lambda s: (not s.covers_whole_document, s.index))
    return trusted[0]


def _find_authorised_signatory(page):
    """Amazon NOCs use both US and UK spellings."""
    for needle in ("Authorised Signatory", "Authorized Signatory"):
        hits = page.search_for(needle)
        if hits:
            return hits[0]
    return None


def _anchor_rect(page):
    import fitz

    widget_rect = None
    try:
        for widget in list(page.widgets() or []):
            ft = (getattr(widget, "field_type_string", "") or "").lower()
            fn = (getattr(widget, "field_name", "") or "").lower()
            if "sig" in ft or "sign" in fn:
                widget_rect = widget.rect
                break
    except Exception:
        pass

    boxes = []
    for needle in ("Signature Not Verified", "Digitally signed", "Signature valid"):
        boxes.extend(page.search_for(needle))
    if widget_rect is not None:
        boxes.append(widget_rect)

    auth = _find_authorised_signatory(page)
    for_amazon = page.search_for("For Amazon Seller Services")

    if not boxes:
        if for_amazon:
            r = for_amazon[0]
            top = r.y1 + 1
            bot = (auth.y0 - 6) if auth else r.y1 + 80
            return fitz.Rect(r.x0, top, r.x0 + 190, bot)
        pr = page.rect
        return fitz.Rect(pr.x0 + 72, pr.y1 - 270, pr.x0 + 260, pr.y1 - 200)

    x0 = min(b.x0 for b in boxes) - 1
    y0 = min(b.y0 for b in boxes) - 1
    x1 = max(max(b.x1 for b in boxes) + 10, x0 + 190)
    y1 = max(b.y1 for b in boxes) + 2

    # Never cover company line or Authorised Signatory
    if for_amazon and y0 < for_amazon[0].y1 + 1:
        y0 = for_amazon[0].y1 + 1
    if auth:
        y1 = min(y1, auth.y0 - 6)

    # Prefer a readable stamp height, but never expand into Authorised Signatory
    if y1 - y0 < 70 and auth is None:
        y0 = max((for_amazon[0].y1 + 1) if for_amazon else (y0 - 20), y1 - 78)
    if y1 <= y0 + 48:
        # Extremely tight band — keep whatever gap exists above Authorised Signatory
        if auth:
            y1 = max(y0 + 48, min(y1, auth.y0 - 6))
        else:
            y1 = y0 + 70

    return fitz.Rect(x0, y0, x1, y1)


def export_verified_appearance_pdf(
    source_pdf: str | Path,
    output_pdf: str | Path,
    *,
    trust_dir: str | Path | None = None,
    report: VerificationReport | None = None,
) -> VerificationReport:
    import fitz

    source = Path(source_pdf)
    output = Path(output_pdf)
    report = report or verify_pdf(source, trust_dir=trust_dir)

    if not is_cryptographically_verified(report):
        raise ValueError(
            "Cannot create verified appearance: cryptographic verification did not pass. "
            f"Status: {report.overall} — {report.overall_label}"
        )

    sig = _pick_sig(report)
    stamp_png = build_adobe_valid_stamp(sig.signer_name, sig.signing_time)

    doc = fitz.open(source)
    try:
        page_index = 0
        for i, page in enumerate(doc):
            try:
                for widget in list(page.widgets() or []):
                    ft = (getattr(widget, "field_type_string", "") or "").lower()
                    fn = (getattr(widget, "field_name", "") or "").lower()
                    if "sig" in ft or "sign" in fn:
                        page_index = i
                        break
            except Exception:
                pass

        page = doc[page_index]
        # Capture Authorised Signatory before deleting the widget (layout stays).
        auth = _find_authorised_signatory(page)
        for_amazon = page.search_for("For Amazon Seller Services")
        try:
            for widget in list(page.widgets() or []):
                ft = (getattr(widget, "field_type_string", "") or "").lower()
                fn = (getattr(widget, "field_name", "") or "").lower()
                if "sig" in ft or "sign" in fn:
                    page.delete_widget(widget)
        except Exception:
            pass

        cover = _anchor_rect(page)
        pr = page.rect
        if auth:
            cover.y1 = min(cover.y1, auth.y0 - 6)
        if for_amazon:
            cover.y0 = max(cover.y0, for_amazon[0].y1 + 1)
        cover.x1 = min(max(cover.x1, cover.x0 + 190), pr.x1 - 14)
        # Grow upward only if it will not cover the company line
        if cover.height < 70:
            min_y0 = (for_amazon[0].y1 + 1) if for_amazon else (pr.y0 + 40)
            cover.y0 = max(min_y0, cover.y1 - 78)

        page.draw_rect(cover, color=(1, 1, 1), fill=(1, 1, 1), width=0, overlay=True)

        # Stamp aspect 300:122 — fit inside cover; never overlap Authorised Signatory
        aspect = 300 / 122
        max_bottom = (auth.y0 - 6) if auth else (cover.y1)
        stamp_h = min(88.0, cover.height - 1, max_bottom - cover.y0)
        stamp_h = max(48.0, stamp_h)
        stamp_w = stamp_h * aspect
        if stamp_w > cover.width:
            stamp_w = cover.width
            stamp_h = stamp_w / aspect
        if cover.y0 + stamp_h > max_bottom:
            stamp_h = max(48.0, max_bottom - cover.y0)
            stamp_w = stamp_h * aspect

        stamp_rect = fitz.Rect(cover.x0, cover.y0, cover.x0 + stamp_w, cover.y0 + stamp_h)
        page.insert_image(stamp_rect, stream=stamp_png, keep_proportion=False, overlay=True)

        # Mark as visual NOC so re-checking this file is not confused with the original PKCS#7
        doc.set_metadata(
            {
                **doc.metadata,
                "keywords": "PDF-Sign-Verifier-NOC",
                "subject": "Verified appearance (visual NOC) — original PKCS#7 is on the source PDF",
            }
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        doc.save(output, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    return report
