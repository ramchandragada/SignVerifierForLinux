"""Batch / folder PDF signature verification for CA firms and ops desks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .authentic import is_cryptographically_verified
from .verifier import VerificationReport, verify_pdf


@dataclass
class BatchItemResult:
    path: str
    file_name: str
    overall: str
    overall_label: str
    cryptographically_verified: bool
    signature_count: int
    error: str = ""
    report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchVerificationReport:
    root: str
    total: int
    verified: int
    failed: int
    unsigned: int
    errors: int
    results: list[BatchItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "total": self.total,
            "verified": self.verified,
            "failed": self.failed,
            "unsigned": self.unsigned,
            "errors": self.errors,
            "results": [r.to_dict() for r in self.results],
        }


def iter_pdf_paths(target: str | Path, *, recursive: bool = True) -> list[Path]:
    """Collect PDF paths from a file or directory."""
    path = Path(target)
    if path.is_file():
        return [path] if path.suffix.lower() == ".pdf" else []
    if not path.is_dir():
        return []
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(p for p in path.glob(pattern) if p.is_file())


def verify_many(
    paths: Iterable[str | Path],
    *,
    trust_dir: str | Path | None = None,
    allow_fetching: bool = False,
) -> list[BatchItemResult]:
    items: list[BatchItemResult] = []
    for raw in paths:
        path = Path(raw)
        try:
            report: VerificationReport = verify_pdf(
                path, trust_dir=trust_dir, allow_fetching=allow_fetching
            )
            data = report.to_dict()
            data["cryptographically_verified"] = is_cryptographically_verified(report)
            items.append(
                BatchItemResult(
                    path=str(path.resolve()),
                    file_name=path.name,
                    overall=report.overall,
                    overall_label=report.overall_label,
                    cryptographically_verified=bool(data["cryptographically_verified"]),
                    signature_count=report.signature_count,
                    error=report.error or "",
                    report=data,
                )
            )
        except Exception as exc:
            items.append(
                BatchItemResult(
                    path=str(path.resolve()),
                    file_name=path.name,
                    overall="ERROR",
                    overall_label=str(exc),
                    cryptographically_verified=False,
                    signature_count=0,
                    error=str(exc),
                )
            )
    return items


def verify_folder(
    folder: str | Path,
    *,
    recursive: bool = True,
    trust_dir: str | Path | None = None,
    allow_fetching: bool = False,
) -> BatchVerificationReport:
    root = Path(folder)
    paths = iter_pdf_paths(root, recursive=recursive)
    results = verify_many(paths, trust_dir=trust_dir, allow_fetching=allow_fetching)
    verified = sum(1 for r in results if r.cryptographically_verified)
    unsigned = sum(1 for r in results if r.overall == "UNSIGNED")
    errors = sum(1 for r in results if r.overall == "ERROR")
    failed = len(results) - verified
    return BatchVerificationReport(
        root=str(root.resolve()),
        total=len(results),
        verified=verified,
        failed=failed,
        unsigned=unsigned,
        errors=errors,
        results=results,
    )
