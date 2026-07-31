#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF Sign Verifier")
    parser.add_argument("pdf", nargs="?", help="PDF to verify (CLI mode)")
    parser.add_argument("--cli", action="store_true", help="Force CLI output")
    parser.add_argument("--json", action="store_true", help="JSON output (CLI)")
    parser.add_argument("--gui", action="store_true", help="Start local web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--trust-dir", default=None)
    parser.add_argument("--list-roots", action="store_true")
    parser.add_argument("--allow-fetching", action="store_true")
    parser.add_argument("--copy-if-verified", metavar="OUT.pdf")
    parser.add_argument("--export-verified-noc", metavar="OUT.pdf")
    parser.add_argument("--report", metavar="REPORT.pdf")
    args, unknown = parser.parse_known_args(argv)

    if args.gui or (
        args.pdf is None
        and not args.list_roots
        and not args.cli
        and not args.copy_if_verified
        and not args.export_verified_noc
        and not args.report
    ):
        from pdf_sign_verifier.webapp import run

        run(host=args.host, port=args.port, open_browser=not args.no_browser)
        return 0

    from pdf_sign_verifier.cli import main as cli_main

    cli_argv: list[str] = []
    if args.list_roots:
        cli_argv.append("--list-roots")
    if args.json:
        cli_argv.append("--json")
    if args.allow_fetching:
        cli_argv.append("--allow-fetching")
    if args.trust_dir:
        cli_argv.extend(["--trust-dir", args.trust_dir])
    if args.export_verified_noc:
        cli_argv.extend(["--export-verified-noc", args.export_verified_noc])
    if args.report:
        cli_argv.extend(["--report", args.report])
    if args.pdf:
        cli_argv.append(args.pdf)
    cli_argv.extend(unknown)
    return cli_main(cli_argv)


if __name__ == "__main__":
    raise SystemExit(main())
