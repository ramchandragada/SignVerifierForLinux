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
from .trust_store import DEFAULT_TRUST_DIR, trust_root_names
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
            "Cryptographically verify PDF digital signatures using India's CCA trust roots. "
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
        help="List loaded trust roots and exit",
    )
    parser.add_argument(
        "--allow-fetching",
        action="store_true",
        help="Allow online CRL/OCSP/AIA fetching during validation",
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
            for name in trust_root_names(Path(args.trust_dir)):
                print(name)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0

    if not args.pdf:
        parser.print_help()
        return 2

    report = verify_pdf(args.pdf, trust_dir=args.trust_dir, allow_fetching=args.allow_fetching)
    if args.json:
        data = report.to_dict()
        data["cryptographically_verified"] = is_cryptographically_verified(report)
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
