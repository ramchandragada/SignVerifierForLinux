from __future__ import annotations

import base64
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory

from . import __version__
from .authentic import (
    build_verification_report_pdf,
    is_cryptographically_verified,
)
from .batch import verify_many
from .irn_qr import inspect_pdf_for_irn, inspect_text_payload, verify_irn_online
from .noc_fields import fill_noc_form, inspect_noc_form
from .trust_store import DEFAULT_TRUST_DIR, PACKAGE_ROOT, load_intermediate_certs, trust_root_names
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
  <title>PDF Sign Verifier</title>
  <link rel="icon" type="image/png" href="/brand/app-icon.png" />
  <link rel="apple-touch-icon" href="/brand/app-icon.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,700&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --ink: #0c1628;
      --muted: #5b6a80;
      --line: #d7e0ea;
      --bg: #eef3f8;
      --panel: rgba(255, 255, 255, 0.86);
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
      --navy: #071529;
      --navy-2: #0d2348;
      --shadow: 0 18px 50px rgba(7, 21, 41, 0.08);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html, body {
      height: 100%;
      margin: 0;
    }
    body {
      font-family: "Sora", "Ubuntu", "Segoe UI", sans-serif;
      color: var(--ink);
      background: #dfe8f1;
      overflow: hidden;
    }
    .app-shell {
      height: 100vh;
      display: flex;
      flex-direction: column;
      background:
        radial-gradient(900px 420px at 8% -10%, rgba(59,110,214,0.18), transparent 55%),
        radial-gradient(700px 380px at 100% 0%, rgba(15,107,86,0.12), transparent 46%),
        linear-gradient(180deg, #e8eef6 0%, #eef3f8 42%, #e7eee9 100%);
    }
    .titlebar {
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0.78rem 1.15rem;
      background: linear-gradient(90deg, #06101f 0%, #0a1c38 55%, #0b2748 100%);
      color: #fff;
      border-bottom: 1px solid rgba(183,182,244,0.16);
      -webkit-app-region: drag;
    }
    .titlebar-text {
      min-width: 0;
      flex: 1;
    }
    .titlebar-text strong {
      display: block;
      font-size: 1.08rem;
      font-weight: 700;
      letter-spacing: -0.03em;
    }
    .titlebar-text span {
      display: block;
      margin-top: 0.12rem;
      color: #9eb0cc;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .titlebar-ver {
      font-size: 0.78rem;
      color: #d7e3f5;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 999px;
      padding: 0.28rem 0.7rem;
      -webkit-app-region: no-drag;
    }
    .aspera-logo {
      height: 36px;
      width: auto;
      max-width: 240px;
      object-fit: contain;
      object-position: left center;
      display: block;
      background: transparent;
      box-shadow: none;
      border-radius: 0;
      -webkit-app-region: no-drag;
    }
    .titlebar-back {
      -webkit-app-region: no-drag;
      padding: 0.38rem 0.85rem;
      font-size: 0.78rem;
      border-radius: 8px;
      background: rgba(255,255,255,0.10);
      color: #e8eef8;
      border: 1px solid rgba(255,255,255,0.16);
      box-shadow: none;
    }
    .titlebar-back:hover { filter: brightness(1.1); transform: none; }
    .app-body {
      flex: 1 1 auto;
      overflow: auto;
      padding: 1.15rem 1.2rem 1.3rem;
    }
    main {
      position: relative;
      width: min(1120px, 100%);
      margin: 0 auto;
      padding: 0;
    }
    .update-dialog {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 1.3rem 1.4rem;
      width: min(28rem, calc(100% - 2rem));
      box-shadow: var(--shadow);
    }
    .update-dialog::backdrop { background: rgba(16, 36, 31, 0.35); }
    .update-dialog h3 { margin: 0 0 0.45rem; font-family: "Sora", sans-serif; }
    .update-dialog p { margin: 0 0 1rem; color: var(--muted); line-height: 1.5; }
    .brand-mark {
      display: none;
      align-items: center;
      gap: 0.55rem;
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
    h1, .tagline, .hero { display: none; }
    .drop {
      position: relative;
      margin-top: 0;
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
    .drop-toolbar {
      margin-top: 1.05rem;
      display: flex;
      gap: 0.6rem;
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
    .titlebar .titlebar-back {
      -webkit-app-region: no-drag;
      padding: 0.38rem 0.85rem;
      font-size: 0.78rem;
      border-radius: 8px;
      background: rgba(255,255,255,0.10);
      color: #e8eef8;
      border: 1px solid rgba(255,255,255,0.16);
      box-shadow: none;
    }
    .titlebar .titlebar-back:hover { filter: brightness(1.1); transform: none; }
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
    .update-card { margin-top: 1.2rem; }
    .update-row {
      display: flex;
      gap: 0.7rem;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
    }
    .update-status {
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 0.45rem;
      white-space: pre-wrap;
      word-break: break-word;
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
    footer, .statusbar {
      flex: 0 0 auto;
      margin: 0;
      padding: 0.42rem 1rem;
      color: var(--muted);
      font-size: 0.78rem;
      text-align: left;
      background: #f3f6f4;
      border-top: 1px solid var(--line);
      white-space: normal;
      line-height: 1.45;
    }
    .statusbar .contributors { color: var(--ink); }
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
    .field input, .field textarea, .field select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 0.72rem 0.85rem;
      font: inherit;
      background: #fff;
      color: var(--ink);
      transition: border-color .15s, box-shadow .15s;
    }
    .field input:focus, .field textarea:focus, .field select:focus {
      outline: none;
      border-color: rgba(15,107,86,0.55);
      box-shadow: 0 0 0 3px rgba(15,107,86,0.12);
    }
    .field textarea { min-height: 4.2rem; resize: vertical; }
    .field input:disabled, .field textarea:disabled, .field select:disabled {
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
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.9rem;
      margin-top: 0;
    }
    .mode-card {
      background: var(--panel-solid);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 18px;
      padding: 1.15rem 1.1rem 1.05rem;
      cursor: pointer;
      transition: border-color .18s, box-shadow .18s, transform .18s;
      text-align: left;
      min-height: 250px;
      box-shadow: 0 10px 28px rgba(7,21,41,0.05);
      display: flex;
      flex-direction: column;
    }
    .mode-card .choose-pdf-btn {
      margin-top: auto;
      width: 100%;
      justify-content: center;
      padding: 0.62rem 1rem;
      font-size: 0.88rem;
    }
    .mode-card:hover {
      border-color: rgba(15,107,86,0.45);
      transform: translateY(-3px);
      box-shadow: 0 18px 40px rgba(7,21,41,0.12);
    }
    .mode-card h2 {
      font-family: "Sora", sans-serif;
      font-size: 1.05rem;
      margin: 0.75rem 0 0.4rem;
    }
    .mode-card p { color: var(--muted); margin: 0 0 0.85rem; font-size: 0.86rem; line-height: 1.5; flex: 1; }
    .mode-card p strong { color: var(--ink); }
    .mode-icon {
      width: 46px; height: 46px;
      border-radius: 13px;
      display: grid; place-items: center;
    }
    .welcome {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: flex-end;
      margin-bottom: 1rem;
    }
    .welcome h2 {
      margin: 0 0 0.28rem;
      font-size: 1.45rem;
      letter-spacing: -0.04em;
    }
    .welcome p { margin: 0; color: var(--muted); font-size: 0.92rem; max-width: 38rem; }
    .stat-row {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.7rem;
      margin-bottom: 1rem;
    }
    .stat {
      background: rgba(255,255,255,0.78);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 16px;
      padding: 0.85rem 0.9rem;
      box-shadow: 0 8px 22px rgba(7,21,41,0.04);
    }
    .stat b { display: block; font-size: 1.18rem; letter-spacing: -0.03em; }
    .stat span { display: block; margin-top: 0.18rem; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; }
    .insight-grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 0.9rem;
      margin-top: 1rem;
    }
    .insight {
      background: rgba(255,255,255,0.86);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 18px;
      padding: 1.1rem 1.15rem;
      box-shadow: 0 10px 28px rgba(7,21,41,0.04);
    }
    .insight h3 { margin: 0 0 0.75rem; font-size: 0.98rem; }
    .steps { margin: 0; padding: 0; list-style: none; }
    .steps li {
      display: grid;
      grid-template-columns: 28px 1fr;
      gap: 0.7rem;
      margin-bottom: 0.7rem;
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.45;
    }
    .steps li:last-child { margin-bottom: 0; }
    .num {
      width: 28px; height: 28px;
      border-radius: 50%;
      display: grid; place-items: center;
      background: var(--navy);
      color: #fff;
      font-size: 0.75rem;
      font-weight: 700;
    }
    .checks { margin: 0; padding-left: 1.1rem; color: var(--muted); font-size: 0.88rem; line-height: 1.7; }
    .tools-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.9rem;
      margin-top: 1rem;
    }
    .tools-grid .card { margin-top: 0; min-height: 150px; }
    .chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 0.16rem 0.5rem;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: var(--accent-soft);
      color: var(--accent-deep);
    }
    .work-hero {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: flex-start;
      margin-bottom: 0.9rem;
    }
    .work-kicker {
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-deep);
      margin-bottom: 0.28rem;
    }
    .work-hero h2 {
      margin: 0 0 0.28rem;
      font-size: 1.38rem;
      letter-spacing: -0.04em;
    }
    .work-hero p { margin: 0; color: var(--muted); font-size: 0.92rem; max-width: 42rem; line-height: 1.5; }
    .work-facts {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.7rem;
      margin-bottom: 0.9rem;
    }
    .work-fact {
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 14px;
      padding: 0.75rem 0.85rem;
      box-shadow: 0 8px 22px rgba(7,21,41,0.04);
    }
    .work-fact b { display: block; font-size: 0.88rem; margin-bottom: 0.18rem; }
    .work-fact span { color: var(--muted); font-size: 0.8rem; line-height: 1.4; }
    .work-grid {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 0.9rem;
      align-items: stretch;
    }
    .work-grid .drop { padding: 1.6rem 1.15rem 1.25rem; margin-top: 0; }
    .work-guide {
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 18px;
      padding: 1.1rem 1.15rem;
      box-shadow: 0 10px 28px rgba(7,21,41,0.05);
    }
    .work-guide h3 { margin: 0 0 0.7rem; font-size: 0.98rem; }
    .work-accept {
      margin-top: 0.85rem;
      padding: 0.75rem 0.8rem;
      border-radius: 12px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      font-size: 0.84rem;
      line-height: 1.45;
    }
    .work-switch {
      margin-top: 1.15rem;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 18px;
      padding: 1.05rem 1.1rem 1.15rem;
    }
    .work-switch-head h3 { margin: 0 0 0.2rem; font-size: 1rem; }
    .work-switch-head p { margin: 0 0 0.85rem; color: var(--muted); font-size: 0.86rem; }
    .switch-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.75rem;
    }
    .switch-card {
      background: #fff;
      border: 1px solid rgba(13,35,72,0.08);
      border-radius: 16px;
      padding: 0.95rem 1rem;
      text-align: left;
      box-shadow: 0 8px 20px rgba(7,21,41,0.04);
    }
    .switch-card h4 { margin: 0 0 0.35rem; font-size: 0.95rem; }
    .switch-card p { margin: 0 0 0.75rem; color: var(--muted); font-size: 0.82rem; line-height: 1.45; }
    .switch-card .drop-toolbar { margin-top: 0; justify-content: flex-start; }
    .switch-card .choose-pdf-btn { width: auto; margin-top: 0; padding: 0.55rem 0.9rem; font-size: 0.82rem; }
    @media (max-width: 900px) {
      .mode-grid, .stat-row, .insight-grid, .tools-grid, .work-grid, .work-facts, .switch-grid { grid-template-columns: 1fr; }
      .welcome, .work-hero { flex-direction: column; align-items: flex-start; }
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
  <div class="app-shell">
    <header class="titlebar">
      <img class="aspera-logo" src="/brand/aspera-logo.png" alt="Aspera" />
      <div class="titlebar-text">
        <strong>PDF Sign Verifier</strong>
        <span>Indian DSC · CCA trust · Linux</span>
      </div>
      <button type="button" class="titlebar-back" id="homeBtn" hidden>Home</button>
      <div class="titlebar-ver">{{ version }}</div>
    </header>
    <div class="app-body">
  <main>
    <div id="homeDash">
      <div class="welcome">
        <div>
          <h2>Choose a workflow</h2>
          <p>Cryptographically verify Indian DSC-signed PDFs on Linux using CCA India trust roots — no Windows, no Adobe.</p>
        </div>
        <span class="chip">Local · offline crypto</span>
      </div>
      <div class="stat-row">
        <div class="stat"><b>{{ root_count }}</b><span>CCA trust anchors</span></div>
        <div class="stat"><b>{{ inter_count }}</b><span>Licensed CA intermediates</span></div>
        <div class="stat"><b>{{ version }}</b><span>Installed version</span></div>
        <div class="stat"><b>Linux</b><span>Mint · Ubuntu · Debian</span></div>
      </div>
    </div>
    <div id="modeSelect" class="mode-grid">
      <div class="mode-card" id="modeVerify">
        <div class="mode-icon" style="background:var(--valid-bg);color:var(--valid)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:28px;height:28px"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
        </div>
        <h2>Verify Pre-filled Signed NOC</h2>
        <p>NOC already has seller details filled in. Drop the signed PDF to <strong>verify the digital signature</strong> and save with Adobe-style green tick.</p>
        <button type="button" class="choose-pdf-btn" data-mode="verify">Choose PDF</button>
      </div>
      <div class="mode-card" id="modeBlank">
        <div class="mode-icon" style="background:var(--gold-soft);color:#8a5f12">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:28px;height:28px"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
        </div>
        <h2>Fill Blank Signed NOC</h2>
        <p>NOC is blank (dotted lines / empty fields). <strong>Add seller name, date, address</strong> first, then verify the digital signature.</p>
        <button type="button" class="choose-pdf-btn" data-mode="blank">Choose PDF</button>
      </div>
      <div class="mode-card" id="modeBsa">
        <div class="mode-icon" style="background:var(--untrusted-bg);color:var(--untrusted)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:28px;height:28px"><path d="M4 4h16v16H4z"/><path d="M9 9h6"/><path d="M9 13h6"/><path d="M9 17h4"/></svg>
        </div>
        <h2>Verify BSA Agreement</h2>
        <p>Amazon Business Solutions Agreement (BSA). Drop the signed PDF to <strong>verify the digital signature</strong> — no form fill needed.</p>
        <button type="button" class="choose-pdf-btn" data-mode="bsa">Choose PDF</button>
      </div>
    </div>

    <div id="homeInfo" class="insight-grid">
      <section class="insight">
        <h3>How verification works</h3>
        <ol class="steps">
          <li><span class="num">1</span><span>Pick a workflow above. Drop the original digitally signed PDF — not a print/scan copy.</span></li>
          <li><span class="num">2</span><span>We check PKCS#7 / CMS signature bytes against CCA India roots and licensed CA intermediates.</span></li>
          <li><span class="num">3</span><span>If crypto-verified, save an Adobe-style green <strong>Signature valid</strong> stamp for upload.</span></li>
          <li><span class="num">4</span><span>Blank NOCs: type merchant details first, then verify. Address is entered manually each time.</span></li>
        </ol>
      </section>
      <section class="insight">
        <h3>What this app checks</h3>
        <ul class="checks">
          <li>Signature intact (document hash matches)</li>
          <li>Signer certificate chains to CCA India</li>
          <li>Amazon NOC and BSA agreement PDFs</li>
          <li>Batch verify for multiple pre-filled NOCs</li>
          <li>Optional GST IRN helper (separate from DSC)</li>
        </ul>
      </section>
    </div>

    <div id="workArea" hidden>
      <div class="work-hero">
        <div>
          <div class="work-kicker" id="workKicker">Workflow</div>
          <h2 id="workTitle">Verify signed PDF</h2>
          <p id="workLead">Drop the original digitally signed file. This screen stays useful while you work — switch workflows below without going home.</p>
        </div>
        <button type="button" class="secondary" id="homeBtnPage">Home</button>
      </div>
      <div class="work-facts" id="workFacts"></div>
      <div class="work-grid">
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
        <p id="dropHint">PKCS#7 / CMS check against CCA India trust roots + licensed CA intermediates.</p>
        <div class="drop-toolbar">
          <button type="button" id="browse">Choose PDF</button>
          <button type="button" class="secondary" id="clear" hidden>Clear file</button>
        </div>
        <input id="file" type="file" accept="application/pdf,.pdf" />
        <div class="meta" id="fileMeta">No file selected</div>
      </div>
      <aside class="work-guide">
        <h3>How this workflow runs</h3>
        <ol class="steps" id="guideSteps"></ol>
        <div class="work-accept" id="guideAccept"></div>
      </aside>
      </div>

      <div id="result"></div>

      <section class="work-switch">
        <div class="work-switch-head">
          <h3>Need a different workflow?</h3>
          <p>The other two options stay on this screen so you can switch without going back to Home.</p>
        </div>
        <div class="switch-grid" id="switchGrid"></div>
      </section>
    </div>

    <div id="homeTools" class="tools-grid">
    <details class="card">
      <summary style="cursor:pointer;font-weight:600">Optional: GST IRN helper</summary>
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

    <section class="card update-card">
      <div class="update-row">
        <div>
          <h2 style="margin:0">App update</h2>
          <div class="meta" style="text-align:left;margin:0.35rem 0 0">Current version: {{ version }}</div>
        </div>
        <button type="button" class="secondary" id="updateBtn">Check for update</button>
      </div>
      <div id="updateStatus" class="update-status">Ready</div>
    </section>
    </div>
    </main>

    <dialog class="update-dialog" id="updateDialog">
      <h3>Install update?</h3>
      <p id="updateDialogText">A new version is downloaded. Install now? Your computer will ask for the password.</p>
      <div class="actions" style="justify-content:flex-end;margin-top:0">
        <button type="button" class="secondary" id="updateLaterBtn">Later</button>
        <button type="button" class="success" id="updateInstallBtn">Install update</button>
      </div>
    </dialog>
    </div>
    <footer class="statusbar">PDF Sign Verifier {{ version }} · Aspera · <span class="contributors">Contributors: Vijayalaxmi Nuti, Tarun Pandal, Amar Vallakatti, Balaji Dube</span> · Trust anchors: {{ root_count }} · Intermediates: {{ inter_count }} (CCA India)</footer>
  </div>

  <script>
    const modeSelect = document.getElementById('modeSelect');
    const workArea = document.getElementById('workArea');
    const drop = document.getElementById('drop');
    const fileInput = document.getElementById('file');
    const browse = document.getElementById('browse');
    const clearBtn = document.getElementById('clear');
    const homeBtn = document.getElementById('homeBtn');
    const homeBtnPage = document.getElementById('homeBtnPage');
    const fileMeta = document.getElementById('fileMeta');
    const result = document.getElementById('result');
    const dropLabel = document.getElementById('dropLabel');
    const dropHint = document.getElementById('dropHint');
    const updateBtn = document.getElementById('updateBtn');
    const updateStatus = document.getElementById('updateStatus');
    const updateDialog = document.getElementById('updateDialog');
    const updateDialogText = document.getElementById('updateDialogText');
    const updateInstallBtn = document.getElementById('updateInstallBtn');
    const updateLaterBtn = document.getElementById('updateLaterBtn');
    let pendingUpdateVersion = '';
    let lastFile = null;
    let currentMode = '';  // 'verify' or 'blank' or 'bsa'

    const BRANCH_OPTIONS = [
      'Latur Maharashtra',
      'Solapur Maharashtra',
      'Pune Maharashtra',
      'Mumbai Maharashtra',
    ];
    const STATE_OPTIONS = [
      'Maharashtra',
      'Karnataka',
      'Tamilnadu',
    ];

    function toDateInputValue(v) {
      const raw = String(v || '').trim();
      if (!raw) return '';
      // dd/mm/yyyy -> yyyy-mm-dd
      let m = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      if (m) {
        const dd = m[1].padStart(2, '0');
        const mm = m[2].padStart(2, '0');
        return `${m[3]}-${mm}-${dd}`;
      }
      // yyyy-mm-dd already
      m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (m) return raw;
      return '';
    }

    function fromDateInputValue(v) {
      const raw = String(v || '').trim();
      const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!m) return raw;
      return `${m[3]}/${m[2]}/${m[1]}`;
    }

    function renderSelect(id, fieldName, options, current, dis) {
      const opts = options.map(o => {
        const selected = String(current || '') === o ? 'selected' : '';
        return `<option value="${esc(o)}" ${selected}>${esc(o)}</option>`;
      }).join('');
      const placeholder = `<option value="" ${current ? '' : 'selected'}>Select</option>`;
      return `<select id="${id}" data-noc-field="${esc(fieldName)}" ${dis}>${placeholder}${opts}</select>`;
    }

    const MODE_INFO = {
      verify: {
        kicker: 'Workflow 1 of 3',
        title: 'Verify Pre-filled Signed NOC',
        lead: 'Use this when seller details are already on the NOC. We check the original PKCS#7 / CMS signature against CCA India trust — then you can save an Adobe-style green tick.',
        dropLabel: 'Drop the pre-filled signed NOC / any signed PDF',
        dropHint: 'Signature is verified immediately. Select multiple files to batch-check a folder of NOCs.',
        multiple: true,
        facts: [
          ['Original signed PDF', 'Use the digitally signed file, not a print, scan, or screenshot.'],
          ['Batch ready', 'Choose several PDFs at once to verify a stack of pre-filled NOCs.'],
          ['Green tick export', 'Crypto-verified files can be saved with a Signature valid stamp.'],
        ],
        steps: [
          'Choose or drop the original signed PDF (PKCS#7 must still be inside the file).',
          'We check document hash, signer certificate, and the CCA India chain.',
          'Read the result: VALID, UNSIGNED, or a trust/integrity failure.',
          'If verified, export the Adobe-style green tick copy for upload.',
        ],
        accept: 'Best for Amazon NOCs that already have merchant name, date, and address filled in. BSA agreements belong in the BSA workflow.',
      },
      blank: {
        kicker: 'Workflow 2 of 3',
        title: 'Fill Blank Signed NOC',
        lead: 'Use this when the NOC still has dotted lines. Type seller name, date, and address first — filling does not create a signature — then we verify the original DSC.',
        dropLabel: 'Drop the blank signed NOC',
        dropHint: 'We detect blank fields so you can add seller name, date, and address — then verify.',
        multiple: false,
        facts: [
          ['Fill first', 'Merchant name, date, branch, and address go on the dotted lines.'],
          ['Address is manual', 'Type the merchant address each time. It is not copied from Branch.'],
          ['Fill ≠ signature', 'Typing details does not sign the PDF. Crypto verify still needs the original DSC.'],
        ],
        steps: [
          'Choose the original blank signed NOC (dotted placeholders still visible).',
          'Enter seller / merchant details. Address stays a manual field.',
          'Click Fill & Verify. Fields overlay the template; leftover dots are normal.',
          'Check signature status of the source file. Filling never adds a digital signature.',
        ],
        accept: 'Best for Amazon NAX-style blanks. If the NOC is already filled, switch to Verify Pre-filled instead.',
      },
      bsa: {
        kicker: 'Workflow 3 of 3',
        title: 'Verify BSA Agreement',
        lead: 'Amazon Business Solutions Agreement — signature check only. No form fill. Same CCA India cryptographic path as NOC verify.',
        dropLabel: 'Drop the signed BSA agreement PDF',
        dropHint: 'Amazon Business Solutions Agreement — digital signature verification only.',
        multiple: false,
        facts: [
          ['No form fill', 'BSA is verify-only. There are no merchant dotted fields to type.'],
          ['CCA chain', 'Signer certificate must chain to CCA India roots and licensed CAs.'],
          ['Keep the original', 'A printed or Print-to-PDF copy will show UNSIGNED.'],
        ],
        steps: [
          'Choose the original signed BSA PDF from Amazon.',
          'We inspect PKCS#7 / CMS bytes and the signer certificate chain.',
          'Review VALID vs UNSIGNED / untrusted on this screen.',
          'Export a verified copy with the green Signature valid stamp if it passes.',
        ],
        accept: 'Use this for BSA agreements only. Pre-filled or blank Amazon NOCs have their own workflows on the cards below.',
      },
    };
    const MODE_SWITCH = {
      verify: [
        { id: 'blank', title: 'Fill Blank Signed NOC', blurb: 'Dotted-line NOC. Add seller name, date, and address, then verify.' },
        { id: 'bsa', title: 'Verify BSA Agreement', blurb: 'Business Solutions Agreement. Signature check only — no fill.' },
      ],
      blank: [
        { id: 'verify', title: 'Verify Pre-filled Signed NOC', blurb: 'Details already filled. Drop the signed PDF and check the DSC.' },
        { id: 'bsa', title: 'Verify BSA Agreement', blurb: 'Business Solutions Agreement. Signature check only — no fill.' },
      ],
      bsa: [
        { id: 'verify', title: 'Verify Pre-filled Signed NOC', blurb: 'Details already filled. Drop the signed PDF and check the DSC.' },
        { id: 'blank', title: 'Fill Blank Signed NOC', blurb: 'Dotted-line NOC. Add seller name, date, and address, then verify.' },
      ],
    };

    function renderWorkChrome(mode) {
      const info = MODE_INFO[mode] || MODE_INFO.verify;
      const kicker = document.getElementById('workKicker');
      const title = document.getElementById('workTitle');
      const lead = document.getElementById('workLead');
      const facts = document.getElementById('workFacts');
      const steps = document.getElementById('guideSteps');
      const accept = document.getElementById('guideAccept');
      const grid = document.getElementById('switchGrid');
      if (kicker) kicker.textContent = info.kicker;
      if (title) title.textContent = info.title;
      if (lead) lead.textContent = info.lead;
      if (facts) {
        facts.innerHTML = info.facts.map(([name, text]) =>
          `<div class="work-fact"><b>${esc(name)}</b><span>${esc(text)}</span></div>`
        ).join('');
      }
      if (steps) {
        steps.innerHTML = info.steps.map((text, i) =>
          `<li><span class="num">${i + 1}</span><span>${esc(text)}</span></li>`
        ).join('');
      }
      if (accept) accept.textContent = info.accept;
      if (grid) {
        const others = MODE_SWITCH[mode] || [];
        grid.innerHTML = others.map(item => `
          <article class="switch-card">
            <h4>${esc(item.title)}</h4>
            <p>${esc(item.blurb)}</p>
            <div class="drop-toolbar">
              <button type="button" class="secondary" data-switch-mode="${esc(item.id)}">Open this workflow</button>
              <button type="button" class="choose-pdf-btn" data-switch-pick="${esc(item.id)}">Choose PDF</button>
            </div>
          </article>`).join('');
      }
    }

    function goHome() {
      modeSelect.hidden = false;
      workArea.hidden = true;
      if (homeBtn) homeBtn.hidden = true;
      const homeDash = document.getElementById('homeDash');
      const homeInfo = document.getElementById('homeInfo');
      const homeTools = document.getElementById('homeTools');
      if (homeDash) homeDash.hidden = false;
      if (homeInfo) homeInfo.hidden = false;
      if (homeTools) homeTools.hidden = false;
      result.innerHTML = '';
      fileInput.value = '';
      lastFile = null;
      currentMode = '';
      clearBtn.hidden = true;
      fileMeta.textContent = 'No file selected';
    }

    document.getElementById('modeVerify').addEventListener('click', () => enterMode('verify'));
    document.getElementById('modeBlank').addEventListener('click', () => enterMode('blank'));
    document.getElementById('modeBsa').addEventListener('click', () => enterMode('bsa'));
    document.querySelectorAll('#modeSelect .choose-pdf-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        enterMode(btn.getAttribute('data-mode'), true);
      });
    });
    document.getElementById('switchGrid')?.addEventListener('click', (e) => {
      const pick = e.target.closest('[data-switch-pick]');
      if (pick) {
        e.preventDefault();
        enterMode(pick.getAttribute('data-switch-pick'), true);
        return;
      }
      const open = e.target.closest('[data-switch-mode]');
      if (open) {
        e.preventDefault();
        enterMode(open.getAttribute('data-switch-mode'));
      }
    });

    function enterMode(mode, pickFile) {
      currentMode = mode;
      modeSelect.hidden = true;
      workArea.hidden = false;
      if (homeBtn) homeBtn.hidden = false;
      const homeDash = document.getElementById('homeDash');
      const homeInfo = document.getElementById('homeInfo');
      const homeTools = document.getElementById('homeTools');
      if (homeDash) homeDash.hidden = true;
      if (homeInfo) homeInfo.hidden = true;
      if (homeTools) homeTools.hidden = true;
      result.innerHTML = '';
      fileInput.value = '';
      lastFile = null;
      clearBtn.hidden = true;
      fileMeta.textContent = 'No file selected';
      const info = MODE_INFO[mode] || MODE_INFO.verify;
      dropLabel.textContent = info.dropLabel;
      dropHint.textContent = info.dropHint;
      fileInput.multiple = !!info.multiple;
      renderWorkChrome(mode);
      if (pickFile) fileInput.click();
    }

    homeBtn?.addEventListener('click', goHome);
    homeBtnPage?.addEventListener('click', goHome);

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

    updateBtn?.addEventListener('click', runAppUpdate);
    updateLaterBtn?.addEventListener('click', () => updateDialog?.close());
    updateInstallBtn?.addEventListener('click', async () => {
      updateDialog?.close();
      await installDownloadedUpdate();
    });
    checkUpdateStatus(true);

    async function checkUpdateStatus(autoStart) {
      if (!updateStatus) return;
      try {
        const res = await fetch('/api/app-update/status');
        const data = await res.json().catch(() => ({}));
        if (data.update_available) {
          updateStatus.textContent = `Update available: ${data.latest_version} (you have ${data.current_version})`;
          if (updateBtn) updateBtn.textContent = 'Download update';
          if (autoStart) await runAppUpdate();
        } else if (data.latest_version) {
          updateStatus.textContent = `Ready · latest is ${data.latest_version}`;
        }
      } catch (err) {
        /* stay on Ready if offline */
      }
    }

    async function runAppUpdate() {
      if (!updateBtn || !updateStatus) return;
      updateBtn.disabled = true;
      const original = updateBtn.textContent;
      updateBtn.textContent = 'Checking...';
      updateStatus.textContent = 'Checking for a new version...';
      try {
        const statusRes = await fetch('/api/app-update/status');
        const status = await statusRes.json().catch(() => ({}));
        if (!statusRes.ok) throw new Error(status.error || 'Could not check for update');
        if (!status.update_available) {
          updateStatus.textContent = `Already up to date (${status.current_version}).`;
          return;
        }
        updateBtn.textContent = 'Downloading...';
        updateStatus.textContent = `Downloading ${status.latest_version}...`;
        const dlRes = await fetch('/api/app-update/download', { method: 'POST' });
        const dl = await dlRes.json().catch(() => ({}));
        if (!dlRes.ok || !dl.downloaded) throw new Error(dl.error || 'Download failed');
        pendingUpdateVersion = dl.latest_version || status.latest_version || '';
        updateStatus.textContent = `${pendingUpdateVersion} downloaded. Waiting for install confirmation.`;
        if (updateDialogText) {
          updateDialogText.textContent =
            `Version ${pendingUpdateVersion} is downloaded. Install now? Your computer will ask for the password.`;
        }
        if (updateDialog?.showModal) updateDialog.showModal();
        else {
          const ok = confirm(`Version ${pendingUpdateVersion} is downloaded. Install now?`);
          if (ok) await installDownloadedUpdate();
        }
      } catch (err) {
        updateStatus.textContent = String(err.message || err);
      } finally {
        updateBtn.disabled = false;
        updateBtn.textContent = original || 'Check for update';
      }
    }

    async function installDownloadedUpdate() {
      if (!updateBtn || !updateStatus) return;
      updateBtn.disabled = true;
      updateBtn.textContent = 'Installing...';
      updateStatus.textContent = 'Password window should appear. Installing update...';
      try {
        const res = await fetch('/api/app-update/install', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        const latest = data.latest_version ? `Latest: ${data.latest_version}` : '';
        if (data.updated) {
          updateStatus.textContent = [data.message, latest, 'Please close this window and start the app again.'].filter(Boolean).join('\n');
          return;
        }
        updateStatus.textContent = [
          data.message || data.error || 'Install did not finish.',
          latest,
          data.details,
          data.command ? ('If a password window did not appear, run this in terminal:\n' + data.command) : '',
        ].filter(Boolean).join('\n\n');
      } catch (err) {
        updateStatus.textContent = String(err.message || err);
      } finally {
        updateBtn.disabled = false;
        updateBtn.textContent = 'Check for update';
      }
    }

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
      if (currentMode === 'bsa') {
        html += renderReport(data);
      } else if (currentMode === 'blank' && noc.is_amazon_noc) {
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

    function suggestPdfName(file, suffix) {
      const base = String(file && file.name ? file.name : 'document').replace(/\.pdf$/i, '');
      return base + suffix;
    }

    async function choosePdfSavePath(suggestedName) {
      if (typeof window.showSaveFilePicker !== 'function') return null;
      return window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'PDF document', accept: { 'application/pdf': ['.pdf'] } }],
      });
    }

    function showManualSaveLink(url, name) {
      let bar = document.getElementById('manualSaveBar');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'manualSaveBar';
        bar.className = 'card';
        result.insertAdjacentElement('afterbegin', bar);
      }
      bar.innerHTML = `<p><strong>Save this file:</strong> <a href="${url}" download="${esc(name)}">${esc(name)}</a>. If no window appeared, click the link or right-click and choose Save.</p>`;
    }

    async function savePdfBlob(blob, suggestedName, handle) {
      if (handle) {
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        return handle.name || suggestedName;
      }
      if (typeof window.showSaveFilePicker === 'function') {
        const picked = await window.showSaveFilePicker({
          suggestedName,
          types: [{ description: 'PDF document', accept: { 'application/pdf': ['.pdf'] } }],
        });
        const writable = await picked.createWritable();
        await writable.write(blob);
        await writable.close();
        return picked.name || suggestedName;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = suggestedName;
      a.rel = 'noopener';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      a.remove();
      try {
        const prepBody = new FormData();
        prepBody.append('file', blob, suggestedName);
        prepBody.append('name', suggestedName);
        const prep = await fetch('/api/prepare-download', { method: 'POST', body: prepBody });
        const info = await prep.json().catch(() => ({}));
        if (prep.ok && info.url) {
          let frame = document.getElementById('downloadFrame');
          if (!frame) {
            frame = document.createElement('iframe');
            frame.id = 'downloadFrame';
            frame.setAttribute('hidden', '');
            document.body.appendChild(frame);
          }
          frame.src = info.url;
          showManualSaveLink(info.url, suggestedName);
          return suggestedName;
        }
      } catch (err) {
        /* keep blob link below */
      }
      showManualSaveLink(url, suggestedName);
      return suggestedName;
    }

    result.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn || btn.disabled) return;
      const action = btn.getAttribute('data-action');
      if (action === 'export-verified') {
        e.preventDefault();
        exportVerifiedNoc();
      } else if (action === 'download-report') {
        e.preventDefault();
        downloadReport();
      } else if (action === 'fill-verify') {
        e.preventDefault();
        fillAndVerify();
      }
    });

    function wireButtons(data) {
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
      let banner = `<div class="fill-banner">${esc(noc.message || 'Enter details, then Fill & Verify.')}</div>`;
      if (locked) {
        if (data.cryptographically_verified) {
          banner = `<div class="locked-banner">Details already filled — fields locked. Signature verified below.</div>`;
                    } else if (data.source_overall === 'UNSIGNED') {
                      banner = `<div class="fill-banner">Details already filled — fields locked. Source blank PDF is UNSIGNED, so it cannot be cryptographically verified after filling.</div>`;
        } else if (data.overall === 'UNSIGNED') {
          banner = `<div class="fill-banner">Details already filled — fields locked. This file currently has no digital signature (UNSIGNED).</div>`;
        } else {
          banner = `<div class="fill-banner">Details already filled — fields locked. Verification status: ${esc(data.overall || 'UNKNOWN')}.</div>`;
        }
      }
      const title = nax ? 'Amazon NAX blank NOC' : 'Amazon NOC merchant details';
      const hint = nax
        ? 'Date (calendar) · Branch (dropdown) · State (dropdown) · M/S · M/s. · Merchant address is typed each time. FC address is pre-printed on the NOC.'
        : 'Date · M/S · M/s. · Main place of business in Maharashtra. M/S and M/s. use the same seller name on Amazon’s form.';
      const fields = noc.fields || [];
      const inputs = fields.map((f, i) => {
        const id = 'noc_' + f.name;
        const val = esc(f.value || '');
        const ph = esc(f.label || '');
        let control = '';
        if (nax && f.name === 'date') {
          control = `<input id="${id}" data-noc-field="${esc(f.name)}" type="date" value="${esc(toDateInputValue(f.value))}" ${dis} />`;
        } else if (nax && f.name === 'branch') {
          control = renderSelect(id, f.name, BRANCH_OPTIONS, f.value || '', dis);
        } else if (nax && f.name === 'state') {
          control = renderSelect(id, f.name, STATE_OPTIONS, f.value || '', dis);
        } else if (f.name === 'address' || f.multiline) {
          const addrPh = f.name === 'address' ? 'Type merchant place of business (new address each time)' : ph;
          control = `<textarea id="${id}" data-noc-field="${esc(f.name)}" placeholder="${esc(addrPh)}" ${dis}>${val}</textarea>`;
        } else {
          control = `<input id="${id}" data-noc-field="${esc(f.name)}" type="text" placeholder="${ph}" value="${val}" ${dis} />`;
        }
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
            <button type="button" class="success" data-action="fill-verify">Fill &amp; Verify signature</button>
          </div>`}
        </div>`;
    }

    async function fillAndVerify() {
      if (!lastFile) {
        alert('No PDF is loaded. Choose a blank signed NOC first.');
        return;
      }
      const fields = [...document.querySelectorAll('[data-noc-field]')];
      const values = {};
      for (const el of fields) {
        const key = el.dataset.nocField;
        let val = (el.value || '').trim();
        if (key === 'date' && el.type === 'date') {
          val = fromDateInputValue(val);
        }
        values[key] = val;
      }
      if (!values.ms_name_2) values.ms_name_2 = values.ms_name || '';
      const missing = [];
      if (!values.date) missing.push('Date');
      if (!values.ms_name) missing.push('M/S');
      if (!values.address) missing.push('Address');
      if (document.getElementById('noc_branch') && !values.branch) missing.push('Branch');
      if (document.getElementById('noc_state') && !values.state) missing.push('State');
      // FC address removed — pre-printed on every NOC
      if (missing.length) {
        alert('Please fill: ' + missing.join(', '));
        return;
      }
      const btn = document.querySelector('[data-action="fill-verify"]');
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
          const filledName = data.filled_file_name || suggestPdfName(lastFile, '_filled.pdf');
          lastFile = new File([bytes], filledName, { type: 'application/pdf' });
          fileMeta.textContent = `Filled: ${filledName} (${Math.round(lastFile.size/1024)} KB)`;
          try {
            await savePdfBlob(lastFile, filledName, null);
          } catch (saveErr) {
            if (!(saveErr && saveErr.name === 'AbortError')) throw saveErr;
          }
        }
        renderAll(data);
        if (data.overall === 'UNSIGNED' && data.source_overall === 'UNSIGNED') {
          alert('Filled successfully, but the source blank PDF has no digital signature. Use the original Amazon-signed blank PDF for cryptographic verification.');
        }
      } catch (err) {
        alert(err.message);
        if (btn) { btn.disabled = false; btn.textContent = 'Fill & Verify signature'; }
      }
    }

    async function exportVerifiedNoc() {
      if (!lastFile) {
        alert('No PDF is loaded. Choose a PDF first, then save.');
        return;
      }
      const suggested = suggestPdfName(lastFile, '_Signature_valid.pdf');
      let handle = null;
      try {
        handle = await choosePdfSavePath(suggested);
      } catch (err) {
        if (err && err.name === 'AbortError') return;
      }
      const btn = document.querySelector('[data-action="export-verified"]');
      if (btn) { btn.disabled = true; btn.textContent = 'Creating verified PDF…'; }
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
        const name = match && match[1] ? match[1] : suggested;
        const saved = await savePdfBlob(blob, name, handle);
        fileMeta.textContent = 'Saved: ' + saved;
      } catch (err) {
        if (err && err.name === 'AbortError') return;
        alert(err.message || String(err));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save verified PDF (green Signature valid)'; }
      }
    }

    async function downloadReport() {
      if (!lastFile) {
        alert('No PDF is loaded. Choose a PDF first, then save the report.');
        return;
      }
      const suggested = suggestPdfName(lastFile, '_verification_report.pdf');
      let handle = null;
      try {
        handle = await choosePdfSavePath(suggested);
      } catch (err) {
        if (err && err.name === 'AbortError') return;
      }
      const btn = document.querySelector('[data-action="download-report"]');
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
        const name = match && match[1] ? match[1] : suggested;
        const saved = await savePdfBlob(blob, name, handle);
        fileMeta.textContent = 'Saved: ' + saved;
      } catch (err) {
        if (err && err.name === 'AbortError') return;
        alert(err.message || String(err));
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
                <button type="button" class="success" data-action="export-verified">Save verified PDF (green Signature valid)</button>
                <button type="button" class="secondary" data-action="download-report">Download verification report (audit only)</button>
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


def _parse_version_tuple(text: str) -> tuple[int, ...]:
    raw = (text or "").strip().lower().lstrip("v")
    nums: list[int] = []
    for part in raw.split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums or [0])


