from __future__ import annotations

import sys
from pathlib import Path

from asn1crypto import x509 as asn1_x509
from pyhanko.keys import load_certs_from_pemder


def _package_root() -> Path:
    # PyInstaller onedir/onefile extracts data under sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


PACKAGE_ROOT = _package_root()
DEFAULT_TRUST_DIR = PACKAGE_ROOT / "trust"


def _cert_paths(directory: Path) -> list[Path]:
    pem_paths = sorted(directory.glob("*.pem"))
    other_paths = sorted(
        {
            *directory.glob("*.cer"),
            *directory.glob("*.crt"),
            *directory.glob("*.der"),
        }
    )
    # Prefer PEM; skip raw .cer when a matching .pem exists (same stem).
    if pem_paths:
        pem_stems = {p.stem for p in pem_paths}
        other_paths = [p for p in other_paths if p.stem not in pem_stems]
        return [*pem_paths, *other_paths]
    return other_paths


def _load_all_certs(trust_dir: Path | None = None) -> list[asn1_x509.Certificate]:
    directory = Path(trust_dir) if trust_dir else DEFAULT_TRUST_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"Trust directory not found: {directory}")

    paths = _cert_paths(directory)
    if not paths:
        raise FileNotFoundError(f"No certificates found in {directory}")

    certs: list[asn1_x509.Certificate] = []
    seen: set[bytes] = set()
    for path in paths:
        try:
            for cert in load_certs_from_pemder([str(path)]):
                key = cert.dump()
                if key in seen:
                    continue
                seen.add(key)
                certs.append(cert)
        except Exception:
            continue

    if not certs:
        raise FileNotFoundError(f"Could not parse any certificates in {directory}")
    return certs


def _is_trust_anchor(cert: asn1_x509.Certificate) -> bool:
    """CCA India roots are self-signed; licensed CA intermediates are not."""
    return cert.self_signed in {"yes", "maybe"}


def load_trust_roots(trust_dir: Path | None = None) -> list[asn1_x509.Certificate]:
    """Load trust-anchor certificates (typically CCA India roots)."""
    roots = [c for c in _load_all_certs(trust_dir) if _is_trust_anchor(c)]
    if not roots:
        raise FileNotFoundError("No trust-anchor certificates found (expected CCA India roots)")
    return roots


def load_intermediate_certs(trust_dir: Path | None = None) -> list[asn1_x509.Certificate]:
    """Load bundled CA intermediates (SafeScrypt, Verasys, …) for chain building."""
    return [c for c in _load_all_certs(trust_dir) if not _is_trust_anchor(c)]


def trust_root_names(trust_dir: Path | None = None) -> list[str]:
    return [cert.subject.human_friendly for cert in load_trust_roots(trust_dir)]
