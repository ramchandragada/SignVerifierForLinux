# VPPOB Landing Page

A fast, mobile-responsive, single-page landing site for **VPPOB.COM** — a Virtual
Place of Business (VPOB / APOB) service for GST registration across India. Built as
a Google Ads–compliant landing page.

## What's here

| File | Purpose |
|------|---------|
| `index.html` | The single-page landing page (hero, benefits, process, FAQ, contact, lead form) |
| `styles.css` | All styling (no build step) |
| `main.js` | Lead-form handling + minor interactions |
| `privacy-policy.html` | Privacy Policy (required for Google Ads) |
| `terms.html` | Terms & Conditions |
| `refund-policy.html` | Refund & Cancellation Policy |
| `robots.txt`, `sitemap.xml` | Basic SEO |
| `vercel.json` | Vercel static config (clean URLs + security headers) |

Pure static HTML/CSS/JS — no framework, no build, loads fast.

## Google Ads compliance checklist

- ✅ Clear, honest description of the business and service
- ✅ Accessible **Privacy Policy**, **Terms**, and **Refund Policy**
- ✅ Real business **contact details** (phone, WhatsApp, email, physical address)
- ✅ Consent checkbox + Privacy Policy link on the lead form
- ✅ No pop-ups, no auto-redirects, no misleading claims
- ✅ Honest disclaimer that GST approval is decided by the authorities
- ✅ Mobile-responsive and fast-loading

## Deploy to Vercel

This site lives in the `vppob-landing/` subdirectory of the repo.

### Option A — Connect the GitHub repo (recommended, no CLI)
1. Go to <https://vercel.com/new> and import this GitHub repository.
2. In project settings set **Root Directory** to `vppob-landing`.
3. Framework preset: **Other** (it's static — no build command needed).
4. Deploy, then add your domain **vppob.com** under **Settings → Domains**.

### Option B — Vercel CLI
```bash
cd vppob-landing
npx vercel --prod
```
(Requires a logged-in Vercel account / token.)

## Local preview
```bash
cd vppob-landing
python3 -m http.server 8000
# open http://localhost:8000
```

## Configure lead capture (optional)
By default the form opens a pre-filled email to `sales@thegstco.com`, so it works
with zero setup. To capture leads automatically, create a free
[Formspree](https://formspree.io) form and paste its endpoint into
`FORM_ENDPOINT` at the top of `main.js`.
