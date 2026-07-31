"""Real verification helpers — never photoshop a green tick onto a signed PDF.

The only authentic digitally signed document is the original PDF with its
PKCS#7 / CMS signature bytes intact. Viewer green ticks (Adobe) are a
display of crypto validation, not something you draw into the file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from .verifier import VerificationReport, verify_pdf


def is_cryptographically_verified(report: VerificationReport) -> bool:
    """True when at least one embedded signature is intact and chain-trusted."""
    return any(sig.intact and sig.trusted for sig in report.signatures)


def build_verification_report_pdf(report: VerificationReport) -> bytes:
    """
    Create a separate verification report (not a modified NOC).

    This document attests that our tool checked the signature. It does NOT
    replace or alter the original signed PDF. Anyone can re-verify the
    original independently.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    def line(text: str, size: int = 11, bold: bool = False, gap: float = 6 * mm):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(20 * mm, y, text[:110])
        y -= gap

    verified = is_cryptographically_verified(report)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    line("PDF Digital Signature — Verification Report", size=16, bold=True, gap=10 * mm)
    line("This is NOT the signed document. It is an audit report only.", size=10, gap=8 * mm)
    line(f"Generated: {now}", size=10)
    line(f"Tool: PDF Sign Verifier", size=10, gap=8 * mm)

    line(f"Document: {report.file_name}", bold=True)
    line(f"Path checked: {report.path}", size=9, gap=4 * mm)
    line(f"Result: {report.overall} — {report.overall_label}", bold=True, gap=8 * mm)

    if verified:
        c.setFillColorRGB(0.06, 0.48, 0.27)
        line("CRYPTOGRAPHIC VERIFICATION: PASSED", bold=True, gap=5 * mm)
        c.setFillColorRGB(0, 0, 0)
        line("Signature bytes are intact and the certificate chains to a trusted CCA India root.", size=10, gap=8 * mm)
    else:
        c.setFillColorRGB(0.7, 0.1, 0.1)
        line("CRYPTOGRAPHIC VERIFICATION: FAILED / INCOMPLETE", bold=True, gap=5 * mm)
        c.setFillColorRGB(0, 0, 0)
        line("Do not treat this PDF as a verified digitally signed document.", size=10, gap=8 * mm)

    line(f"Trust roots loaded: {report.trust_roots_loaded}", size=10, gap=8 * mm)

    for sig in report.signatures:
        line(f"Signature field: {sig.field_name}", bold=True)
        line(f"  Signer: {sig.signer_name}")
        if sig.signer_email:
            line(f"  Email: {sig.signer_email}")
        line(f"  Issuer: {sig.issuer}")
        line(f"  Signing time: {sig.signing_time or 'n/a'}")
        line(f"  Trust anchor: {sig.trust_anchor or 'n/a'}")
        line(f"  Intact: {sig.intact}   Trusted: {sig.trusted}   Covers whole file: {sig.covers_whole_document}")
        line(f"  Hash: {sig.hash_algorithm or 'n/a'}   Status: {sig.overall}", gap=4 * mm)
        line(f"  {sig.summary}", size=9, gap=6 * mm)
        for w in sig.warnings:
            line(f"  Warning: {w}", size=9, gap=4 * mm)
        y -= 4 * mm

    if y < 40 * mm:
        c.showPage()
        y = height - 25 * mm

    line("Important", bold=True, gap=5 * mm)
    for note in [
        "1. Upload/share the ORIGINAL digitally signed PDF for others to verify.",
        "2. Drawing a green tick into a PDF is NOT digital signature verification.",
        "3. Adobe Print-to-PDF also removes the real signature and keeps only a picture.",
        "4. Recipients should verify the original with a trusted CCA India root store.",
    ]:
        line(note, size=9, gap=5 * mm)

    c.showPage()
    c.save()
    return buf.getvalue()


def export_original_if_verified(
    source_pdf: str | Path,
    output_pdf: str | Path,
    *,
    trust_dir: str | Path | None = None,
    report: VerificationReport | None = None,
) -> VerificationReport:
    """
    Copy the original PDF unchanged — only if crypto verification passed.

    Bytes are preserved so the PKCS#7 signature remains independently verifiable.
    """
    import shutil

    source = Path(source_pdf)
    output = Path(output_pdf)
    report = report or verify_pdf(source, trust_dir=trust_dir)

    if not is_cryptographically_verified(report):
        raise ValueError(
            "Refusing to mark as verified: signature is not intact and trusted. "
            f"Status: {report.overall} — {report.overall_label}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    return report
