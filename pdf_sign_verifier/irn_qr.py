"""Optional GST e-invoice IRN / Signed QR helpers (separate from PDF DSC verify).

This does NOT replace PKCS#7 Amazon NOC / DSC verification. GST e-invoice
authenticity is primarily carried by the IRP-signed QR / IRN, which is a
different trust path from Adobe-style PDF signatures.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

# Common IRN shape: 64 hex chars (SHA-256 hex of invoice payload).
IRN_RE = re.compile(r"\b([a-fA-F0-9]{64})\b")
# Loose JSON blob detection in QR payload text.
JSON_HINT_RE = re.compile(r"\{[^{}]{20,}\}")


@dataclass
class IrnQrResult:
    source: str
    found: bool
    irn: str = ""
    qr_payload: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)
    online_checked: bool = False
    online_ok: bool | None = None
    online_detail: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_irn_candidates(text: str) -> list[str]:
    return list(dict.fromkeys(IRN_RE.findall(text or "")))


def _try_parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"value": data}
    except Exception:
        pass
    for match in JSON_HINT_RE.finditer(text):
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def inspect_text_payload(text: str, *, source: str = "text") -> IrnQrResult:
    """Inspect free text / QR decode string for IRN-like content."""
    parsed = _try_parse_json(text)
    irn = ""
    if parsed:
        for key in ("Irn", "IRN", "irn", "IrnHash"):
            if parsed.get(key):
                irn = str(parsed[key]).strip()
                break
    candidates = extract_irn_candidates(text)
    if not irn and candidates:
        irn = candidates[0]
    notes: list[str] = []
    if irn:
        notes.append("IRN-like value detected in payload.")
    elif parsed:
        notes.append("JSON payload found, but no IRN field.")
    else:
        notes.append("No IRN / JSON QR payload detected.")
    notes.append(
        "PDF DSC verification is separate — use /api/verify for PKCS#7 signatures."
    )
    return IrnQrResult(
        source=source,
        found=bool(irn or parsed),
        irn=irn,
        qr_payload=text[:4000],
        parsed=parsed,
        notes=notes,
    )


def inspect_pdf_for_irn(path: str | Path) -> IrnQrResult:
    """Best-effort: scrape PDF text for IRN / embedded QR JSON strings."""
    path = Path(path)
    try:
        import fitz

        doc = fitz.open(path)
        try:
            chunks: list[str] = []
            for page in doc:
                chunks.append(page.get_text("text") or "")
            text = "\n".join(chunks)
        finally:
            doc.close()
    except Exception as exc:
        return IrnQrResult(
            source=str(path),
            found=False,
            notes=[f"Could not read PDF text: {exc}"],
        )
    result = inspect_text_payload(text, source=str(path))
    if not result.found:
        result.notes.insert(
            0,
            "No IRN string found in page text. Scanned QR images are not decoded yet.",
        )
    return result


def verify_irn_online(
    irn: str,
    *,
    endpoint: str | None = None,
    timeout: float = 8.0,
) -> IrnQrResult:
    """
    Optional online IRN lookup.

    Government / IRP verification endpoints change over time. By default this
    only validates IRN shape locally unless PDF_SIGN_VERIFIER_IRN_URL is set
    (or endpoint= is passed) to a JSON API that accepts ?irn=.
    """
    import os

    irn = (irn or "").strip()
    result = IrnQrResult(source="online", found=bool(IRN_RE.fullmatch(irn)), irn=irn)
    if not result.found:
        result.notes.append("IRN must be 64 hex characters.")
        return result

    url = endpoint or os.environ.get("PDF_SIGN_VERIFIER_IRN_URL")
    if not url:
        result.notes.append(
            "Local IRN format OK. Set PDF_SIGN_VERIFIER_IRN_URL to enable online IRP lookup."
        )
        return result

    req_url = f"{url}{('&' if '?' in url else '?')}irn={irn}"
    result.online_checked = True
    try:
        req = Request(req_url, headers={"User-Agent": "PDF-Sign-Verifier-IRN/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result.online_detail = body[:2000]
            try:
                result.parsed = json.loads(body)
            except Exception:
                result.parsed = {}
            result.online_ok = resp.status == 200
            result.notes.append("Online IRN endpoint responded.")
    except HTTPError as exc:
        result.online_ok = False
        result.online_detail = str(exc)
        result.notes.append(f"Online IRN check HTTP error: {exc.code}")
    except URLError as exc:
        result.online_ok = False
        result.online_detail = str(exc.reason)
        result.notes.append(f"Online IRN check failed: {exc.reason}")
    except Exception as exc:
        result.online_ok = False
        result.online_detail = str(exc)
        result.notes.append(f"Online IRN check failed: {exc}")
    return result
