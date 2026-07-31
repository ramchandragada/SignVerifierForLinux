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

## Install with .deb (company PCs)

**Always download the newest build** from Releases (every push to `main` publishes a new `.deb`):

https://github.com/ramchandragada/SignVerifierForLinux/releases/latest

```bash
# Example after downloading the latest .deb:
sudo apt install ./pdf-sign-verifier_*_amd64.deb
pdf-sign-verifier          # opens web UI
# or find "PDF Sign Verifier" in the app menu
```

To update later: download the new `.deb` from the same Releases page and install again (`apt` will upgrade the package).

Rebuild locally:

```bash
./packaging/build-deb.sh --docker   # Ubuntu 24.04 via Docker
# or on Ubuntu 24.04:
./packaging/build-deb.sh
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
