#!/usr/bin/env bash
# Build an installable .deb for PDF Sign Verifier (company distribution).
#
# Usage:
#   ./packaging/build-deb.sh              # local build (this machine's Python)
#   ./packaging/build-deb.sh --docker     # Ubuntu 24.04 amd64 (recommended for sharing)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_NAME="pdf-sign-verifier"
VERSION="${VERSION:-1.0.0}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
DIST_DIR="${ROOT}/dist"
STAGE="${DIST_DIR}/stage"
OUT_DEB="${DIST_DIR}/${PKG_NAME}_${VERSION}_${ARCH}${DEB_SUFFIX:+_${DEB_SUFFIX}}.deb"

USE_DOCKER=0
if [[ "${1:-}" == "--docker" ]]; then
  USE_DOCKER=1
fi

if [[ "${USE_DOCKER}" -eq 1 ]]; then
  echo "==> Building inside Ubuntu 24.04 Docker (portable for company PCs)..."
  mkdir -p "${DIST_DIR}"
  docker run --rm \
    -v "${ROOT}:/src:ro" \
    -v "${DIST_DIR}:/out" \
    -e VERSION="${VERSION}" \
    ubuntu:24.04 \
    bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq python3 python3-venv python3-pip dpkg-dev binutils \
        fonts-liberation fonts-urw-base35 >/dev/null
      cp -a /src /build
      cd /build
      # Writable copy for build artifacts
      rm -rf /build/dist/stage /build/dist/*.deb
      mkdir -p /build/dist
      bash /build/packaging/build-deb.sh --inside-docker
      cp -a /build/dist/*.deb /out/
      echo "Copied deb to host dist/"
    '
  ls -lh "${DIST_DIR}"/*.deb
  echo "Done: $(ls -1 "${DIST_DIR}"/${PKG_NAME}_*_*.deb | tail -1)"
  exit 0
fi

echo "==> Staging ${PKG_NAME} ${VERSION} (${ARCH})"
rm -rf "${STAGE}"
mkdir -p \
  "${STAGE}/DEBIAN" \
  "${STAGE}/opt/${PKG_NAME}/app" \
  "${STAGE}/usr/bin" \
  "${STAGE}/usr/share/applications" \
  "${STAGE}/usr/share/doc/${PKG_NAME}"

# Application payload
install -m 0755 "${ROOT}/main.py" "${STAGE}/opt/${PKG_NAME}/app/main.py"
install -m 0644 "${ROOT}/requirements.txt" "${STAGE}/opt/${PKG_NAME}/app/requirements.txt"
cp -a "${ROOT}/pdf_sign_verifier" "${STAGE}/opt/${PKG_NAME}/app/"
cp -a "${ROOT}/trust" "${STAGE}/opt/${PKG_NAME}/app/"
find "${STAGE}/opt/${PKG_NAME}/app" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "${STAGE}/opt/${PKG_NAME}/app" -type f -name '*.pyc' -delete 2>/dev/null || true

# Vendor Python dependencies into a venv at the final install path prefix
VENV="${STAGE}/opt/${PKG_NAME}/venv"
echo "==> Creating venv and installing dependencies (no network needed after this build)..."
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --upgrade pip wheel -q
"${VENV}/bin/pip" install -r "${ROOT}/requirements.txt" -q

# Make venv relocatable to /opt/pdf-sign-verifier
OLD_PREFIX="${STAGE}/opt/${PKG_NAME}"
NEW_PREFIX="/opt/${PKG_NAME}"
if [[ -f "${VENV}/pyvenv.cfg" ]]; then
  sed -i "s|${OLD_PREFIX}|${NEW_PREFIX}|g" "${VENV}/pyvenv.cfg"
fi
# Rewrite shebangs in venv/bin
while IFS= read -r -d '' f; do
  if head -1 "$f" | grep -q "^#!${OLD_PREFIX}"; then
    sed -i "1s|^#!${OLD_PREFIX}|#!${NEW_PREFIX}|" "$f"
  fi
done < <(find "${VENV}/bin" -type f -print0)

# Launcher
cat > "${STAGE}/usr/bin/pdf-sign-verifier" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="/opt/pdf-sign-verifier"
export PDF_SIGN_VERIFIER_HOME="${ROOT}/app"
exec "${ROOT}/venv/bin/python" "${ROOT}/app/main.py" "$@"
EOF
chmod 0755 "${STAGE}/usr/bin/pdf-sign-verifier"

# Desktop entry
cat > "${STAGE}/usr/share/applications/pdf-sign-verifier.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PDF Sign Verifier
Comment=Verify Indian DSC / Amazon NOC PDF signatures on Linux Mint / Ubuntu
Exec=pdf-sign-verifier --gui
Icon=application-pdf
Terminal=false
Categories=Office;Utility;XFCE;
Keywords=PDF;Signature;DSC;NOC;Verify;Mint;
StartupNotify=true
EOF

# Docs
install -m 0644 "${ROOT}/README.md" "${STAGE}/usr/share/doc/${PKG_NAME}/README.md"
cat > "${STAGE}/usr/share/doc/${PKG_NAME}/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: PDF Sign Verifier
Files: *
Copyright: PDF Sign Verifier contributors
License: Proprietary
 Internal company distribution.
EOF

# Debian control
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_NEXT="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor + 1}")')"
INSTALLED_SIZE="$(du -sk "${STAGE}/opt" "${STAGE}/usr" | awk '{s+=$1} END {print s}')"

cat > "${STAGE}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= ${PY_VER}), python3 (<< ${PY_NEXT}), fonts-liberation | fonts-dejavu-core
Maintainer: Ramchandra Gada <ramchandragada@users.noreply.github.com>
Description: Verify PDF digital signatures (Indian DSC / Amazon NOC)
 Lightweight Linux tool to cryptographically verify PDF signatures
 using CCA India trust roots, with a local web UI and verified-NOC export.
 .
 Built for Python ${PY_VER} on ${ARCH}. Install on matching Ubuntu/Debian systems.
Installed-Size: ${INSTALLED_SIZE}
Homepage: https://github.com/ramchandragada/SignVerifierForLinux
EOF

cat > "${STAGE}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
echo "PDF Sign Verifier installed. Run: pdf-sign-verifier"
echo "Or open 'PDF Sign Verifier' from the app menu."
EOF
chmod 0755 "${STAGE}/DEBIAN/postinst"

cat > "${STAGE}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
EOF
chmod 0755 "${STAGE}/DEBIAN/postrm"

echo "==> Building .deb..."
mkdir -p "${DIST_DIR}"
dpkg-deb --root-owner-group --build "${STAGE}" "${OUT_DEB}"
echo
ls -lh "${OUT_DEB}"
echo
echo "Install with:"
echo "  sudo apt install ./${OUT_DEB#$ROOT/}"
echo "  # or: sudo dpkg -i ${OUT_DEB}"
echo "Then run: pdf-sign-verifier"
