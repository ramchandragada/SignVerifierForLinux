from __future__ import annotations

from pathlib import Path

from asn1crypto import x509 as asn1_x509
from pyhanko.keys import load_certs_from_pemder

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRUST_DIR = PACKAGE_ROOT / "trust"


def load_trust_roots(trust_dir: Path | None = None) -> list[asn1_x509.Certificate]:
    """Load PEM/DER root certificates from the trust directory."""
    directory = Path(trust_dir) if trust_dir else DEFAULT_TRUST_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"Trust directory not found: {directory}")

    # Prefer normalized .pem files; fall back to other encodings.
    pem_paths = sorted(directory.glob("*.pem"))
    other_paths = sorted(
        {
            *directory.glob("*.cer"),
            *directory.glob("*.crt"),
            *directory.glob("*.der"),
        }
    )
    paths = pem_paths or other_paths
    if not paths:
        raise FileNotFoundError(f"No certificates found in {directory}")

    roots: list[asn1_x509.Certificate] = []
    seen: set[bytes] = set()
    for path in paths:
        try:
            for cert in load_certs_from_pemder([str(path)]):
                key = cert.dump()
                if key in seen:
                    continue
                seen.add(key)
                roots.append(cert)
        except Exception:
            # Skip unreadable files; other formats may still load.
            continue

    if not roots:
        raise FileNotFoundError(f"Could not parse any certificates in {directory}")
    return roots


def trust_root_names(trust_dir: Path | None = None) -> list[str]:
    names: list[str] = []
    for cert in load_trust_roots(trust_dir):
        names.append(cert.subject.human_friendly)
    return names
