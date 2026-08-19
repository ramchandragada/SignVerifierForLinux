#!/usr/bin/env bash
# Build ONE universal .deb that runs on Debian / Ubuntu / Linux Mint (amd64).
#
# Uses PyInstaller so the package does NOT depend on a specific system Python.
# Built on Ubuntu 22.04 (oldest common glibc) → runs on Mint 21/22, Ubuntu 22.04+, Debian 12+.
#
# Usage:
#   ./packaging/build-deb.sh              # build via Docker (recommended)
#   ./packaging/build-deb.sh --local      # build on this machine (needs pyinstaller)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_NAME="pdf-sign-verifier"
VERSION="${VERSION:-1.0.0}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
DIST_DIR="${ROOT}/dist"
STAGE="${DIST_DIR}/stage"
OUT_DEB="${DIST_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
DOCKER_IMAGE="${DOCKER_IMAGE:-ubuntu:22.04}"

if [[ "${1:-}" != "--local" ]]; then
  echo "==> Building UNIVERSAL .deb inside ${DOCKER_IMAGE} (works on Mint/Ubuntu/Debian)..."
  mkdir -p "${DIST_DIR}"
  docker run --rm \
    -v "${ROOT}:/src:ro" \
    -v "${DIST_DIR}:/out" \
    -e VERSION="${VERSION}" \
    "${DOCKER_IMAGE}" \
    bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq python3 python3-venv python3-pip dpkg-dev binutils \
        fonts-liberation fonts-urw-base35 file >/dev/null
      cp -a /src /build
      cd /build
      rm -rf /build/dist/stage /build/dist/*.deb /build/build /build/dist/pyi
      mkdir -p /build/dist
      bash /build/packaging/build-deb.sh --local
      cp -a /build/dist/*.deb /out/
      ls -lh /out/*.deb
    '
  echo "Done: $(ls -1t "${DIST_DIR}"/${PKG_NAME}_*_*.deb | head -1)"
  exit 0
fi

echo "==> Staging universal ${PKG_NAME} ${VERSION} (${ARCH})"
rm -rf "${STAGE}" "${DIST_DIR}/pyi" "${ROOT}/build" "${ROOT}/*.spec"
mkdir -p \
  "${STAGE}/DEBIAN" \
  "${STAGE}/opt/${PKG_NAME}" \
  "${STAGE}/usr/bin" \
  "${STAGE}/usr/share/applications" \
  "${STAGE}/usr/share/doc/${PKG_NAME}" \
  "${STAGE}/usr/share/icons/hicolor/scalable/apps"

# Bundle fonts into the app for systems without liberation/urw
mkdir -p "${ROOT}/packaging/bundle-fonts"
cp -n /usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf "${ROOT}/packaging/bundle-fonts/" 2>/dev/null || true
cp -n /usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf "${ROOT}/packaging/bundle-fonts/" 2>/dev/null || true
cp -n /usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf "${ROOT}/packaging/bundle-fonts/" 2>/dev/null || true
cp -n /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf "${ROOT}/packaging/bundle-fonts/" 2>/dev/null || true

echo "==> Creating build venv + installing deps + PyInstaller..."
python3 -m venv "${DIST_DIR}/build-venv"
# shellcheck disable=SC1091
source "${DIST_DIR}/build-venv/bin/activate"
pip install -q --upgrade pip wheel
pip install -q -r "${ROOT}/requirements.txt" pyinstaller tzdata

echo "==> Stamping app version ${VERSION}..."
# Keep UI/CLI version in sync with the .deb release number.
sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" "${ROOT}/pdf_sign_verifier/__init__.py"

echo "==> Freezing app with PyInstaller (onedir)..."
cd "${ROOT}"
pyinstaller \
  --noconfirm \
  --clean \
  --name pdf-sign-verifier \
  --onedir \
  --distpath "${DIST_DIR}/pyi" \
  --workpath "${DIST_DIR}/pyi-work" \
  --specpath "${DIST_DIR}/pyi-work" \
  --paths "${ROOT}" \
  --collect-all pymupdf \
  --collect-all cryptography \
  --collect-all PIL \
  --collect-all tzdata \
  --hidden-import reportlab \
  --hidden-import flask \
  --hidden-import zoneinfo \
  --hidden-import tzdata \
  --hidden-import pdf_sign_verifier \
  --hidden-import pdf_sign_verifier.webapp \
  --hidden-import pdf_sign_verifier.verifier \
  --hidden-import pdf_sign_verifier.verified_appearance \
  --hidden-import pdf_sign_verifier.trust_store \
  --hidden-import pdf_sign_verifier.cli \
  --hidden-import pdf_sign_verifier.authentic \
  --hidden-import pdf_sign_verifier.noc_fields \
  --hidden-import pdf_sign_verifier.batch \
  --hidden-import pdf_sign_verifier.irn_qr \
  --hidden-import webview \
  --collect-all webview \
  --add-data "${ROOT}/trust:trust" \
  --add-data "${ROOT}/packaging/bundle-fonts:fonts" \
  --add-data "${ROOT}/pdf_sign_verifier/static:static" \
  "${ROOT}/main.py"

# Install frozen tree under /opt
cp -a "${DIST_DIR}/pyi/pdf-sign-verifier/." "${STAGE}/opt/${PKG_NAME}/"
chmod 0755 "${STAGE}/opt/${PKG_NAME}/pdf-sign-verifier"

# Launcher (thin wrapper)
cat > "${STAGE}/usr/bin/pdf-sign-verifier" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /opt/pdf-sign-verifier/pdf-sign-verifier "$@"
EOF
chmod 0755 "${STAGE}/usr/bin/pdf-sign-verifier"

# Desktop entry (XFCE / GNOME / KDE / Cinnamon)
for sz in 16 32 48 64 128 256 512; do
  mkdir -p "${STAGE}/usr/share/icons/hicolor/${sz}x${sz}/apps"
  install -m 0644 "${ROOT}/packaging/icons/pdf-sign-verifier-${sz}.png" \
    "${STAGE}/usr/share/icons/hicolor/${sz}x${sz}/apps/pdf-sign-verifier.png"
done
install -m 0644 "${ROOT}/packaging/icons/pdf-sign-verifier.svg" \
  "${STAGE}/usr/share/icons/hicolor/scalable/apps/pdf-sign-verifier.svg"

cat > "${STAGE}/usr/share/applications/pdf-sign-verifier.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PDF Sign Verifier
Comment=Verify Indian DSC / Amazon NOC PDF signatures
Exec=pdf-sign-verifier --gui
Icon=pdf-sign-verifier
Terminal=false
Categories=Office;Utility;XFCE;
Keywords=PDF;Signature;DSC;NOC;Verify;Mint;Ubuntu;Debian;
StartupNotify=true
StartupWMClass=PDFSignVerifier
SingleMainWindow=true
EOF

install -m 0644 "${ROOT}/README.md" "${STAGE}/usr/share/doc/${PKG_NAME}/README.md"
cat > "${STAGE}/usr/share/doc/${PKG_NAME}/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: PDF Sign Verifier
Files: *
Copyright: PDF Sign Verifier contributors
License: Proprietary
 Internal company distribution.
EOF

INSTALLED_SIZE="$(du -sk "${STAGE}/opt" "${STAGE}/usr" | awk '{s+=$1} END {print s}')"
cat > "${STAGE}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: libc6
Recommends: fonts-liberation | fonts-dejavu-core, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0
Maintainer: Ramchandra Gada <ramchandragada@users.noreply.github.com>
Description: Verify PDF digital signatures (Indian DSC / Amazon NOC)
 Self-contained Linux tool to cryptographically verify PDF signatures
 using CCA India trust roots, with a local web UI and verified-NOC export.
 .
 One package for Debian, Ubuntu, and Linux Mint (amd64). No system Python
 version required — runtime is bundled.
Installed-Size: ${INSTALLED_SIZE}
Homepage: https://github.com/ramchandragada/SignVerifierForLinux
EOF

cat > "${STAGE}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-icon-caches >/dev/null 2>&1; then
  update-icon-caches /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
echo "PDF Sign Verifier installed."
echo "  Run:  pdf-sign-verifier"
echo "  Or open 'PDF Sign Verifier' from the application menu."
EOF
chmod 0755 "${STAGE}/DEBIAN/postinst"

cat > "${STAGE}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
EOF
chmod 0755 "${STAGE}/DEBIAN/postrm"

echo "==> Building .deb..."
mkdir -p "${DIST_DIR}"
dpkg-deb --root-owner-group --build "${STAGE}" "${OUT_DEB}"
echo
ls -lh "${OUT_DEB}"
file "${STAGE}/opt/${PKG_NAME}/pdf-sign-verifier" || true
echo
echo "Install on ANY Debian/Ubuntu/Mint amd64 PC:"
echo "  sudo apt install ./${OUT_DEB##*/}"
echo "  pdf-sign-verifier"
