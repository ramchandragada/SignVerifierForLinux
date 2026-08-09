from __future__ import annotations

import base64
import tempfile
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, Response, jsonify, render_template_string, request

from . import __version__
from .authentic import (
    build_verification_report_pdf,
    is_cryptographically_verified,
)
from .noc_fields import fill_noc_form, inspect_noc_form
from .trust_store import DEFAULT_TRUST_DIR, trust_root_names
from .verified_appearance import export_verified_appearance_pdf
from .verifier import verify_pdf

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PDF Sign Verifier</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,700&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --ink: #10241f;
      --muted: #5a6d66;
      --line: #d5e0da;
      --bg: #e7f0eb;
      --panel: rgba(255, 255, 255, 0.82);
      --panel-solid: #ffffff;
      --accent: #0f6b56;
      --accent-deep: #0a4a3c;
      --accent-soft: #d8f0e7;
      --gold: #b8892d;
      --gold-soft: #f7edd4;
      --valid: #0f7a45;
      --valid-bg: #e4f6ec;
      --modified: #9a6700;
      --modified-bg: #fff4d8;
      --untrusted: #0b5cab;
      --untrusted-bg: #e7f1fb;
      --invalid: #b42318;
      --invalid-bg: #fdecea;
      --unsigned: #5b6777;
      --unsigned-bg: #eef1f5;
      --shadow: 0 18px 50px rgba(16, 36, 31, 0.08);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Sora", "Ubuntu", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(900px 420px at 8% -8%, #cfe8dc 0%, transparent 55%),
        radial-gradient(800px 380px at 100% 0%, #f3e7c8 0%, transparent 48%),
        radial-gradient(700px 360px at 50% 110%, #d7ebe3 0%, transparent 45%),
        linear-gradient(165deg, #edf5f0 0%, #e8f0eb 42%, #f4f1e8 100%);
      background-attachment: fixed;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.35;
      background-image:
        linear-gradient(rgba(15, 107, 86, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15, 107, 86, 0.045) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: radial-gradient(ellipse 80% 70% at 50% 20%, #000 30%, transparent 85%);
    }
    main {
      position: relative;
      width: min(920px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 2.4rem 0 3.2rem;
    }
    .hero {
      animation: rise 0.7s cubic-bezier(.2,.8,.2,1) both;
      margin-bottom: 1.4rem;
    }
    .brand-mark {
      display: inline-flex;
      align-items: center;
      gap: 0.55rem;
      margin-bottom: 0.85rem;
      color: var(--accent-deep);
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .brand-mark .seal {
      width: 1.55rem;
      height: 1.55rem;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: linear-gradient(145deg, var(--accent) 0%, var(--accent-deep) 100%);
      color: #fff;
      font-family: "Fraunces", "Liberation Serif", Georgia, serif;
      font-size: 0.85rem;
      font-weight: 700;
      box-shadow: 0 6px 16px rgba(15, 107, 86, 0.28);
      animation: pulse-seal 2.8s ease-in-out infinite;
    }
    h1 {
      font-family: "Fraunces", "Liberation Serif", Georgia, serif;
      font-weight: 700;
      font-size: clamp(2.35rem, 6vw, 3.55rem);
      line-height: 1.05;
      margin: 0 0 0.7rem;
      letter-spacing: -0.03em;
      color: var(--ink);
      max-width: 14ch;
    }
    h1 span {
      display: inline;
      background: linear-gradient(120deg, var(--accent-deep) 0%, var(--accent) 55%, #1a7a5f 100%);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }
    .tagline {
      color: var(--muted);
      margin: 0;
      max-width: 40rem;
      font-size: 1.02rem;
      line-height: 1.55;
    }
    .tagline strong { color: var(--accent-deep); font-weight: 600; }
    .drop {
      position: relative;
      margin-top: 1.6rem;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.95) 0%, rgba(248,252,250,0.9) 100%);
      border: 1.5px dashed rgba(15, 107, 86, 0.35);
      border-radius: calc(var(--radius) + 4px);
      padding: 2.4rem 1.4rem 1.8rem;
      text-align: center;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
      overflow: hidden;
      transition: border-color .2s, transform .2s, box-shadow .2s, background .2s;
      animation: rise 0.85s cubic-bezier(.2,.8,.2,1) 0.08s both;
    }
    .drop::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(420px 180px at 50% 0%, rgba(15,107,86,0.08), transparent 70%);
      pointer-events: none;
    }
    .drop > * { position: relative; }
    .drop.dragover {
      border-color: var(--accent);
      border-style: solid;
      background: linear-gradient(180deg, #eefaf5 0%, #ffffff 100%);
      transform: translateY(-3px) scale(1.01);
      box-shadow: 0 22px 55px rgba(15, 107, 86, 0.16);
    }
    .drop-icon {
      width: 64px;
      height: 64px;
      margin: 0 auto 1rem;
      border-radius: 18px;
      display: grid;
      place-items: center;
      background: var(--accent-soft);
      color: var(--accent-deep);
      box-shadow: inset 0 0 0 1px rgba(15,107,86,0.12);
    }
    .drop-icon svg { width: 30px; height: 30px; }
    .drop p { margin: 0.35rem 0; color: var(--muted); }
    .drop strong {
      display: block;
      color: var(--ink);
      font-size: 1.15rem;
      font-weight: 650;
      margin-bottom: 0.2rem;
    }
    input[type=file] { display: none; }
    .actions {
      margin-top: 1.15rem;
      display: flex;
      gap: 0.75rem;
      justify-content: center;
      flex-wrap: wrap;
    }
    button, .btn {
      appearance: none;
      border: 0;
      border-radius: 12px;
      padding: 0.78rem 1.25rem;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      background: linear-gradient(180deg, #148567 0%, var(--accent-deep) 100%);
      color: white;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      box-shadow: 0 8px 18px rgba(10, 74, 60, 0.22);
      transition: transform .15s, box-shadow .15s, filter .15s;
    }
    button:hover, .btn:hover { transform: translateY(-1px); filter: brightness(1.03); }
    button:active, .btn:active { transform: translateY(0); }
    button.secondary, .btn.secondary {
      background: #edf4f0;
      color: var(--accent-deep);
      box-shadow: none;
      border: 1px solid rgba(15,107,86,0.14);
    }
    button.success, .btn.success {
      background: linear-gradient(180deg, #19a05c 0%, #0f7a45 100%);
      box-shadow: 0 8px 18px rgba(15, 122, 69, 0.22);
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; transform: none; filter: none; }
    .meta {
      margin-top: 1rem;
      font-size: 0.9rem;
      color: var(--muted);
      text-align: center;
    }
    #result { margin-top: 1.1rem; }
    #result:not(:empty) { animation: rise 0.45s cubic-bezier(.2,.8,.2,1) both; }
    .card {
      background: var(--panel-solid);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 1.2rem 1.3rem;
      margin-top: 1rem;
      box-shadow: 0 10px 28px rgba(16, 36, 31, 0.05);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      border-radius: 8px;
      padding: 0.38rem 0.7rem;
      font-weight: 700;
      font-size: 0.8rem;
      letter-spacing: 0.04em;
    }
    .VALID { color: var(--valid); background: var(--valid-bg); }
    .MODIFIED { color: var(--modified); background: var(--modified-bg); }
    .UNTRUSTED { color: var(--untrusted); background: var(--untrusted-bg); }
    .INVALID, .ERROR { color: var(--invalid); background: var(--invalid-bg); }
    .UNSIGNED { color: var(--unsigned); background: var(--unsigned-bg); }
    .headline {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .headline h2 {
      margin: 0;
      font-family: "Fraunces", Georgia, serif;
      font-size: 1.25rem;
      font-weight: 650;
    }
    .adobe-stamp {
      display: flex;
      gap: 1rem;
      align-items: center;
      margin-top: 1rem;
      padding: 1.1rem 1.15rem;
      border: 1px solid #cfe3d6;
      border-radius: 14px;
      background:
        radial-gradient(280px 120px at 0% 0%, rgba(15,122,69,0.08), transparent 70%),
        linear-gradient(180deg, #f5fbf7, #ffffff);
    }
    .tick {
      width: 68px;
      height: 68px;
      border-radius: 50%;
      background: linear-gradient(160deg, #1aa85a, #0f7a45);
      color: white;
      display: grid;
      place-items: center;
      font-size: 2rem;
      font-weight: 700;
      flex-shrink: 0;
      box-shadow: 0 10px 22px rgba(15, 122, 69, 0.28);
    }
    .tick.warn { background: linear-gradient(160deg, #d4a017, #c48a00); box-shadow: 0 10px 22px rgba(196,138,0,0.25); }
    .tick.bad { background: linear-gradient(160deg, #d6453d, #b42318); box-shadow: 0 10px 22px rgba(180,35,24,0.25); }
    .tick.ask { background: linear-gradient(160deg, #f0c84a, #e6b800); color: #1c2430; box-shadow: 0 10px 22px rgba(230,184,0,0.22); }
    .adobe-stamp h3 {
      margin: 0 0 0.25rem;
      font-family: "Fraunces", Georgia, serif;
      font-size: 1.25rem;
    }
    .adobe-stamp p { margin: 0.15rem 0; color: var(--ink); }
    .adobe-stamp .sub { color: var(--muted); font-size: 0.92rem; }
    .note {
      margin-top: 0.85rem;
      padding: 0.8rem 0.95rem;
      border-radius: 12px;
      background: #f3f8f5;
      color: var(--muted);
      font-size: 0.92rem;
      text-align: left;
      border: 1px solid rgba(15,107,86,0.08);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 0.75rem;
      margin-top: 1rem;
    }
    .kv {
      background: linear-gradient(180deg, #f6faf8, #f2f6f4);
      border-radius: 12px;
      padding: 0.8rem 0.9rem;
      border: 1px solid rgba(15,107,86,0.06);
    }
    .kv .k {
      color: var(--muted);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
    }
    .kv .v { margin-top: 0.25rem; font-weight: 600; word-break: break-word; }
    .warnings { margin: 0.9rem 0 0; padding-left: 1.1rem; color: #7a4d00; }
    details { margin-top: 0.8rem; color: var(--muted); }
    pre {
      white-space: pre-wrap;
      background: #13201c;
      color: #d7e8df;
      border-radius: 12px;
      padding: 0.9rem;
      overflow: auto;
      font-size: 0.82rem;
    }
    footer {
      margin-top: 1.8rem;
      color: var(--muted);
      font-size: 0.85rem;
      text-align: center;
    }
    .noc-form h2 {
      margin: 0 0 0.35rem;
      font-family: "Fraunces", Georgia, serif;
      font-size: 1.35rem;
    }
    .noc-form .hint { color: var(--muted); margin: 0 0 1rem; font-size: 0.92rem; }
    .field { margin-bottom: 0.9rem; text-align: left; }
    .field label {
      display: block;
      font-size: 0.74rem;
      font-weight: 650;
      color: var(--accent-deep);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 0.4rem;
    }
    .field input, .field textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 0.72rem 0.85rem;
      font: inherit;
      background: #fff;
      color: var(--ink);
      transition: border-color .15s, box-shadow .15s;
    }
    .field input:focus, .field textarea:focus {
      outline: none;
      border-color: rgba(15,107,86,0.55);
      box-shadow: 0 0 0 3px rgba(15,107,86,0.12);
    }
    .field textarea { min-height: 4.2rem; resize: vertical; }
    .field input:disabled, .field textarea:disabled {
      background: #f1f5f3;
      color: #3a4656;
      cursor: not-allowed;
    }
    .locked-banner {
      margin-bottom: 1rem;
      padding: 0.75rem 0.9rem;
      border-radius: 12px;
      background: var(--valid-bg);
      color: var(--valid);
      font-size: 0.92rem;
      font-weight: 600;
      border: 1px solid rgba(15,122,69,0.15);
    }
    .fill-banner {
      margin-bottom: 1rem;
      padding: 0.75rem 0.9rem;
      border-radius: 12px;
      background: var(--gold-soft);
      color: #8a5f12;
      font-size: 0.92rem;
      font-weight: 600;
      border: 1px solid rgba(184,137,45,0.22);
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(14px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse-seal {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.06); }
    }
    @media (max-width: 640px) {
      main { padding-top: 1.5rem; }
      h1 { max-width: none; }
      .drop { padding: 1.8rem 1rem 1.4rem; }
      .adobe-stamp { flex-direction: column; align-items: flex-start; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation: none !important;
        transition: none !important;
      }
    }
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div class="brand-mark"><span class="seal" aria-hidden="true">V</span> Local · Offline-ready</div>
      <h1>PDF Sign <span>Verifier</span></h1>
      <p class="tagline">Fill Amazon blank NOC details when needed, verify the real digital signature, then save an Adobe-style <strong>Signature valid</strong> green tick for upload.</p>
    </header>

    <div class="drop" id="drop">
      <div class="drop-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>
          <path d="M14 3v5h5"/>
          <path d="M12 11v6"/>
          <path d="M9.5 13.5 12 11l2.5 2.5"/>
        </svg>
      </div>
      <p><strong>Drop the original digitally signed PDF</strong></p>
      <p>Blank Amazon NOCs can be filled here, then cryptographically verified.</p>
      <div class="actions">
        <button type="button" id="browse">Choose PDF</button>
        <button type="button" class="secondary" id="clear" hidden>Clear</button>
      </div>
      <input id="file" type="file" accept="application/pdf,.pdf" />
      <div class="meta" id="fileMeta">No file selected</div>
    </div>

    <div id="result"></div>
    <footer>PDF Sign Verifier {{ version }} · Trust roots: {{ root_count }} (CCA India bundled)</footer>
  </main>

  <script>
    const drop = document.getElementById('drop');
    const fileInput = document.getElementById('file');
    const browse = document.getElementById('browse');
    const clearBtn = document.getElementById('clear');
    const fileMeta = document.getElementById('fileMeta');
    const result = document.getElementById('result');
    let lastFile = null;

    browse.addEventListener('click', () => fileInput.click());
    clearBtn.addEventListener('click', () => {
      fileInput.value = '';
      lastFile = null;
      fileMeta.textContent = 'No file selected';
      clearBtn.hidden = true;
      result.innerHTML = '';
    });

    ['dragenter','dragover'].forEach(evt => drop.addEventListener(evt, e => {
      e.preventDefault(); drop.classList.add('dragover');
    }));
    ['dragleave','drop'].forEach(evt => drop.addEventListener(evt, e => {
      e.preventDefault(); drop.classList.remove('dragover');
    }));
    drop.addEventListener('drop', e => {
      const file = e.dataTransfer.files?.[0];
      if (file) handlePdf(file);
    });
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      if (file) handlePdf(file);
    });

    async function handlePdf(file) {
      lastFile = file;
      fileMeta.textContent = `Checking: ${file.name} (${Math.round(file.size/1024)} KB)`;
      clearBtn.hidden = false;
      browse.disabled = true;
      result.innerHTML = `<div class="card">Inspecting NOC fields and signature…</div>`;
      const body = new FormData();
      body.append('pdf', file);
      try {
        const res = await fetch('/api/verify', { method: 'POST', body });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Verification failed');
        renderAll(data);
      } catch (err) {
        result.innerHTML = `<div class="card"><span class="badge ERROR">ERROR</span><p>${esc(err.message)}</p></div>`;
      } finally {
        browse.disabled = false;
      }
    }

    function renderAll(data) {
      const noc = data.noc_form || {};
      let html = '';
      if (noc.is_amazon_noc) {
        html += renderNocForm(noc, data);
      }
      if (!noc.needs_fill) {
        html += renderReport(data);
      } else if (data.signatures?.length) {
        html += `<div class="card note" style="margin-top:1rem">Amazon signature is present on this blank NOC.
          Fill the merchant fields above, then click <strong>Fill &amp; Verify</strong> to write the details and run the crypto check.</div>`;
      }
      result.innerHTML = html;
      wireButtons(data);
    }

    function wireButtons(data) {
      const exportBtn = document.getElementById('exportBtn');
      if (exportBtn) exportBtn.addEventListener('click', exportVerifiedNoc);
      const reportBtn = document.getElementById('reportBtn');
      if (reportBtn) reportBtn.addEventListener('click', downloadReport);
      const fillBtn = document.getElementById('fillVerifyBtn');
      if (fillBtn) fillBtn.addEventListener('click', fillAndVerify);
      const ms1 = document.getElementById('noc_ms_name');
      const ms2 = document.getElementById('noc_ms_name_2');
      if (ms1 && ms2 && !ms2.disabled) {
        ms1.addEventListener('input', () => {
          if (!ms2.dataset.touched) ms2.value = ms1.value;
        });
        ms2.addEventListener('input', () => { ms2.dataset.touched = '1'; });
      }
    }

    function fieldValue(noc, name) {
      const f = (noc.fields || []).find(x => x.name === name);
      return f ? (f.value || '') : '';
    }

    function renderNocForm(noc, data) {
      const locked = !!noc.complete && !noc.needs_fill;
      const dis = locked ? 'disabled' : '';
      const banner = locked
        ? `<div class="locked-banner">Details already filled — fields locked. Signature verified below.</div>`
        : `<div class="fill-banner">${esc(noc.message || 'Enter merchant details, then Fill & Verify.')}</div>`;
      return `
        <div class="card noc-form">
          <h2>Amazon NOC merchant details</h2>
          <p class="hint">Date · M/S · M/s. · Main place of business in Maharashtra. M/S and M/s. use the same seller name on Amazon’s form.</p>
          ${banner}
          <div class="field">
            <label for="noc_date">1) Date</label>
            <input id="noc_date" type="text" placeholder="DD/MM/YYYY" value="${esc(fieldValue(noc,'date'))}" ${dis} />
          </div>
          <div class="field">
            <label for="noc_ms_name">2) M/S</label>
            <input id="noc_ms_name" type="text" placeholder="Merchant / seller legal name" value="${esc(fieldValue(noc,'ms_name'))}" ${dis} />
          </div>
          <div class="field">
            <label for="noc_ms_name_2">3) M/s.</label>
            <input id="noc_ms_name_2" type="text" placeholder="Same merchant name (usually)" value="${esc(fieldValue(noc,'ms_name_2'))}" ${dis} />
          </div>
          <div class="field">
            <label for="noc_address">4) Main place of business in Maharashtra</label>
            <textarea id="noc_address" placeholder="Full address" ${dis}>${esc(fieldValue(noc,'address'))}</textarea>
          </div>
          <div class="field">
            <label for="noc_address_line2">Address line 2 (optional)</label>
            <input id="noc_address_line2" type="text" placeholder="Overflow address line" value="${esc(fieldValue(noc,'address_line2'))}" ${dis} />
          </div>
          ${locked ? '' : `
          <div class="actions" style="justify-content:flex-start">
            <button type="button" class="success" id="fillVerifyBtn">Fill &amp; Verify signature</button>
          </div>`}
        </div>`;
    }

    async function fillAndVerify() {
      if (!lastFile) return;
      const date = document.getElementById('noc_date')?.value?.trim() || '';
      const ms = document.getElementById('noc_ms_name')?.value?.trim() || '';
      const ms2 = document.getElementById('noc_ms_name_2')?.value?.trim() || '';
      const address = document.getElementById('noc_address')?.value?.trim() || '';
      const address2 = document.getElementById('noc_address_line2')?.value?.trim() || '';
      if (!date || !ms || !address) {
        alert('Please fill Date, M/S, and the Maharashtra address.');
        return;
      }
      if (!ms2) ms2 = ms;
      const btn = document.getElementById('fillVerifyBtn');
      if (btn) { btn.disabled = true; btn.textContent = 'Filling & verifying…'; }
      const body = new FormData();
      body.append('pdf', lastFile);
      body.append('date', date);
      body.append('ms_name', ms);
      body.append('ms_name_2', ms2);
      body.append('address', address);
      body.append('address_line2', address2);
      try {
        const res = await fetch('/api/fill-and-verify', { method: 'POST', body });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fill & verify failed');
        if (data.filled_pdf_base64) {
          const bin = atob(data.filled_pdf_base64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          const filledName = data.filled_file_name || lastFile.name.replace(/\\.pdf$/i, '') + '_filled.pdf';
          lastFile = new File([bytes], filledName, { type: 'application/pdf' });
          fileMeta.textContent = `Filled: ${filledName} (${Math.round(lastFile.size/1024)} KB)`;
          // Offer immediate download of filled signed NOC
          const url = URL.createObjectURL(lastFile);
          const a = document.createElement('a');
          a.href = url; a.download = filledName;
          document.body.appendChild(a); a.click(); a.remove();
          URL.revokeObjectURL(url);
        }
        renderAll(data);
      } catch (err) {
        alert(err.message);
        if (btn) { btn.disabled = false; btn.textContent = 'Fill & Verify signature'; }
      }
    }

    async function exportVerifiedNoc() {
      if (!lastFile) return;
      const btn = document.getElementById('exportBtn');
      if (btn) { btn.disabled = true; btn.textContent = 'Creating verified NOC…'; }
      const body = new FormData();
      body.append('pdf', lastFile);
      try {
        const res = await fetch('/api/export-verified-noc', { method: 'POST', body });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || 'Export failed');
        }
        const blob = await res.blob();
        const disposition = res.headers.get('Content-Disposition') || '';
        const match = /filename="?([^"]+)"?/.exec(disposition);
        const name = match?.[1] || lastFile.name.replace(/\\.pdf$/i, '') + '_Signature_valid.pdf';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert(err.message);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save verified NOC (green Signature valid)'; }
      }
    }

    async function downloadReport() {
      if (!lastFile) return;
      const btn = document.getElementById('reportBtn');
      if (btn) { btn.disabled = true; btn.textContent = 'Creating report…'; }
      const body = new FormData();
      body.append('pdf', lastFile);
      try {
        const res = await fetch('/api/verification-report', { method: 'POST', body });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || 'Report failed');
        }
        const blob = await res.blob();
        const disposition = res.headers.get('Content-Disposition') || '';
        const match = /filename="?([^"]+)"?/.exec(disposition);
        const name = match?.[1] || 'verification_report.pdf';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert(err.message);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Download verification report (audit only)'; }
      }
    }

    function esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    function stampFor(data) {
      const sig = (data.signatures || [])[0];
      const ok = !!data.cryptographically_verified;
      if (ok && sig) {
        const note = data.overall === 'MODIFIED'
          ? 'Crypto check passed. Merchant fields were filled after Amazon signed (expected for blank NOCs). Verified NOC export is available for upload.'
          : 'Crypto check passed. Save the verified NOC below (Adobe-style Signature valid) for upload.';
        return `
          <div class="adobe-stamp">
            <div class="tick">✓</div>
            <div>
              <h3>Signature valid</h3>
              <p>Digitally signed by ${esc(sig.signer_name)}</p>
              <p class="sub">Date: ${esc(sig.signing_time || '—')}</p>
              <p class="sub">Trust: ${esc(sig.trust_anchor || 'CCA India')}</p>
              <div class="note">${note}</div>
              <div class="actions" style="justify-content:flex-start;margin-top:0.85rem">
                <button type="button" class="success" id="exportBtn">Save verified NOC (green Signature valid)</button>
                <button type="button" class="secondary" id="reportBtn">Download audit report</button>
              </div>
            </div>
          </div>`;
      }
      if (data.overall === 'UNTRUSTED' && sig) {
        return `
          <div class="adobe-stamp">
            <div class="tick ask">?</div>
            <div>
              <h3>Signature Not Verified</h3>
              <p>Digitally signed by ${esc(sig.signer_name)}</p>
              <p class="sub">Signature math may be OK, but the issuer is not in the trust store.</p>
            </div>
          </div>`;
      }
      if (data.overall === 'INVALID' || data.overall === 'ERROR') {
        return `
          <div class="adobe-stamp">
            <div class="tick bad">✗</div>
            <div>
              <h3>Signature invalid</h3>
              <p class="sub">${esc(data.overall_label || data.error || '')}</p>
            </div>
          </div>`;
      }
      if (data.overall === 'UNSIGNED') {
        if (data.is_visual_noc) {
          return `
          <div class="adobe-stamp">
            <div class="tick">✓</div>
            <div>
              <h3>Verified NOC (visual only)</h3>
              <p class="sub">This is the green <strong>Signature valid</strong> file saved for upload. It has no PKCS#7 — that is expected. Drop the <strong>original</strong> digitally signed PDF to run crypto verification again.</p>
            </div>
          </div>`;
        }
        return `
          <div class="adobe-stamp">
            <div class="tick ask">?</div>
            <div>
              <h3>No digital signature found</h3>
              <p class="sub">This file has no PKCS#7 signature (often a Print-to-PDF / scanned copy). It cannot be cryptographically verified.</p>
            </div>
          </div>`;
      }
      return '';
    }

    function renderReport(data) {
      const sigs = (data.signatures || []).map(sig => `
        <div class="card">
          <div class="headline">
            <h2>${esc(sig.field_name || 'Signature')}</h2>
            <span class="badge ${esc(sig.overall)}">${esc(sig.overall)}</span>
          </div>
          <p>${esc(sig.summary)}</p>
          <div class="grid">
            <div class="kv"><div class="k">Signer</div><div class="v">${esc(sig.signer_name)}</div></div>
            <div class="kv"><div class="k">Email</div><div class="v">${esc(sig.signer_email || '—')}</div></div>
            <div class="kv"><div class="k">Issuer</div><div class="v">${esc(sig.issuer || '—')}</div></div>
            <div class="kv"><div class="k">Signing time</div><div class="v">${esc(sig.signing_time || '—')}</div></div>
            <div class="kv"><div class="k">Intact</div><div class="v">${sig.intact ? 'Yes' : 'No'}</div></div>
            <div class="kv"><div class="k">Trusted CA</div><div class="v">${sig.trusted ? 'Yes' : 'No'}</div></div>
            <div class="kv"><div class="k">Whole document covered</div><div class="v">${sig.covers_whole_document ? 'Yes' : 'No'}</div></div>
            <div class="kv"><div class="k">Hash</div><div class="v">${esc(sig.hash_algorithm || '—')}</div></div>
          </div>
          ${sig.warnings?.length ? `<ul class="warnings">${sig.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
          ${sig.details ? `<details><summary>Technical details</summary><pre>${esc(sig.details)}</pre></details>` : ''}
        </div>
      `).join('');

      return `
        <div class="card">
          <div class="headline">
            <div>
              <h2>${esc(data.file_name)}</h2>
              <div class="meta" style="text-align:left;margin:0.35rem 0 0">${esc(
                data.is_visual_noc && data.overall === 'UNSIGNED'
                  ? 'Saved verified NOC — visual Signature valid for upload (no PKCS#7 by design)'
                  : data.overall_label
              )}</div>
            </div>
            <span class="badge ${esc(data.is_visual_noc && data.overall === 'UNSIGNED' ? 'VALID' : data.overall)}">${esc(
              data.is_visual_noc && data.overall === 'UNSIGNED' ? 'VISUAL NOC' : data.overall
            )}</span>
          </div>
          ${stampFor(data)}
          ${data.error ? `<p>${esc(data.error)}</p>` : ''}
        </div>
        ${sigs || ''}
      `;
    }
  </script>
</body>
</html>
"""


def _report_payload(report, upload_name: str, path: Path) -> dict:
    data = report.to_dict()
    data["file_name"] = Path(upload_name).name
    data["cryptographically_verified"] = is_cryptographically_verified(report)
    data["is_visual_noc"] = _is_visual_noc_export(path)
    data["noc_form"] = inspect_noc_form(path).to_dict()
    return data


@app.get("/")
def home():
    try:
        roots = trust_root_names(DEFAULT_TRUST_DIR)
        root_count = len(roots)
    except Exception:
        root_count = 0
    return render_template_string(PAGE, version=__version__, root_count=root_count)


@app.post("/api/verify")
def api_verify():
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return jsonify({"error": "No PDF uploaded"}), 400
    if not upload.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a .pdf file"}), 400

    with tempfile.TemporaryDirectory(prefix="pdfsig-") as tmp:
        target = Path(tmp) / Path(upload.filename).name
        upload.save(target)
        noc = inspect_noc_form(target)
        # Blank NOCs: return form status first; still verify so crypto status is known.
        report = verify_pdf(target)
        data = _report_payload(report, upload.filename, target)
        if noc.needs_fill:
            data["awaiting_fill"] = True
        return jsonify(data)


@app.post("/api/fill-and-verify")
def api_fill_and_verify():
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return jsonify({"error": "No PDF uploaded"}), 400
    if not upload.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a .pdf file"}), 400

    date = (request.form.get("date") or "").strip()
    ms_name = (request.form.get("ms_name") or "").strip()
    ms_name_2 = (request.form.get("ms_name_2") or "").strip() or ms_name
    address = (request.form.get("address") or "").strip()
    address_line2 = (request.form.get("address_line2") or "").strip()

    with tempfile.TemporaryDirectory(prefix="pdfsig-fill-") as tmp:
        source = Path(tmp) / Path(upload.filename).name
        upload.save(source)
        filled_name = f"{Path(upload.filename).stem}_filled.pdf"
        filled = Path(tmp) / filled_name
        try:
            fill_noc_form(
                source,
                filled,
                date=date,
                ms_name=ms_name,
                ms_name_2=ms_name_2,
                address=address,
                address_line2=address_line2,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Could not fill NOC fields: {exc}"}), 400

        report = verify_pdf(filled)
        data = _report_payload(report, filled_name, filled)
        data["filled_file_name"] = filled_name
        data["filled_pdf_base64"] = base64.b64encode(filled.read_bytes()).decode("ascii")
        data["awaiting_fill"] = False
        return jsonify(data)


def _is_visual_noc_export(path: Path) -> bool:
    """True for NOCs we exported (green tick visual; PKCS#7 removed by design)."""
    try:
        import fitz

        doc = fitz.open(path)
        try:
            meta = doc.metadata or {}
            keywords = (meta.get("keywords") or "") + " " + (meta.get("subject") or "")
            if "PDF-Sign-Verifier-NOC" in keywords:
                return True
            if path.name.endswith("_Signature_valid.pdf"):
                return True
        finally:
            doc.close()
    except Exception:
        pass
    return False


@app.post("/api/export-verified-noc")
def api_export_verified_noc():
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return jsonify({"error": "No PDF uploaded"}), 400
    if not upload.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a .pdf file"}), 400

    with tempfile.TemporaryDirectory(prefix="pdfsig-noc-") as tmp:
        target = Path(tmp) / Path(upload.filename).name
        upload.save(target)
        out = Path(tmp) / f"{Path(upload.filename).stem}_Signature_valid.pdf"
        try:
            report = export_verified_appearance_pdf(target, out)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        return Response(
            out.read_bytes(),
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{out.name}"',
                "X-Verification-Status": report.overall,
            },
        )


@app.post("/api/verification-report")
def api_verification_report():
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return jsonify({"error": "No PDF uploaded"}), 400

    with tempfile.TemporaryDirectory(prefix="pdfsig-report-") as tmp:
        target = Path(tmp) / Path(upload.filename).name
        upload.save(target)
        report = verify_pdf(target)
        report.file_name = Path(upload.filename).name
        pdf_bytes = build_verification_report_pdf(report)
        name = f"{Path(upload.filename).stem}_verification_report.pdf"
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )


def _pick_port(host: str, preferred: int, attempts: int = 20) -> int:
    """Use preferred port, or the next free one if it is already taken."""
    import socket

    for port in range(preferred, preferred + max(1, attempts)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(
        f"No free port found from {preferred} to {preferred + attempts - 1}. "
        "Stop the old pdf-sign-verifier process, or start with --port 8766"
    )


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    chosen = _pick_port(host, port)
    url = f"http://{host}:{chosen}/"
    if open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"PDF Sign Verifier {__version__}")
    if chosen != port:
        print(f"Port {port} is busy — using {chosen} instead.")
    print(f"Open {url}  (Ctrl+C to stop)")
    print("Fill blank Amazon NOC → Verify crypto → Save Signature valid NOC")
    app.run(host=host, port=chosen, debug=False, use_reloader=False)
