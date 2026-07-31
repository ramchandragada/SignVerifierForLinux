from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.errors import (
    DisallowedAlgorithmError,
    SignatureValidationError,
)
from pyhanko.sign.validation.status import (
    PdfSignatureStatus,
    SignatureCoverageLevel,
)
from pyhanko_certvalidator import ValidationContext

from .trust_store import (
    DEFAULT_TRUST_DIR,
    load_intermediate_certs,
    load_trust_roots,
)

# pyHanko prints full tracebacks for expected incremental-update findings.
logging.getLogger("pyhanko.sign.diff_analysis").setLevel(logging.ERROR)
logging.getLogger("pyhanko.sign.validation").setLevel(logging.ERROR)


@dataclass
class SignatureResult:
    index: int
    field_name: str
    signer_name: str
    signer_email: str
    issuer: str
    signing_time: str
    hash_algorithm: str
    signature_type: str
    intact: bool
    trusted: bool
    covers_whole_document: bool
    summary: str
    details: str
    certificate_valid_from: str = ""
    certificate_valid_to: str = ""
    trust_anchor: str = ""
    coverage: str = ""
    modification_level: str = ""
    chain: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def overall(self) -> str:
        if not self.intact:
            return "INVALID"
        if not self.covers_whole_document:
            return "MODIFIED"
        if not self.trusted:
            return "UNTRUSTED"
        return "VALID"


@dataclass
class VerificationReport:
    path: str
    file_name: str
    has_signatures: bool
    signature_count: int
    overall: str
    overall_label: str
    signatures: list[SignatureResult] = field(default_factory=list)
    error: str = ""
    trust_roots_loaded: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signatures"] = [asdict(s) | {"overall": s.overall} for s in self.signatures]
        return data


