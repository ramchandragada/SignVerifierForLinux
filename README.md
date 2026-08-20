# PDF Sign Verifier

Linux-native tool to **cryptographically verify Indian DSC / CCA-chained PDF signatures** — without Windows, VirtualBox, or Adobe Acrobat.

Built first for **Amazon blank NOC** workflows (still fully supported). Also useful for MCA filings, tenders, bank packs, and any PKCS#7-signed PDF that chains to CCA India.

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

Works on Linux Mint XFCE, Ubuntu, and Debian. No special Python version needed. The UI opens in **Google Chrome** (or Chromium / Edge / Brave if Chrome is missing).

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
./run.sh                  # local web UI in Google Chrome → http://127.0.0.1:8765
./run.sh --cli file.pdf   # terminal check
./run.sh --cli file.pdf --report ~/Downloads/report.pdf
./run.sh --batch ~/Documents/signed-pdfs --json
./run.sh --list-roots
./run.sh --irn <64-hex-IRN-or-pdf>
```

## Amazon blank NOC (service provider) — primary workflow

Amazon may issue a **digitally signed blank NOC**. In the web UI:

1. Drop the signed blank PDF (**single file**).
2. If merchant fields are empty, enter **Date**, **M/S**, **M/s.**, and **Maharashtra address**, then **Fill & Verify**.
3. If those fields are already filled, they are **locked** and the signature is verified immediately.

Filling blank fields after Amazon’s signature is expected; the crypto check still validates Amazon’s signature (status may show **MODIFIED** because the form was completed after signing).

## Amazon NAX-1 blank NOC (generic / other states)

Drop **Blank NAX 1 NOC** (or similar generic Amazon letter with dotted lines). The app shows extra fields:

1. Date  
2. Tax Officer Branch  
3. Amazon FC / premises address  
4. State  
5. M/S and M/s. (merchant name)  
6. Merchant main place of business  

Then **Fill & Verify**. If the file is a Print-to-PDF with **no PKCS#7**, verification will show **UNSIGNED** — that copy cannot be cryptographically verified. Use Amazon’s original digitally signed blank whenever available. Maharashtra BOM AcroForm NOCs keep the previous fill path.

## Batch verify (CA firms / desks)

```bash
./run.sh --batch /path/to/folder
./run.sh --batch /path/to/folder --json
```

Or drop **multiple PDFs** on the web UI. Amazon NOC fill stays single-PDF only.

## JSON API (ERP / scripts)

Local Flask server (same process as the UI):

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/verify` | multipart `pdf=@file.pdf` → JSON report |
| `POST /api/v1/batch-verify` | multipart `pdfs=@a.pdf` `pdfs=@b.pdf` |
| `POST /api/v1/irn-inspect` | optional GST IRN helper (`payload=` or `pdf=`) |
| `POST /api/fill-and-verify` | Amazon blank NOC fill + verify (unchanged) |

Example:

```bash
curl -sS -F pdf=@signed.pdf http://127.0.0.1:8765/api/v1/verify | jq .overall
```

## Optional GST IRN helper

e-Invoice IRN / signed QR is a **separate** trust path from PDF DSC signatures. Use `--irn` to inspect IRN-shaped values. Online IRP lookup is opt-in via `PDF_SIGN_VERIFIER_IRN_URL`.

## Results

- **VALID** — signature intact + trusted (CCA India)
- **MODIFIED** — signature intact + trusted, but file changed after signing
- **UNTRUSTED** — signature intact, chain not trusted
- **INVALID** / **UNSIGNED**

## Trust roots & intermediates

Bundled under `trust/`:

- **Roots:** [CCA India](https://cca.gov.in/root_certificate.html) (2015 SPL, 2022, 2022 SPL)
- **Intermediates:** licensed CAs under RCAI 2022 / SPL from [cca.gov.in](https://cca.gov.in/display_cert2022.php) (e-Mudhra, Capricorn, (n)Code, SafeScrypt, Verasys, and others)

`./run.sh --list-roots` prints what is loaded.

## First-time setup (other PCs)

```bash
python3 -m venv --without-pip .venv
curl -fsSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -r requirements.txt
./run.sh
```