def _latest_deb_release() -> dict:
    api = "https://api.github.com/repos/ramchandragada/SignVerifierForLinux/releases/latest"
    req = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "pdf-sign-verifier",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    assets = payload.get("assets") or []
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.endswith(".deb") and "amd64" in name:
            return {
                "tag": str(payload.get("tag_name") or ""),
                "version": name.split("_")[1] if "_" in name else str(payload.get("tag_name") or ""),
                "url": str(asset.get("browser_download_url") or ""),
                "asset_name": name,
            }
    raise RuntimeError("No amd64 .deb asset found in latest release")


UPDATE_DEB_PATH = Path("/var/tmp/pdf-sign-verifier-latest.deb")


def _manual_update_command(deb_path: Path | None = None) -> str:
    path = deb_path or UPDATE_DEB_PATH
    return f"sudo apt install -y {path}"


def _sudo_auth_required(output: str) -> bool:
    text = (output or "").lower()
    needles = (
        "password is required",
        "a password is required",
        "a terminal is required",
        "no tty",
        "authentication",
        "not in the sudoers",
        "permission denied",
        "polkit",
        "not authorized",
        "dismissed",
        "cancelled",
        "canceled",
    )
    return any(n in text for n in needles)


def _run_install(deb_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    apt_get = shutil.which("apt-get") or "/usr/bin/apt-get"
    attempts: list[list[str]] = [["sudo", "-n", apt_get, "install", "-y", str(deb_path)]]
    pkexec = shutil.which("pkexec")
    if pkexec:
        attempts.append([pkexec, apt_get, "install", "-y", str(deb_path)])
    last = subprocess.CompletedProcess(attempts[0], 1, "", "install not attempted")
    for cmd in attempts:
        last = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
        if last.returncode == 0:
            return last
    return last


def _static_dir() -> Path:
    here = Path(__file__).resolve().parent / "static"
    if here.is_dir():
        return here
    return PACKAGE_ROOT / "static"


@app.get("/brand/aspera-logo.png")
def aspera_logo():
    return send_from_directory(_static_dir(), "aspera-logo.png", mimetype="image/png")


@app.get("/brand/aspera-logo.svg")
def aspera_logo_svg():
    return send_from_directory(_static_dir(), "aspera-logo.svg", mimetype="image/svg+xml")


@app.get("/brand/app-icon.png")
def app_icon_png():
    return send_from_directory(_static_dir(), "app-icon.png", mimetype="image/png")


@app.get("/brand/app-icon.svg")
def app_icon_svg():
    return send_from_directory(_static_dir(), "app-icon.svg", mimetype="image/svg+xml")


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


@app.get("/api/app-update/status")
def api_app_update_status():
    try:
        latest = _latest_deb_release()
    except Exception as exc:
        return jsonify({"error": f"Could not check latest release: {exc}"}), 500
    current = _parse_version_tuple(__version__)
    latest_v = _parse_version_tuple(latest["version"])
    return jsonify(
        {
            "current_version": __version__,
            "latest_version": latest["version"],
            "update_available": latest_v > current,
        }
    )


@app.post("/api/app-update/download")
def api_app_update_download():
    try:
        latest = _latest_deb_release()
    except Exception as exc:
        return jsonify({"error": f"Could not check latest release: {exc}"}), 500

    current = _parse_version_tuple(__version__)
    latest_v = _parse_version_tuple(latest["version"])
    if latest_v <= current:
        return jsonify(
            {
                "downloaded": False,
                "update_available": False,
                "message": f"Already up to date ({__version__}).",
                "latest_version": latest["version"],
            }
        )

    req = urllib.request.Request(
        latest["url"],
        headers={"User-Agent": "pdf-sign-verifier"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            UPDATE_DEB_PATH.write_bytes(resp.read())
        UPDATE_DEB_PATH.chmod(0o644)
    except Exception as exc:
        return jsonify({"error": f"Download failed: {exc}"}), 500
    return jsonify(
        {
            "downloaded": True,
            "latest_version": latest["version"],
            "path": str(UPDATE_DEB_PATH),
            "message": f"Downloaded {latest['version']}. Ready to install.",
        }
    )


@app.post("/api/app-update/install")
def api_app_update_install():
    if not UPDATE_DEB_PATH.is_file():
        return jsonify({"error": "No downloaded update found. Download first."}), 400
    try:
        latest = _latest_deb_release()
        latest_version = latest["version"]
    except Exception:
        latest_version = ""

    try:
        proc = _run_install(UPDATE_DEB_PATH)
    except Exception as exc:
        return jsonify(
            {
                "updated": False,
                "requires_admin": True,
                "message": f"Could not start installer: {exc}",
                "command": _manual_update_command(),
                "latest_version": latest_version,
            }
        )

    if proc.returncode == 0:
        return jsonify(
            {
                "updated": True,
                "message": f"Updated successfully to {latest_version or 'the latest version'}.",
                "latest_version": latest_version,
            }
        )

    combined = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    return jsonify(
        {
            "updated": False,
            "requires_admin": True,
            "message": (
                "A password window should appear so the update can install. "
                "If it did not, the package is already downloaded — run the command below."
            ),
            "details": combined[:1200],
            "command": _manual_update_command(),
            "latest_version": latest_version,
        }
    )


@app.post("/api/app-update")
def api_app_update():
    """Back-compat: check only. UI now uses download then install."""
    return api_app_update_status()


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
        source_report = verify_pdf(source)
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
        source_data = _report_payload(source_report, Path(upload.filename).name, source)
        data["source_overall"] = source_data.get("overall")
        data["source_cryptographically_verified"] = source_data.get("cryptographically_verified", False)
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


_PREPARED_DOWNLOADS: dict[str, tuple[bytes, str, float]] = {}


def _safe_download_name(name: str) -> str:
    raw = Path(name or "download.pdf").name
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in " ._-+()")[:180].strip()
    if not cleaned:
        cleaned = "download.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned


def _purge_prepared_downloads() -> None:
    now = time.time()
    for token, item in list(_PREPARED_DOWNLOADS.items()):
        if now - item[2] > 180:
            _PREPARED_DOWNLOADS.pop(token, None)


@app.post("/api/prepare-download")
def api_prepare_download():
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "No file to save"}), 400
    _purge_prepared_downloads()
    token = uuid.uuid4().hex
    name = _safe_download_name(request.form.get("name") or upload.filename or "download.pdf")
    _PREPARED_DOWNLOADS[token] = (upload.read(), name, time.time())
    return jsonify({"url": f"/api/prepared-download/{token}", "name": name})