def _format_time(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return str(value)


def _name_attr(name_obj, key: str) -> str:
    try:
        native = name_obj.native
        value = native.get(key)
        if value:
            return str(value)
    except Exception:
        pass
    return ""


def _signer_email(cert) -> str:
    try:
        email = cert.subject.native.get("email_address")
        if email:
            return str(email)
    except Exception:
        pass
    try:
        if cert.subject_alt_name_value is not None:
            for general_name in cert.subject_alt_name_value:
                native = general_name.native
                if isinstance(native, str) and "@" in native:
                    return native
                if isinstance(native, dict):
                    for value in native.values():
                        if isinstance(value, str) and "@" in value:
                            return value
    except Exception:
        pass
    return ""


def _covers_whole_document(status: PdfSignatureStatus) -> bool:
    coverage = getattr(status, "coverage", None)
    if coverage == SignatureCoverageLevel.ENTIRE_FILE:
        return True
    if coverage == SignatureCoverageLevel.ENTIRE_REVISION:
        # Signed revision is intact, but later incremental updates exist.
        return False
    # Fall back: if pyHanko reports no legitimate modification level and coverage unknown
    return False


def _summarize(
    *,
    intact: bool,
    trusted: bool,
    covers_whole: bool,
    hash_algorithm: str,
) -> tuple[str, list[str]]:
    warnings: list[str] = []

    if intact and trusted and covers_whole:
        summary = "Signature is valid and the certificate chains to a trusted CCA root."
    elif intact and trusted and not covers_whole:
        summary = "Signature is valid, but the document was changed after signing."
        warnings.append(
            "Content was added or changed after this signature. "
            "Review carefully — Adobe shows a similar modification warning."
        )
    elif intact and not trusted:
        summary = "Signature cryptography is valid, but the issuer is not trusted."
        warnings.append(
            "Add the issuing root certificate to the trust/ folder if this should be trusted."
        )
    else:
        summary = "Signature is invalid or the signed data does not match the file."
        warnings.append("Do not trust this document until the signature problem is resolved.")

    if hash_algorithm and hash_algorithm.lower() in {"sha1", "md5"}:
        warnings.append(
            f"Signed with {hash_algorithm.upper()} (common on older Indian DSCs). "
            "Cryptographic check still ran; prefer SHA-256 for new signatures."
        )
    return summary, warnings


def _overall_for_report(signatures: list[SignatureResult], has_signatures: bool) -> tuple[str, str]:
    if not has_signatures:
        return "UNSIGNED", "No digital signatures found"
    ranks = {"INVALID": 0, "MODIFIED": 1, "UNTRUSTED": 2, "VALID": 3}
    labels = {
        "INVALID": "Invalid signature",
        "MODIFIED": "Signed, but modified after signing",
        "UNTRUSTED": "Signature OK — certificate not trusted",
        "VALID": "Valid signature",
    }
    worst = min(signatures, key=lambda s: ranks.get(s.overall, 0))
    return worst.overall, labels[worst.overall]


def verify_pdf(
    path: str | Path,
    trust_dir: str | Path | None = None,
    *,
    allow_fetching: bool = False,
) -> VerificationReport:
    pdf_path = Path(path).expanduser().resolve()
    trust_path = Path(trust_dir) if trust_dir else DEFAULT_TRUST_DIR

    if not pdf_path.is_file():
        return VerificationReport(
            path=str(pdf_path),
            file_name=pdf_path.name,
            has_signatures=False,
            signature_count=0,
            overall="ERROR",
            overall_label="File not found",
            error=f"File not found: {pdf_path}",
        )

    try:
        roots = load_trust_roots(trust_path)
        intermediates = load_intermediate_certs(trust_path)
    except Exception as exc:
        return VerificationReport(
            path=str(pdf_path),
            file_name=pdf_path.name,
            has_signatures=False,
            signature_count=0,
            overall="ERROR",
            overall_label="Trust store error",
            error=str(exc),
        )

    results: list[SignatureResult] = []
    try:
        with pdf_path.open("rb") as handle:
            reader = PdfFileReader(handle, strict=False)
            embedded = list(reader.embedded_signatures)
            if not embedded:
                overall, label = _overall_for_report([], False)
                return VerificationReport(
                    path=str(pdf_path),
                    file_name=pdf_path.name,
                    has_signatures=False,
                    signature_count=0,
                    overall=overall,
                    overall_label=label,
                    trust_roots_loaded=len(roots),
                )

            for index, sig in enumerate(embedded):
                field_name = str(getattr(sig, "field_name", None) or f"Signature{index + 1}")
                signer_name = "Unknown signer"
                signer_email = ""
                issuer = ""
                cert_from = ""
                cert_to = ""
                trust_anchor = ""
                chain: list[str] = []
                signing_time = _format_time(getattr(sig, "self_reported_timestamp", None))
                hash_algorithm = str(getattr(sig, "md_algorithm", "") or "")
                signature_type = ""
                covers_whole = False
                intact = False
                trusted = False
                details = ""
                summary = ""
                warnings: list[str] = []
                coverage = ""
                modification_level = ""

                try:
                    signature_type = str(sig.sig_object.get("/SubFilter") or "")
                except Exception:
                    signature_type = ""

                try:
                    cert = sig.signer_cert
                    if cert is not None:
                        signer_name = (
                            _name_attr(cert.subject, "common_name")
                            or cert.subject.human_friendly
                        )
                        signer_email = _signer_email(cert)
                        issuer = (
                            _name_attr(cert.issuer, "common_name")
                            or cert.issuer.human_friendly
                        )
                        cert_from = _format_time(cert.not_valid_before)
                        cert_to = _format_time(cert.not_valid_after)
                        chain = [cert.subject.human_friendly]
                except Exception:
                    pass

                # Validate certificate validity at signing time (Adobe-style), not "now".
                # Many Indian DSCs expire; signatures made while the cert was valid stay trusted.
                moment = getattr(sig, "self_reported_timestamp", None)
                if isinstance(moment, datetime) and moment.tzinfo is None:
                    from datetime import timezone

                    moment = moment.replace(tzinfo=timezone.utc)

                # Empty weak_hash_algos: allow SHA-1 used by many Indian Class 2/3 DSCs.
                vc = ValidationContext(
                    trust_roots=roots,
                    other_certs=intermediates,
                    moment=moment,
                    allow_fetching=allow_fetching,
                    revocation_mode="soft-fail",
                    weak_hash_algos=set(),
                )

                try:
                    # Keep diff analysis so modification-after-sign is detected.
                    status = validate_pdf_signature(sig, vc, skip_diff=False)
                    intact = bool(status.intact and status.valid)
                    trusted = bool(status.trusted)
                    covers_whole = _covers_whole_document(status)
                    coverage = str(getattr(status, "coverage", "") or "")
                    modification_level = str(getattr(status, "modification_level", "") or "")
                    trust_anchor = str(getattr(status, "_trust_anchor", "") or "")
                    try:
                        details = status.pretty_print_details()
                    except Exception:
                        details = str(status)
                    summary, warnings = _summarize(
                        intact=intact,
                        trusted=trusted,
                        covers_whole=covers_whole,
                        hash_algorithm=hash_algorithm,
                    )
                    # If crypto is OK but diff policy is noisy, still surface coverage.
                    if intact and not covers_whole:
                        summary, warnings = _summarize(
                            intact=True,
                            trusted=trusted,
                            covers_whole=False,
                            hash_algorithm=hash_algorithm,
                        )
                except DisallowedAlgorithmError as exc:
                    intact = False
                    trusted = False
                    summary = "Signature uses a disallowed algorithm."
                    details = str(exc)
                    warnings.append(str(exc))
                except SignatureValidationError as exc:
                    intact = False
                    trusted = False
                    summary = "Signature validation failed."
                    details = str(exc)
                    warnings.append(str(exc))
                except Exception as exc:
                    intact = False
                    trusted = False
                    summary = "Unexpected validation error."
                    details = str(exc)
                    warnings.append(str(exc))

                results.append(
                    SignatureResult(
                        index=index,
                        field_name=field_name,
                        signer_name=signer_name,
                        signer_email=signer_email,
                        issuer=issuer,
                        signing_time=signing_time,
                        hash_algorithm=hash_algorithm,
                        signature_type=signature_type,
                        intact=intact,
                        trusted=trusted,
                        covers_whole_document=covers_whole,
                        summary=summary,
                        details=details,
                        certificate_valid_from=cert_from,
                        certificate_valid_to=cert_to,
                        trust_anchor=trust_anchor,
                        coverage=coverage,
                        modification_level=modification_level,
                        chain=chain,
                        warnings=warnings,
                    )
                )
    except Exception as exc:
        return VerificationReport(
            path=str(pdf_path),
            file_name=pdf_path.name,
            has_signatures=False,
            signature_count=0,
            overall="ERROR",
            overall_label="Could not read PDF",
            error=str(exc),
            trust_roots_loaded=len(roots),
        )

    overall, label = _overall_for_report(results, True)
    return VerificationReport(
        path=str(pdf_path),
        file_name=pdf_path.name,
        has_signatures=True,
        signature_count=len(results),
        overall=overall,
        overall_label=label,
        signatures=results,
        trust_roots_loaded=len(roots),
    )
