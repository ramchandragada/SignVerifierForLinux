# PDF Sign Verifier

Lightweight Linux tool to **cryptographically verify** PDF digital signatures (Amazon NOC / Indian DSC) without VirtualBox or Adobe Acrobat.

## Important: what is “real” verification?

| Approach | Real? |
|----------|--------|
| Check PKCS#7 / CMS signature + CCA India trust chain | **Yes** |
| Green tick shown in this app after that check | **Yes** (display of a real result) |
| Drawing / photoshopping a green tick into the PDF | **No** — anyone can fake that |
| Adobe “Print to PDF” after verify | **No** — removes the real signature, keeps only a picture |

Amazon’s line *“accept this NOC only if the Digital signature can be verified”* means the **original signed PDF** must still verify. Upload that original — not a stamped/printed lookalike.

## Install / update (.deb — Debian / Ubuntu / Linux Mint)

**One package for all company PCs** (amd64). New builds are published automatically here:

https://github.com/ramchandragada/SignVerifierForLinux/releases/latest

### Update any PC to the latest release (recommended)

Run this on each Linux PC — it always downloads the **newest** `.deb` from GitHub:

```bash
cd ~/Downloads
DEB_URL=$(curl -fsSL https://api.github.com/repos/ramchandragada/SignVerifierForLinux/releases/latest \
  | grep -oE 'https://github.com/[^"]+/pdf-sign-verifier_[^"]+_amd64\.deb' | head -1)
curl -fsSLO "$DEB_URL"
sudo apt install ./pdf-sign-verifier_*_amd64.deb
pkill -f pdf-sign-verifier 2>/dev/null || true
pdf-sign-verifier
```

Same command works for **first install** and later **updates**.

### Or download from the browser

1. Open https://github.com/ramchandragada/SignVerifierForLinux/releases/latest  
2. Download the `.deb` (do **not** type a fake `1.0.X` name)  
3. Install:

```bash
cd ~/Downloads
sudo apt install ./pdf-sign-verifier_*_amd64.deb
pdf-sign-verifier
```

Works on Linux Mint XFCE, Ubuntu, and Debian. No special Python version needed.

Rebuild:

```bash
./packaging/build-deb.sh          # Docker Ubuntu 22.04 → universal .deb
```

## Clone (any PC)

```bash
git clone https://github.com/ramchandragada/SignVerifierForLinux.git
cd SignVerifierForLinux
```

## Quick start

```bash
./run.sh                  # web UI → http://127.0.0.1:8765
./run.sh --cli file.pdf   # terminal check
./run.sh --cli file.pdf --report ~/Downloads/report.pdf
./run.sh --list-roots
```

## Amazon blank NOC (service provider)

Amazon may issue a **digitally signed blank NOC**. In the web UI:

1. Drop the signed blank PDF.
2. If merchant fields are empty, enter **Date**, **M/S**, **M/s.**, and **Maharashtra address**, then **Fill & Verify**.
3. If those fields are already filled, they are **locked** and the signature is verified immediately.

Filling blank fields after Amazon’s signature is expected; the crypto check still validates Amazon’s signature (status may show **MODIFIED** because the form was completed after signing).

## Results

- **VALID** — signature intact + trusted (CCA India)
- **MODIFIED** — signature intact + trusted, but file changed after signing
- **UNTRUSTED** — signature intact, root not trusted
- **INVALID** / **UNSIGNED**

## Trust roots

Bundled under `trust/` from [CCA India](https://cca.gov.in/root_certificate.html).

## First-time setup (other PCs)

```bash
python3 -m venv --without-pip .venv
curl -fsSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -r requirements.txt
./run.sh
```