@app.get("/api/prepared-download/<token>")
def api_prepared_download(token: str):
    item = _PREPARED_DOWNLOADS.pop(token, None)
    if item is None:
        return jsonify({"error": "Save link expired. Click the button again."}), 404
    data, name, _ts = item
    return Response(
        data,
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


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


_APP_CACHE = Path.home() / ".cache" / "pdf-sign-verifier-app"
_STATE_DIR = Path.home() / ".cache" / "pdf-sign-verifier"
_INSTANCE_LOCK_FP = None
_WM_CLASS = "PDFSignVerifier"


def _try_acquire_instance_lock() -> bool:
    """Keep a single app process. The lock is released when this process exits."""
    global _INSTANCE_LOCK_FP
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    fp = open(_STATE_DIR / "instance.lock", "a+", encoding="utf-8")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        return False
    fp.seek(0)
    fp.truncate()
    fp.write(str(os.getpid()))
    fp.flush()
    _INSTANCE_LOCK_FP = fp
    return True


def _write_instance_port(port: int) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    (_STATE_DIR / "port").write_text(str(port), encoding="utf-8")


def _read_instance_port(default: int) -> int:
    try:
        return int((_STATE_DIR / "port").read_text(encoding="utf-8").strip())
    except Exception:
        return default


def _run_quiet(args: list[str]) -> bool:
    if not shutil.which(args[0]):
        return False
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def _app_window_open() -> bool:
    if shutil.which("wmctrl"):
        try:
            listing = subprocess.check_output(["wmctrl", "-lx"], text=True, errors="ignore")
        except Exception:
            listing = ""
        for line in listing.splitlines():
            low = line.lower()
            if _WM_CLASS.lower() in low or "pdf sign verifier" in low:
                return True
    if shutil.which("xdotool"):
        found = subprocess.run(
            ["xdotool", "search", "--class", _WM_CLASS],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if found.returncode == 0:
            return True
    try:
        listing = subprocess.check_output(["ps", "-eo", "args"], text=True, errors="ignore")
        return any(
            "pdf-sign-verifier-app" in line and "--app=" in line
            for line in listing.splitlines()
        )
    except Exception:
        return False


def _raise_and_maximize_window() -> bool:
    raised = (
        _run_quiet(["wmctrl", "-xa", _WM_CLASS])
        or _run_quiet(["wmctrl", "-a", "PDF Sign Verifier"])
        or _run_quiet(["xdotool", "search", "--class", _WM_CLASS, "windowactivate"])
    )
    _run_quiet(
        ["wmctrl", "-x", "-r", _WM_CLASS, "-b", "add,maximized_vert,maximized_horz"]
    )
    _run_quiet(
        ["wmctrl", "-r", "PDF Sign Verifier", "-b", "add,maximized_vert,maximized_horz"]
    )
    return raised


def _maximize_when_ready(timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _app_window_open():
            _raise_and_maximize_window()
            return
        time.sleep(0.2)


def _activate_existing_instance(host: str, preferred_port: int) -> None:
    port = _read_instance_port(preferred_port)
    url = f"http://{host}:{port}/"
    if _app_window_open():
        _raise_and_maximize_window()
        print("PDF Sign Verifier is already running — existing window brought to the front.")
        return
    try:
        urllib.request.urlopen(url, timeout=0.6)
        server_up = True
    except Exception:
        server_up = False
    if server_up and _open_chrome_app_window(url):
        threading.Thread(target=_maximize_when_ready, daemon=True).start()
        print("PDF Sign Verifier is already running — reopened the app window.")
        return
    _raise_and_maximize_window()
    print("PDF Sign Verifier is already running.")


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


def _wait_for_server(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.4)
            return
        except Exception:
            time.sleep(0.12)


def _open_chrome_app_window(url: str) -> subprocess.Popen | None:
    profile = _APP_CACHE
    profile.mkdir(parents=True, exist_ok=True)
    binaries = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
        "brave-browser",
    )
    for name in binaries:
        path = shutil.which(name)
        if not path:
            continue
        return subprocess.Popen(
            [
                path,
                f"--app={url}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--class=PDFSignVerifier",
                "--start-maximized",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return None


def _open_webview(url: str) -> bool:
    try:
        import webview
    except Exception:
        return False
    try:
        webview.create_window(
            "PDF Sign Verifier",
            url,
            width=1400,
            height=900,
            min_size=(880, 620),
            maximized=True,
        )
        webview.start()
        return True
    except Exception:
        return False


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if not _try_acquire_instance_lock():
        _activate_existing_instance(host, port)
        return

    chosen = _pick_port(host, port)
    _write_instance_port(chosen)
    url = f"http://{host}:{chosen}/"
    print(f"PDF Sign Verifier {__version__}")
    if chosen != port:
        print(f"Port {port} is busy — using {chosen} instead.")
    print(f"App: {url}")
    print("Keep this terminal open while the app is running.")

    if open_browser:
        def _launch() -> None:
            _wait_for_server(url)
            if _open_chrome_app_window(url):
                _maximize_when_ready()
                return
            webbrowser.open(url)

        threading.Timer(0.35, _launch).start()

    # Flask must stay on the main thread. If it runs as a daemon and the
    # window process exits, the server dies and the UI shows connection refused.
    app.run(host=host, port=chosen, debug=False, use_reloader=False, threaded=True)
