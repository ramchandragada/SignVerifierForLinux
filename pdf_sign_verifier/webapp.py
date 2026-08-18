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
from .batch import verify_many
from .irn_qr import inspect_pdf_for_irn, inspect_text_payload, verify_irn_online
from .noc_fields import fill_noc_form, inspect_noc_form
from .trust_store import DEFAULT_TRUST_DIR, load_intermediate_certs, trust_root_names
from .verified_appearance import export_verified_appearance_pdf
from .verifier import verify_pdf

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PDF Sign Verifier · Indian DSC on Linux</title>
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
    .mode-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1rem;
      margin-top: 1.2rem;
      animation: rise 0.7s cubic-bezier(.2,.8,.2,1) 0.1s both;
    }
    .mode-card {
      background: var(--panel-solid);
      border: 1.5px solid var(--line);
      border-radius: var(--radius);
      padding: 1.4rem 1.3rem;
      cursor: pointer;
      transition: border-color .2s, transform .2s, box-shadow .2s;
      text-align: left;
    }
    .mode-card:hover {
      border-color: var(--accent);
      transform: translateY(-3px);
      box-shadow: 0 16px 40px rgba(15,107,86,0.12);
    }
    .mode-card h2 {
      font-family: "Fraunces", Georgia, serif;
      font-size: 1.18rem;
      margin: 0.8rem 0 0.4rem;
    }
    .mode-card p { color: var(--muted); margin: 0; font-size: 0.92rem; line-height: 1.5; }
    .mode-card p strong { color: var(--ink); }
    .mode-icon {
      width: 52px; height: 52px;
      border-radius: 14px;
      display: grid; place-items: center;
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
      <div class="brand-mark"><span class="seal" aria-hidden="true">V</span> Indian DSC · CCA trust · Linux</div>
      <h1>PDF Sign <span>Verifier</span></h1>
      <p class="tagline">Verify Indian DSC-signed PDFs on Linux — no Windows, no Adobe.</p>
    </header>

    <div id="modeSelect" class="mode-grid">
      <div class="mode-card" id="modeVerify">
        <div class="mode-icon" style="background:var(--valid-bg);color:var(--valid)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:28px;height:28px"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
        </div>
        <h2>Verify Pre-filled Signed NOC</h2>
        <p>NOC already has seller details filled in. Drop the signed PDF to <strong>verify the digital signature</strong> and save with Adobe-style green tick.</p>
      </div>
      <div class="mode-card" id="modeBlank">
        <div class="mode-icon" style="background:var(--gold-soft);color:#8a5f12">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:28px;height:28px"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
        </div>
        <h2>Fill Blank Signed NOC</h2>
        <p>NOC is blank (dotted lines / empty fields). <strong>Add seller name, date, address</strong> first, then verify the digital signature.</p>
      </div>
    </div>

    <div id="workArea" hidden>
      <div class="actions" style="margin-bottom:1rem">
        <button type="button" class="secondary" id="backBtn">← Back to options</button>
        <button type="button" class="secondary" id="clear" hidden>Clear file</button>
      </div>

      <div class="drop" id="drop">
        <div class="drop-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>
            <path d="M14 3v5h5"/>
            <path d="M12 11v6"/>
            <path d="M9.5 13.5 12 11l2.5 2.5"/>
          </svg>
        </div>
        <p><strong id="dropLabel">Drop signed PDF here</strong></p>
        <p id="dropHint">PKCS#7 / CMS check against CCA India roots + licensed CA intermediates.</p>
        <div class="actions">
          <button type="button" id="browse">Choose PDF</button>
        </div>
        <input id="file" type="file" accept="application/pdf,.pdf" />
        <div class="meta" id="fileMeta">No file selected</div>
      </div>

      <div id="result"></div>
    </div>

    <details class="card" style="margin-top:1.2rem">
      <summary style="cursor:pointer;font-weight:600;font-family:Fraunces,Georgia,serif">Optional: GST IRN helper</summary>
      <p class="meta" style="text-align:left;margin:0.6rem 0 0.8rem">Separate from PDF DSC verify. Paste a 64-character IRN or QR JSON text.</p>
      <div class="field">
        <label for="irnInput">IRN / QR payload</label>
        <textarea id="irnInput" placeholder="Paste IRN (64 hex) or QR JSON"></textarea>
      </div>
      <div class="actions" style="justify-content:flex-start;margin-top:0">
        <button type="button" class="secondary" id="irnBtn">Inspect IRN</button>
      </div>
      <pre id="irnOut" hidden style="margin-top:0.8rem"></pre>
    </details>

    <footer>PDF Sign Verifier {{ version }} · Trust anchors: {{ root_count }} · Intermediates: {{ inter_count }} (CCA India)</footer>
  </main>

  <script>
    const modeSelect = document.getElementById('modeSelect');
    const workArea = document.getElementById('workArea');
    const drop = document.getElementById('drop');
    const fileInput = document.getElementById('file');
    const browse = document.getElementById('browse');
    const clearBtn = document.getElementById('clear');
    const backBtn = document.getElementById('backBtn');
    const fileMeta = document.getElementById('fileMeta');
    const result = document.getElementById('result');
    const dropLabel = document.getElementById('dropLabel');
    const dropHint = document.getElementById('dropHint');
    let lastFile = null;
    let currentMode = '';  // 'verify' or 'blank'

    document.getElementById('modeVerify').addEventListener('click', () => enterMode('verify'));
    document.getElementById('modeBlank').addEventListener('click', () => enterMode('blank'));

    function enterMode(mode) {
      currentMode = mode;
      modeSelect.hidden = true;
      workArea.hidden = false;
      result.innerHTML = '';
      fileInput.value = '';
      lastFile = null;
      clearBtn.hidden = true;
      fileMeta.textContent = 'No file selected';
      if (mode === 'verify') {
        dropLabel.textContent = 'Drop the pre-filled signed NOC / any signed PDF';
        dropHint.textContent = 'Signature will be verified immediately. For batch, select multiple files.';
        fileInput.multiple = true;
      } else {
        dropLabel.textContent = 'Drop the blank signed NOC';
        dropHint.textContent = 'We\u2019ll detect blank fields so you can add seller name, date, address — then verify.';
        fileInput.multiple = false;
      }
    }

    backBtn.addEventListener('click', () => {
      modeSelect.hidden = false;
      workArea.hidden = true;
      result.innerHTML = '';
      fileInput.value = '';
      lastFile = null;
      currentMode = '';
    });

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
      const files = [...(e.dataTransfer.files || [])].filter(f => /\.pdf$/i.test(f.name));
      if (files.length) handleFiles(files);
    });
    fileInput.addEventListener('change', () => {
      const files = [...(fileInput.files || [])];
      if (files.length) handleFiles(files);
    });

    document.getElementById('irnBtn')?.addEventListener('click', async () => {
      const text = document.getElementById('irnInput')?.value?.trim() || '';
      const out = document.getElementById('irnOut');
      if (!text) { alert('Paste an IRN or QR payload first.'); return; }
      const body = new FormData();
      body.append('payload', text);
      try {
        const res = await fetch('/api/irn-inspect', { method: 'POST', body });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'IRN inspect failed');
        out.hidden = false;
        out.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        out.hidden = false;
        out.textContent = String(err.message || err);
      }
    });

    async function handleFiles(files) {
      clearBtn.hidden = false;
      if (currentMode === 'verify' && files.length > 1) {
        await handleBatch(files);
      } else {
        await handlePdf(files[0]);
      }
    }

    async function handleBatch(files) {
      lastFile = null;
      fileMeta.textContent = `Batch checking ${files.length} PDFs…`;
      browse.disabled = true;
      result.innerHTML = `<div class="card">Running batch cryptographic verification…</div>`;
      const body = new FormData();
      for (const f of files) body.append('pdfs', f);
      try {
        const res = await fetch('/api/batch-verify', { method: 'POST', body });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Batch verification failed');
        result.innerHTML = renderBatch(data);
      } catch (err) {
        result.innerHTML = `<div class="card"><span class="badge ERROR">ERROR</span><p>${esc(err.message)}</p></div>`;
      } finally {
        browse.disabled = false;
      }
    }

    function renderBatch(data) {
      const rows = (data.results || []).map(item => `
        <div class="kv">
          <div class="k">${esc(item.file_name)}</div>
          <div class="v"><span class="badge ${esc(item.cryptographically_verified ? 'VALID' : item.overall)}">${esc(item.cryptographically_verified ? 'PASS' : item.overall)}</span> ${esc(item.overall_label || '')}</div>
        </div>`).join('');
      return `
        <div class="card">
          <div class="headline">
            <div>
              <h2>Batch verification</h2>
              <div class="meta" style="text-align:left;margin:0.35rem 0 0">
                ${data.total} PDFs · verified ${data.verified} · failed ${data.failed} · unsigned ${data.unsigned}
              </div>
            </div>
          </div>
          <div class="grid">${rows}</div>
        </div>`;
    }

    async function handlePdf(file) {
      lastFile = file;
      fileMeta.textContent = `Checking: ${file.name} (${Math.round(file.size/1024)} KB)`;
      clearBtn.hidden = false;
      browse.disabled = true;
      result.innerHTML = `<div class="card">${currentMode === 'blank'
        ? 'Detecting blank NOC fields…'
        : 'Verifying digital signature…'}</div>`;
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
      if (currentMode === 'blank' && noc.is_amazon_noc) {
        html += renderNocForm(noc, data);
        if (noc.needs_fill) {
          if (data.signatures?.length) {
            html += `<div class="card note" style="margin-top:1rem">Amazon signature is present on this blank NOC.
              Fill the fields above, then click <strong>Fill &amp; Verify</strong>.</div>`;
          } else {
            html += `<div class="card note" style="margin-top:1rem">Fill the details above, then <strong>Fill &amp; Verify</strong>.
              If this is a Print-to-PDF copy without PKCS#7, verification will show UNSIGNED — use the original digitally signed blank for crypto verify.</div>`;
          }
        } else {
          html += renderReport(data);
        }
      } else if (currentMode === 'blank' && !noc.is_amazon_noc) {
        html += `<div class="card"><span class="badge UNSIGNED">NOT DETECTED</span>
          <p style="margin-top:0.5rem">This PDF does not appear to be a blank Amazon NOC. Try the <strong>Verify Pre-filled Signed NOC</strong> option instead, or confirm this is a supported Amazon blank format.</p></div>`;
        html += renderReport(data);
      } else {
        if (noc.is_amazon_noc && noc.needs_fill) {
          html += `<div class="card"><span class="badge MODIFIED">BLANK NOC</span>
            <p style="margin-top:0.5rem">This NOC has empty fields. Go back and use <strong>Fill Blank Signed NOC</strong> to add seller details first.</p></div>`;
        }
        html += renderReport(data);
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
      const dynMs1 = document.querySelector('[data-noc-field="ms_name"]');
      const dynMs2 = document.querySelector('[data-noc-field="ms_name_2"]');
      if (dynMs1 && dynMs2 && !dynMs2.disabled) {
        dynMs1.addEventListener('input', () => {
          if (!dynMs2.dataset.touched) dynMs2.value = dynMs1.value;
        });
        dynMs2.addEventListener('input', () => { dynMs2.dataset.touched = '1'; });
      }
    }

    function fieldValue(noc, name) {
      const f = (noc.fields || []).find(x => x.name === name);
      return f ? (f.value || '') : '';
    }

    function renderNocForm(noc, data) {
      const locked = !!noc.complete && !noc.needs_fill;
      const dis = locked ? 'disabled' : '';
      const nax = noc.template === 'amazon_nax';
      const banner = locked
        ? `<div class="locked-banner">Details already filled — fields locked. Signature verified below.</div>`
        : `<div class="fill-banner">${esc(noc.message || 'Enter details, then Fill & Verify.')}</div>`;
      const title = nax ? 'Amazon NAX blank NOC' : 'Amazon NOC merchant details';
      const hint = nax
        ? 'Date · Branch · FC address · State · M/S · M/s. · Merchant address. State is written into every state blank on the letter.'
        : 'Date · M/S · M/s. · Main place of business in Maharashtra. M/S and M/s. use the same seller name on Amazon’s form.';
      const fields = noc.fields || [];
      const inputs = fields.map((f, i) => {
        const id = 'noc_' + f.name;
        const val = esc(f.value || '');
        const ph = esc(f.label || '');
        const control = f.multiline
          ? `<textarea id="${id}" data-noc-field="${esc(f.name)}" placeholder="${ph}" ${dis}>${val}</textarea>`
          : `<input id="${id}" data-noc-field="${esc(f.name)}" type="text" placeholder="${ph}" value="${val}" ${dis} />`;
        return `<div class="field"><label for="${id}">${i + 1}) ${esc(f.label)}</label>${control}</div>`;
      }).join('');
      return `
        <div class="card noc-form">
          <h2>${title}</h2>
          <p class="hint">${hint}</p>
          ${banner}
          ${inputs}
          ${locked ? '' : `
          <div class="actions" style="justify-content:flex-start">
            <button type="button" class="success" id="fillVerifyBtn">Fill &amp; Verify signature</button>
          </div>`}
        </div>`;
    }

    async function fillAndVerify() {
      if (!lastFile) return;
      const fields = [...document.querySelectorAll('[data-noc-field]')];
      const values = {};
      for (const el of fields) values[el.dataset.nocField] = (el.value || '').trim();
      if (!values.ms_name_2) values.ms_name_2 = values.ms_name || '';
      const missing = [];
      if (!values.date) missing.push('Date');
      if (!values.ms_name) missing.push('M/S');
      if (!values.address) missing.push('Address');
      if (document.getElementById('noc_branch') && !values.branch) missing.push('Branch');
      if (document.getElementById('noc_state') && !values.state) missing.push('State');
      if (document.getElementById('noc_fc_address') && !values.fc_address) missing.push('FC address');
      if (missing.length) {
        alert('Please fill: ' + missing.join(', '));
        return;
      }
      const btn = document.getElementById('fillVerifyBtn');
      if (btn) { btn.disabled = true; btn.textContent = 'Filling & verifying…'; }
      const body = new FormData();
      body.append('pdf', lastFile);
      for (const [k, v] of Object.entries(values)) body.append(k, v);
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
    data["api_version"] = 1
    data["tool"] = f"pdf-sign-verifier/{__version__}"
    return data


@app.get("/")
def home():
    try:
        roots = trust_root_names(DEFAULT_TRUST_DIR)
        root_count = len(roots)
        inter_count = len(load_intermediate_certs(DEFAULT_TRUST_DIR))
    except Exception:
        root_count = 0
        inter_count = 0
    return render_template_string(
        PAGE, version=__version__, root_count=root_count, inter_count=inter_count
    )


def _verify_upload_to_json(upload) -> tuple[dict, int]:
    if upload is None or not upload.filename:
        return {"error": "No PDF uploaded"}, 400
    if not upload.filename.lower().endswith(".pdf"):
        return {"error": "Please upload a .pdf file"}, 400

    with tempfile.TemporaryDirectory(prefix="pdfsig-") as tmp:
        target = Path(tmp) / Path(upload.filename).name
        upload.save(target)
        noc = inspect_noc_form(target)
        report = verify_pdf(target)
        data = _report_payload(report, upload.filename, target)
        if noc.needs_fill:
            data["awaiting_fill"] = True
        return data, 200


@app.post("/api/verify")
@app.post("/api/v1/verify")
def api_verify():
    """Primary verify API (also aliased for ERP integrations)."""
    data, status = _verify_upload_to_json(request.files.get("pdf"))
    return jsonify(data), status


@app.post("/api/batch-verify")
@app.post("/api/v1/batch-verify")
def api_batch_verify():
    uploads = request.files.getlist("pdfs") or request.files.getlist("pdf")
    uploads = [u for u in uploads if u and u.filename]
    if not uploads:
        return jsonify({"error": "No PDFs uploaded"}), 400

    with tempfile.TemporaryDirectory(prefix="pdfsig-batch-") as tmp:
        paths: list[Path] = []
        for index, upload in enumerate(uploads):
            name = Path(upload.filename).name
            target = Path(tmp) / f"{index:04d}_{name}"
            upload.save(target)
            paths.append(target)
        items = verify_many(paths)
        verified = sum(1 for r in items if r.cryptographically_verified)
        unsigned = sum(1 for r in items if r.overall == "UNSIGNED")
        errors = sum(1 for r in items if r.overall == "ERROR")
        payload = {
            "api_version": 1,
            "tool": f"pdf-sign-verifier/{__version__}",
            "total": len(items),
            "verified": verified,
            "failed": len(items) - verified,
            "unsigned": unsigned,
            "errors": errors,
            "results": [r.to_dict() for r in items],
        }
        return jsonify(payload)


@app.post("/api/irn-inspect")
@app.post("/api/v1/irn-inspect")
def api_irn_inspect():
    """Optional GST IRN helper — does not affect Amazon NOC / DSC verify."""
    upload = request.files.get("pdf")
    payload = (request.form.get("payload") or request.form.get("irn") or "").strip()
    if upload and upload.filename:
        with tempfile.TemporaryDirectory(prefix="pdfsig-irn-") as tmp:
            target = Path(tmp) / Path(upload.filename).name
            upload.save(target)
            return jsonify(inspect_pdf_for_irn(target).to_dict())
    if not payload:
        return jsonify({"error": "Provide payload= IRN/QR text or pdf= file"}), 400
    if len(payload) == 64 and all(c in "0123456789abcdefABCDEF" for c in payload):
        return jsonify(verify_irn_online(payload).to_dict())
    return jsonify(inspect_text_payload(payload, source="api").to_dict())


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
    branch = (request.form.get("branch") or "").strip()
    state = (request.form.get("state") or "").strip()
    fc_address = (request.form.get("fc_address") or "").strip()

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
                branch=branch,
                state=state,
                fc_address=fc_address,
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
    print("Verify Indian DSC PDFs · Batch folder · Amazon NOC fill · optional IRN helper")
    print("API: POST /api/v1/verify  |  /api/v1/batch-verify  |  /api/v1/irn-inspect")
    app.run(host=host, port=chosen, debug=False, use_reloader=False)
