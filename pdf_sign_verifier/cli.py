from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .authentic import (
    build_verification_report_pdf,
    is_cryptographically_verified,
)
from .batch import verify_folder, verify_many
from .irn_qr import inspect_pdf_for_irn, inspect_text_payload, verify_irn_online
from .trust_store import (
    DEFAULT_TRUST_DIR,
    load_intermediate_certs,
    trust_root_names,
)
from .verified_appearance import export_verified_appearance_pdf
from .verifier import verify_pdf


def _print_human(report) -> None:
    print(f"File: {report.file_name}")
    print(f"Path: {report.path}")
    if report.error:
        print(f"Error: {report.error}")
        return

    print(f"Result: {report.overall} — {report.overall_label}")
    print(f"Signatures: {report.signature_count}")
    print(f"Trust roots loaded: {report.trust_roots_loaded}")
    print(
        "Cryptographic verification:",
        "PASSED" if is_cryptographically_verified(report) else "FAILED",
    )
    print()

    for sig in report.signatures:
        print(f"── Signature #{sig.index + 1}: {sig.field_name}")
        print(f"   Status:           {sig.overall}")
        print(f"   Signer:           {sig.signer_name}")
        if sig.signer_email:
            print(f"   Email:            {sig.signer_email}")
        print(f"   Issuer:           {sig.issuer}")
        print(f"   Signing time:     {sig.signing_time or 'n/a'}")
        print(f"   Hash:             {sig.hash_algorithm or 'n/a'}")
        print(f"   Intact:           {sig.intact}")
        print(f"   Trusted:          {sig.trusted}")
        print(f"   Covers whole doc: {sig.covers_whole_document}")
        print(f"   Summary:          {sig.summary}")
        for warning in sig.warnings:
            print(f"   Warning:          {warning}")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-sign-verifier",
        description=(
            "Verify Indian DSC / CCA-chained PDF digital signatures on Linux. "
            "Amazon blank-NOC fill remains available in the web UI. "
            "Does not photoshop green ticks onto documents."
        ),
    )
    parser.add_argument("pdf", nargs="?", help="PDF file to verify")
    parser.add_argument(
        "--trust-dir",
        default=str(DEFAULT_TRUST_DIR),
        help="Directory with trusted root certificates (default: ./trust)",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--list-roots",
        action="store_true",
        help="List loaded trust roots / intermediates and exit",
    )
    parser.add_argument(
        "--allow-fetching",
        action="store_true",
        help="Allow online CRL/OCSP/AIA fetching during validation",
    )
    parser.add_argument(
        "--batch",
        metavar="DIR",
        help="Verify all PDFs in a folder (for CA firms / bulk desks)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="With --batch, do not recurse into subfolders",
    )
    parser.add_argument(
        "--irn",
        metavar="IRN_OR_PDF",
        help="Optional GST IRN helper: 64-hex IRN, QR text, or PDF path to scan",
    )
    parser.add_argument(
        "--export-verified-noc",
        metavar="OUT.pdf",
        help="After crypto PASS, save NOC with Adobe-style green Signature valid appearance",
    )
    parser.add_argument(
        "--report",
        metavar="REPORT.pdf",
        help="Write a separate verification audit report",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_roots:
        try:
            print("Trust anchors (CCA India):")
            for name in trust_root_names(Path(args.trust_dir)):
                print(f"  {name}")
            print("Bundled intermediates (licensed CAs):")
            for cert in load_intermediate_certs(Path(args.trust_dir)):
                native = cert.subject.native
                cn = native.get("common_name") or str(native)
                print(f"  {cn}")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.irn:
        target = args.irn.strip()
        path = Path(target)
        if path.is_file() and path.suffix.lower() == ".pdf":
            result = inspect_pdf_for_irn(path)
        elif len(target) == 64 and all(c in "0123456789abcdefABCDEF" for c in target):
            result = verify_irn_online(target)
        else:
            result = inspect_text_payload(target, source="cli")
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.found else 1

    if args.batch:
        batch = verify_folder(
            args.batch,
            recursive=not args.no_recursive,
            trust_dir=args.trust_dir,
            allow_fetching=args.allow_fetching,
        )
        if args.json:
            print(json.dumps(batch.to_dict(), indent=2))
        else:
            print(
                f"Batch: {batch.total} PDFs · verified {batch.verified} · "
                f"failed {batch.failed} · unsigned {batch.unsigned} · errors {batch.errors}"
            )
            for item in batch.results:
                mark = "PASS" if item.cryptographically_verified else item.overall
                print(f"  [{mark}] {item.file_name} — {item.overall_label}")
        return 0 if batch.failed == 0 and batch.total > 0 else 1

    if not args.pdf:
        parser.print_help()
        return 2

    # Multi-file CLI: space-separated extras via nargs would need change;
    # support verifying a list if path is missing but unknown leftovers exist — skip.
    report = verify_pdf(args.pdf, trust_dir=args.trust_dir, allow_fetching=args.allow_fetching)
    if args.json:
        data = report.to_dict()
        data["cryptographically_verified"] = is_cryptographically_verified(report)
        data["api_version"] = 1
        data["tool"] = f"pdf-sign-verifier/{__version__}"
        print(json.dumps(data, indent=2))
    else:
        _print_human(report)

    if args.export_verified_noc:
        try:
            export_verified_appearance_pdf(
                args.pdf,
                args.export_verified_noc,
                trust_dir=args.trust_dir,
                report=report,
            )
            print(f"Verified NOC saved: {args.export_verified_noc}")
        except Exception as exc:
            print(f"Export failed: {exc}", file=sys.stderr)
            return 2

    if args.report:
        try:
            Path(args.report).write_bytes(build_verification_report_pdf(report))
            print(f"Verification report written: {args.report}")
        except Exception as exc:
            print(f"Report failed: {exc}", file=sys.stderr)
            return 2

    if report.overall in {"VALID"}:
        return 0
    if report.overall in {"MODIFIED", "UNTRUSTED", "UNSIGNED"}:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
