#!/usr/bin/env python3
# CyNiT Tools — DCBaaS API (DEV / T&I / PROD) — OneClick + Postman Runner
#
# Web tool voor CyNiT Tools hub:
# - /dcbaas-api              : UI
# - /dcbaas-api/connect      : JWT->access_token (per environment)
# - /dcbaas-api/run          : Postman request runner
# - /dcbaas-api/app          : application acties (add/update/delegate/delete/health)
# - /dcbaas-api/cert/add     : certificate add (CSR paste/upload)
#
# Vereist:
#   pip install requests pyjwt cryptography jwcrypto
#
# Integreer in ctools.py via:
#   import dcbaas_api
#   dcbaas_api.register_web_routes(app, SETTINGS, TOOLS)
#
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, Flask, request, render_template_string

import cynit_layout
import cynit_theme

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from jwcrypto import jwk

# -------------------- Postman parsing --------------------

_VAR_RE = re.compile(r"{{\s*([^}]+?)\s*}}")

@dataclass
class PMRequest:
    key: str               # unieke key (folderpad + name)
    name: str              # display name (zonder folder prefix)
    folder: List[str]      # folder stack
    depth: int             # folder depth
    method: str
    url_raw: str
    headers: List[Dict[str, str]]
    body_mode: str
    body_raw: str
    body_urlencoded: List[Dict[str, Any]]

def _apply_vars(text: str, variables: Dict[str, str]) -> str:
    if not text:
        return ""
    def repl(m):
        key = m.group(1).strip()
        return variables.get(key, m.group(0))
    return _VAR_RE.sub(repl, text)

def _safe_json_pretty(text: str) -> str:
    try:
        obj = json.loads(text)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return text

def _load_collection(path: Path) -> Tuple[str, List[PMRequest], List[str]]:
    """
    Laadt een Postman collection (v2.1). Ondersteunt nested folders.
    Returns:
      (collection_name, requests, variables_found)
    """
    if not path.exists():
        return ("(collection niet gevonden)", [], [])

    data = json.loads(path.read_text(encoding="utf-8"))
    info = data.get("info", {}) or {}
    name = info.get("name") or path.stem

    reqs: List[PMRequest] = []
    vars_found: set[str] = set()

    def walk(items: List[dict], folder_stack: List[str]) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue

            # Folder?
            if "item" in it and isinstance(it.get("item"), list):
                fname = (it.get("name") or "Folder").strip()
                walk(it["item"], folder_stack + [fname])
                continue

            r = it.get("request") or {}
            if not r:
                continue

            method = (r.get("method") or "GET").upper()
            url = r.get("url") or {}
            url_raw = url.get("raw") or ""
            headers = r.get("header") or []
            body = r.get("body") or {}
            body_mode = body.get("mode") or ""
            body_raw = body.get("raw") or ""
            body_urlencoded = body.get("urlencoded") or []

            # vars detectie
            for s in [
                url_raw,
                json.dumps(headers, ensure_ascii=False),
                body_raw,
                json.dumps(body_urlencoded, ensure_ascii=False),
            ]:
                for m in _VAR_RE.findall(s or ""):
                    vars_found.add(m.strip())

            display = (it.get("name") or "(unnamed)").strip()
            folder_txt = " / ".join(folder_stack)
            key = f"{folder_txt} :: {display}" if folder_txt else display

            reqs.append(
                PMRequest(
                    key=key,
                    name=display,
                    folder=folder_stack,
                    depth=len(folder_stack),
                    method=method,
                    url_raw=url_raw,
                    headers=[
                        {"key": h.get("key", ""), "value": h.get("value", "")}
                        for h in headers
                        if isinstance(h, dict)
                    ],
                    body_mode=body_mode,
                    body_raw=body_raw,
                    body_urlencoded=body_urlencoded if isinstance(body_urlencoded, list) else [],
                )
            )

    walk(data.get("item", []) or [], [])

    # "bekende" variabelen die we in de UI automatisch invullen
    for d in ["url", "DCB TOKEN", "Origin"]:
        vars_found.add(d)

    # sorteer op folderpad + requestnaam
    reqs.sort(key=lambda r: ("/".join(r.folder).lower(), r.name.lower(), r.method))
    return (name, reqs, sorted(vars_found, key=lambda x: x.lower()))

def _headers_to_dict(headers: List[Dict[str, str]], variables: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in headers:
        k = (h.get("key") or "").strip()
        v = (h.get("value") or "")
        if not k:
            continue
        out[k] = _apply_vars(v, variables)
    return out

def _build_body(pm: PMRequest, variables: Dict[str, str]) -> Tuple[Optional[str], Optional[Dict[str, str]], Optional[str]]:
    mode = (pm.body_mode or "").lower()
    if mode == "urlencoded":
        form: Dict[str, str] = {}
        for kv in pm.body_urlencoded:
            if not isinstance(kv, dict):
                continue
            if kv.get("disabled"):
                continue
            k = str(kv.get("key") or "").strip()
            if not k:
                continue
            v = str(kv.get("value") or "")
            form[k] = _apply_vars(v, variables)
        return (None, form, "application/x-www-form-urlencoded")
    if mode == "raw":
        raw = _apply_vars(pm.body_raw or "", variables)
        return (raw, None, None)
    return (None, None, None)

# -------------------- Auth helpers (JWT -> access_token) --------------------

def _load_private_key_from_upload(filename: str, data: bytes, password: Optional[str]) -> Any:
    """
    Ondersteunt:
      - .jwk/.json: jwcrypto JWK
      - .pem/.key : PEM private key
      - .pfx/.p12 : PKCS#12 met private key
    """
    ext = (Path(filename).suffix or "").lower()
    pwd = password.encode("utf-8") if password else None

    if ext in [".jwk", ".json"]:
        data_text = data.decode("utf-8", errors="replace")
        key = jwk.JWK.from_json(data_text)
        pem_key_bytes = key.export_to_pem(private_key=True, password=None)
        return load_pem_private_key(pem_key_bytes, password=None)

    if ext in [".pem", ".key"]:
        return load_pem_private_key(data, password=pwd)

    if ext in [".pfx", ".p12"]:
        key, _cert, _addl = load_key_and_certificates(data, pwd)
        if key is None:
            raise ValueError("Geen private key gevonden in PKCS#12.")
        return key

    raise ValueError("Onbekend sleuteltype. Gebruik .jwk/.json, .pem/.key of .pfx/.p12")

def _build_jwt(iss_sub: str, aud: str, key, alg: str = "RS256", kid: Optional[str] = None, exp_offset: int = 300) -> str:
    now = int(time.time())
    claims = {"iss": iss_sub, "sub": iss_sub, "aud": aud, "iat": now, "exp": now + int(exp_offset)}
    headers = {"typ": "JWT", "alg": alg}
    if kid:
        headers["kid"] = kid
    return jwt.encode(payload=claims, key=key, algorithm=alg, headers=headers)

def _request_access_token(token_url: str, jwt_token: str, audience: str, timeout: int = 30) -> str:
    """
    OAuth2 client_credentials met client_assertion (JWT bearer).
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": jwt_token,
        "audience": audience,
    }
    resp = requests.post(token_url, headers=headers, data=data, timeout=timeout)
    resp.raise_for_status()
    j = resp.json()
    return j.get("access_token", "") or ""

# -------------------- HTTP request runner --------------------

def _parse_headers_text(txt: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in (txt or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out

def _do_request(method: str, url: str, headers: Dict[str, str], body_text: str, timeout: int = 60) -> Dict[str, Any]:
    """
    Voert de request uit. Body kan JSON, form lines (k=v) of raw text zijn.
    Retourneert een dict (ok/status/elapsed_ms/headers/body).
    """
    data = None
    json_payload = None

    if body_text and body_text.strip():
        # JSON?
        try:
            json_payload = json.loads(body_text)
        except Exception:
            # Form? (k=v per lijn)
            if "\n" in body_text and "=" in body_text and "{" not in body_text and "[" not in body_text:
                form: Dict[str, str] = {}
                for line in body_text.splitlines():
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    form[k.strip()] = v.strip()
                data = form
            else:
                data = body_text.encode("utf-8")

    t0 = time.time()
    try:
        resp = requests.request(method=method, url=url, headers=headers, json=json_payload, data=data, timeout=timeout)
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "ok": bool(resp.ok),
            "status": f"{resp.status_code} {resp.reason}",
            "elapsed_ms": elapsed_ms,
            "headers": "\n".join([f"{k}: {v}" for k, v in resp.headers.items()]),
            "body": _safe_json_pretty(resp.text),
        }
    except Exception as e:
        return {"ok": False, "status": "REQUEST FAILED", "elapsed_ms": -1, "headers": "", "body": str(e)}

# -------------------- CSR helpers --------------------

def _csr_to_b64(csr_text: str, csr_file) -> str:
    """
    CSR input:
      - upload: base64(filebytes)
      - paste PEM: strip header/footer + whitespace
      - paste base64/DER: strip whitespace
    """
    if csr_file and getattr(csr_file, "filename", ""):
        b = csr_file.read()
        return base64.b64encode(b).decode("utf-8")

    t = (csr_text or "").strip()
    if not t:
        return ""

    if "BEGIN" in t and "CERTIFICATE REQUEST" in t:
        lines = [ln.strip() for ln in t.splitlines() if ln and "BEGIN" not in ln and "END" not in ln]
        return "".join(lines)

    return re.sub(r"\s+", "", t)

# -------------------- Config + state --------------------

bp = Blueprint("dcbaas_api", __name__)

STATE: Dict[str, Any] = {
    "tokens": {},        # env_id -> token
    "last_resp": None,   # laatst uitgevoerde request (runner/apps/certs)
    "last_auth": None,   # connect status
    "last_smoke": None,  # smoke result
}

TEMPLATES = [
    "SSL Server",
    "SSL Client",
    "SSL Signing",
    "SSL Client + Signing",
    "Machine Authenticatie",
    "ECC Client + Signing",
    "Andere",
]

def _cfg_path() -> Path:
    return Path(__file__).parent / "config" / "dcbaas_api.json"

def _default_cfg() -> Dict[str, Any]:
    return {
        "defaults": {
            "origin": "localhost",
            "iss_sub": "",
            "kid": "",
            "alg": "RS256",
            "exp_offset": 300,
        },
        "environments": {
            "DEV": {
                "label": "DEV",
                "base_url": "https://extapi.dcb-dev.vlaanderen.be",
                "api_prefix": "/dev",
                "token_url": "https://authenticatie-ti.vlaanderen.be/op/v1/token",
                "jwt_aud": "https://authenticatie-ti.vlaanderen.be/op",
                "token_audience": "",
            },
            "TI": {
                "label": "T&I",
                "base_url": "https://extapi.dcb-ti.vlaanderen.be",
                "api_prefix": "/ti",
                "token_url": "https://authenticatie-ti.vlaanderen.be/op/v1/token",
                "jwt_aud": "https://authenticatie-ti.vlaanderen.be/op",
                "token_audience": "",
            },
            "PROD": {
                "label": "PROD",
                "base_url": "https://extapi.dcb.vlaanderen.be",
                "api_prefix": "/prod",
                "token_url": "https://authenticatie.vlaanderen.be/op/v1/token",
                "jwt_aud": "https://authenticatie.vlaanderen.be/op",
                "token_audience": "",
            },
        },
        # Zet hier je collection neer (binnen je repo is dit typisch config/dcbaas_postman_collection.json)
        "postman_collection_path": "config/dcbaas_postman_collection.json",
        # Health endpoint voor smoke test
        "health_path": "/health",
    }

def load_cfg() -> Dict[str, Any]:
    p = _cfg_path()
    cfg = _default_cfg()
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                if isinstance(user.get("defaults"), dict):
                    cfg["defaults"].update(user["defaults"])
                if isinstance(user.get("environments"), dict):
                    cfg["environments"].update(user["environments"])
                if user.get("postman_collection_path"):
                    cfg["postman_collection_path"] = user["postman_collection_path"]
                if user.get("health_path"):
                    cfg["health_path"] = user["health_path"]
        except Exception:
            pass
    return cfg

def _env(cfg: Dict[str, Any], env_id: str) -> Dict[str, Any]:
    envs = cfg.get("environments", {}) or {}
    return envs.get(env_id) or envs.get("DEV") or {}

def _persist_cfg(cfg: Dict[str, Any]) -> None:
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

# -------------------- UI --------------------

TEMPLATE = r"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>CyNiT - DCBaaS API</title>
  <style>
    {{ base_css|safe }}
    .wrap { display: grid; grid-template-columns: 420px 1fr; gap: 14px; }
    .panel { background:#0b0b0b; border:1px solid #222; border-radius:16px; padding:12px; box-shadow:0 10px 26px rgba(0,0,0,0.55); }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; }
    .tab { padding:6px 12px; border-radius:999px; border:1px solid #333; background:#070707; cursor:pointer; text-decoration:none; display:inline-block; }
    .tab.active { background:#151515; border-color:#444; }
    input[type=text], input[type=password], textarea, select {
      width:100%; border-radius:12px; border:1px solid #333; background:#060606; color: {{ colors.general_fg }};
      padding:10px; font-family:Consolas, monospace; box-sizing:border-box;
    }
    textarea { min-height:140px; resize:vertical; }
    .row2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .btn { display:inline-block; border:none; border-radius:999px; padding:8px 14px; background: {{ colors.button_bg }}; color: {{ colors.button_fg }};
      font-weight:700; cursor:pointer; border:1px solid #333; box-shadow:0 8px 18px rgba(0,0,0,0.5); }
    .btn:hover { filter:brightness(1.08); }
    .btn2 { background:#111; color: {{ colors.general_fg }}; }
    .danger { background:#2a0b0b; border-color:#5a1f1f; }
    .tag { display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid #333; font-size:0.82rem; margin-right:6px; }
    .muted { color:#aaa; font-size:0.9em; }
    pre { white-space:pre-wrap; word-wrap:break-word; background:#050505; border:1px solid #222; border-radius:16px; padding:10px; overflow:auto; max-height:460px; }
    .reqlist a{ display:block; padding:8px 10px; border-radius:12px; text-decoration:none; border:1px solid transparent; margin-bottom:6px; background:#080808; }
    .reqlist a:hover{ border-color:#333; background:#111; }
    .reqlist a.active{ border-color:#444; background:#151515; }
    .ok { color:#86efac; } .err { color:#fecaca; }
    .small { font-size:0.85em; }
    .indent { opacity:0.95; }
    .indent .dot { opacity:0.35; }
    .pill { display:inline-block; padding:3px 10px; border-radius:999px; border:1px solid #333; background:#0a0a0a; }
  </style>
  <script>
    {{ common_js|safe }}
    function setTab(name) {
      const u = new URL(window.location.href);
      u.searchParams.set("tab", name);
      window.location.href = u.toString();
    }
    async function copyId(id) {
      const el = document.getElementById(id);
      if (!el) return;
      const txt = el.value || el.textContent || "";
      try { await navigator.clipboard.writeText(txt); } catch(e) {}
    }
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <h1>DCBaaS API</h1>
    <p class="muted">
      Eén pagina voor: <span class="pill">DEV / T&I / PROD</span> + <span class="pill">JWT → token</span> +
      <span class="pill">Postman Runner (nested folders)</span> + <span class="pill">Apps</span> + <span class="pill">Certs</span> +
      <span class="pill">Connect & Run Health</span>.
    </p>

    <div class="wrap">
      <div class="panel">
        <h2>Connect</h2>

        <form method="post" action="{{ url_for('dcbaas_api.connect') }}" enctype="multipart/form-data">
          <label><strong>Environment</strong></label>
          <select name="env_id">
            {% for k, e in envs.items() %}
              <option value="{{k}}" {% if k==env_id %}selected{% endif %}>{{ e.label }}</option>
            {% endfor %}
          </select>

          <div class="row2" style="margin-top:10px;">
            <div><label><strong>Base URL</strong></label><input type="text" name="base_url" value="{{ env.base_url }}"></div>
            <div><label><strong>API prefix</strong></label><input type="text" name="api_prefix" value="{{ env.api_prefix }}"></div>
          </div>

          <div class="row2" style="margin-top:10px;">
            <div><label><strong>Token URL</strong></label><input type="text" name="token_url" value="{{ env.token_url }}"></div>
            <div><label><strong>JWT aud</strong></label><input type="text" name="jwt_aud" value="{{ env.jwt_aud }}"></div>
          </div>

          <div class="row2" style="margin-top:10px;">
            <div><label><strong>Token audience</strong> <span class="muted small">(leeg = iss_sub)</span></label><input type="text" name="token_audience" value="{{ env.token_audience }}"></div>
            <div><label><strong>Origin</strong></label><input type="text" name="origin" value="{{ origin }}"></div>
          </div>

          <hr style="border-color:#222; margin: 12px 0;">

          <h3>Client credentials</h3>
          <label><strong>iss & sub</strong></label>
          <input type="text" name="iss_sub" value="{{ iss_sub }}">

          <div class="row2" style="margin-top:10px;">
            <div><label><strong>kid</strong> <span class="muted small">(optioneel)</span></label><input type="text" name="kid" value="{{ kid }}"></div>
            <div><label><strong>exp offset</strong> <span class="muted small">(sec)</span></label><input type="text" name="exp_offset" value="{{ exp_offset }}"></div>
          </div>

          <div style="margin-top:10px;">
            <label><strong>Private key</strong> <span class="muted small">(.pfx/.p12/.pem/.key/.jwk/.json)</span></label>
            <input type="file" name="key_file" accept=".pfx,.p12,.pem,.key,.jwk,.json">
          </div>

          <div style="margin-top:10px;">
            <label><strong>Key password</strong> <span class="muted small">(optioneel)</span></label>
            <input type="password" name="key_password" value="">
          </div>

          <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn" type="submit" name="do_smoke" value="0">🔌 Connect</button>
            <button class="btn btn2" type="submit" name="do_smoke" value="1">⚡ Connect & Run Health</button>
            <a class="btn btn2" href="{{ url_for('dcbaas_api.index', tab=tab, env=env_id, req=req_key or '') }}">↩ Refresh</a>
          </div>

          {% if auth %}
            <div style="margin-top:12px;">
              {% if auth.ok %}<span class="ok">OK</span>{% else %}<span class="err">FOUT</span>{% endif %}
              <div class="muted small">{{ auth.msg }}</div>
            </div>
          {% endif %}

          {% if smoke %}
            <div style="margin-top:12px;">
              <span class="tag">SMOKE</span>
              {% if smoke.ok %}<span class="ok">OK</span>{% else %}<span class="err">FOUT</span>{% endif %}
              <div class="muted small">{{ smoke.msg }}</div>
              {% if smoke.last %}
                <div class="muted small">Endpoint: <code>{{ smoke.last.url }}</code> — {{ smoke.last.status }} ({{ smoke.last.elapsed_ms }} ms)</div>
              {% endif %}
            </div>
          {% endif %}

          <hr style="border-color:#222; margin: 12px 0;">

          <h3>Current token</h3>
          <textarea id="token_box" readonly>{{ token }}</textarea>
          <button type="button" class="btn btn2 small" onclick="copyId('token_box')">Kopieer token</button>
        </form>
      </div>

      <div>
        <div class="panel">
          <div class="tabs">
            <a class="tab {% if tab=='runner' %}active{% endif %}" href="#" onclick="setTab('runner'); return false;">🧪 Runner</a>
            <a class="tab {% if tab=='apps' %}active{% endif %}" href="#" onclick="setTab('apps'); return false;">📦 Applications</a>
            <a class="tab {% if tab=='certs' %}active{% endif %}" href="#" onclick="setTab('certs'); return false;">🔐 Certificates</a>
          </div>
        </div>

        {% if tab=='runner' %}
          <div class="panel" style="margin-top:14px;">
            <h2>Postman Runner</h2>
            <p class="muted small">Collection: <code>{{ collection_name }}</code> — requests: {{ requests|length }}</p>

            <div class="row2">
              <div class="reqlist" style="max-height:520px; overflow:auto;">
                {% for r in requests %}
                  {% set indent = ('&nbsp;&nbsp;&nbsp;' * r.depth) %}
                  <a class="{% if r.key == selected_key %}active{% endif %}"
                     href="{{ url_for('dcbaas_api.index', tab='runner', env=env_id, req=r.key) }}">
                    <span class="tag">{{ r.method }}</span>
                    <span class="indent">{{ indent|safe }}<span class="dot">•</span> {{ r.name }}</span>
                    {% if r.folder %}
                      <div class="muted small">{{ " / ".join(r.folder) }}</div>
                    {% else %}
                      <div class="muted small">(root)</div>
                    {% endif %}
                  </a>
                {% endfor %}
              </div>

              <div>
                <form method="post" action="{{ url_for('dcbaas_api.run_request') }}">
                  <input type="hidden" name="env_id" value="{{ env_id }}">
                  <input type="hidden" name="selected_key" value="{{ selected_key }}">

                  <label><strong>Method</strong></label>
                  <input type="text" name="method" value="{{ selected.method }}" readonly>

                  <label style="margin-top:10px;"><strong>URL</strong></label>
                  <input type="text" name="url" value="{{ resolved_url }}">

                  <label style="margin-top:10px;"><strong>Headers</strong></label>
                  <textarea name="headers_text" id="headers_text">{{ headers_text }}</textarea>
                  <button type="button" class="btn btn2 small" onclick="copyId('headers_text')">Copy</button>

                  <label style="margin-top:10px;"><strong>Body</strong> <span class="muted small">({{ body_mode_label }})</span></label>
                  <textarea name="body_text" id="body_text">{{ body_text }}</textarea>
                  <button type="button" class="btn btn2 small" onclick="copyId('body_text')">Copy</button>

                  <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                    <button class="btn" type="submit">▶ Run</button>
                    <a class="btn btn2" href="{{ url_for('dcbaas_api.index', tab='runner', env=env_id, req=selected_key) }}">↩ Reset</a>
                  </div>
                </form>
              </div>
            </div>
          </div>

          {% if last %}
          <div class="panel" style="margin-top:14px;">
            <h2>Response</h2>
            <p><span class="tag">{{ last.status }}</span> {% if last.ok %}<span class="ok">OK</span>{% else %}<span class="err">FOUT</span>{% endif %} <span class="muted">— {{ last.elapsed_ms }} ms</span></p>
            <h3>Headers</h3>
            <pre id="resp_headers">{{ last.headers }}</pre>
            <button type="button" class="btn btn2 small" onclick="copyId('resp_headers')">Copy</button>
            <h3 style="margin-top:12px;">Body</h3>
            <pre id="resp_body">{{ last.body }}</pre>
            <button type="button" class="btn btn2 small" onclick="copyId('resp_body')">Copy</button>
          </div>
          {% endif %}

        {% elif tab=='apps' %}
          <div class="panel" style="margin-top:14px;">
            <h2>Application acties</h2>
            <form method="post" action="{{ url_for('dcbaas_api.app_action') }}">
              <input type="hidden" name="env_id" value="{{ env_id }}">
              <label><strong>Application name</strong></label>
              <input type="text" name="app_name" value="">
              <label style="margin-top:10px;"><strong>Reason / description</strong></label>
              <input type="text" name="reason" value="API Test">
              <div class="row2" style="margin-top:10px;">
                <div><label><strong>Organization code (delegate)</strong></label><input type="text" name="org_code" value=""></div>
                <div><label><strong>Duration (maanden)</strong></label><input type="text" name="duration" value="1"></div>
              </div>
              <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                <button class="btn" name="action" value="add" type="submit">Add</button>
                <button class="btn" name="action" value="update" type="submit">Update</button>
                <button class="btn" name="action" value="delegate" type="submit">Delegate</button>
                <button class="btn danger" name="action" value="delete" type="submit">Delete</button>
                <button class="btn btn2" name="action" value="health" type="submit">Health</button>
              </div>
            </form>
          </div>

          {% if last %}
          <div class="panel" style="margin-top:14px;">
            <h2>Response</h2>
            <p><span class="tag">{{ last.status }}</span> {% if last.ok %}<span class="ok">OK</span>{% else %}<span class="err">FOUT</span>{% endif %}</p>
            <pre>{{ last.body }}</pre>
          </div>
          {% endif %}

        {% elif tab=='certs' %}
          <div class="panel" style="margin-top:14px;">
            <h2>Certificate add</h2>
            <form method="post" action="{{ url_for('dcbaas_api.cert_add') }}" enctype="multipart/form-data">
              <input type="hidden" name="env_id" value="{{ env_id }}">
              <label><strong>Application name</strong></label>
              <input type="text" name="application_name" value="">
              <label style="margin-top:10px;"><strong>Description</strong></label>
              <input type="text" name="description" value="">
              <div class="row2" style="margin-top:10px;">
                <div><label><strong>Organization code</strong></label><input type="text" name="organization_code" value=""></div>
                <div><label><strong>Duration (maanden)</strong></label><input type="text" name="duration" value="12"></div>
              </div>
              <div class="row2" style="margin-top:10px;">
                <div>
                  <label><strong>Certificate template</strong></label>
                  <select name="certificate_template">
                    {% for t in templates %}<option value="{{t}}">{{t}}</option>{% endfor %}
                  </select>
                </div>
                <div><label><strong>Custom template</strong> <span class="muted small">(als 'Andere')</span></label><input type="text" name="template_custom" value=""></div>
              </div>
              <label style="margin-top:10px;"><strong>CSR (paste)</strong> <span class="muted small">PEM/DER/base64</span></label>
              <textarea name="csr_text" placeholder="-----BEGIN CERTIFICATE REQUEST----- ..."></textarea>
              <div style="margin-top:10px;">
                <label><strong>CSR upload</strong> <span class="muted small">(.csr/.pem/.der/...)</span></label>
                <input type="file" name="csr_file" accept=".csr,.pem,.der,.txt,*/*">
              </div>
              <div style="margin-top:12px;">
                <button class="btn" type="submit">Add certificate</button>
              </div>
            </form>
          </div>

          {% if last %}
          <div class="panel" style="margin-top:14px;">
            <h2>Response</h2>
            <p><span class="tag">{{ last.status }}</span> {% if last.ok %}<span class="ok">OK</span>{% else %}<span class="err">FOUT</span>{% endif %}</p>
            <pre>{{ last.body }}</pre>
          </div>
          {% endif %}
        {% endif %}
      </div>
    </div>
  </div>
  {{ footer|safe }}
</body>
</html>
"""

def _render(tab: str = "runner", env_id: str = "DEV", selected_key: str = ""):
    settings = cynit_theme.load_settings()
    tools_cfg = cynit_theme.load_tools()
    tools = (tools_cfg.get("tools", []) if isinstance(tools_cfg, dict) else [])

    cfg = load_cfg()
    envs = cfg.get("environments", {}) or {}
    env = _env(cfg, env_id)

    origin = (cfg.get("defaults", {}) or {}).get("origin", "localhost")
    iss_sub = (cfg.get("defaults", {}) or {}).get("iss_sub", "")
    kid = (cfg.get("defaults", {}) or {}).get("kid", "")
    exp_offset = (cfg.get("defaults", {}) or {}).get("exp_offset", 300)

    token = STATE["tokens"].get(env_id, "")

    col_path = Path(__file__).parent / str(cfg.get("postman_collection_path", "config/dcbaas_postman_collection.json"))
    collection_name, reqs, _vars = _load_collection(col_path)

    if reqs:
        sel_key = selected_key or reqs[0].key
    else:
        sel_key = ""
    selected = next((r for r in reqs if r.key == sel_key), reqs[0] if reqs else None)

    var_values = {
        "url": (env.get("base_url") or "").rstrip("/"),
        "Origin": origin,
        "DCB TOKEN": token,
    }

    if selected:
        resolved_url = _apply_vars(selected.url_raw, var_values)
        headers_dict = _headers_to_dict(selected.headers, var_values)

        if "Origin" not in headers_dict:
            headers_dict["Origin"] = origin
        if token and "Authorization" not in headers_dict:
            headers_dict["Authorization"] = token

        headers_text = "\n".join([f"{k}: {v}" for k, v in headers_dict.items()])

        raw_body, form_body, _ct = _build_body(selected, var_values)
        if form_body is not None:
            body_text = "\n".join([f"{k}={v}" for k, v in form_body.items()])
            body_mode_label = "x-www-form-urlencoded"
        elif raw_body is not None:
            body_text = _safe_json_pretty(raw_body)
            body_mode_label = "raw"
        else:
            body_text = ""
            body_mode_label = "none"
    else:
        resolved_url, headers_text, body_text, body_mode_label = "", "", "", "none"

    base_css = cynit_layout.common_css(settings)
    common_js = cynit_layout.common_js()
    header = cynit_layout.header_html(settings, tools=tools, title="CyNiT - DCBaaS API", right_html="")
    footer = cynit_layout.footer_html()

    return render_template_string(
        TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header,
        footer=footer,
        colors=settings.get("colors", {}),
        tab=tab,
        env_id=env_id,
        envs=envs,
        env=env,
        origin=origin,
        iss_sub=iss_sub,
        kid=kid,
        exp_offset=exp_offset,
        token=token,
        auth=STATE.get("last_auth"),
        smoke=STATE.get("last_smoke"),
        collection_name=collection_name,
        requests=reqs,
        selected=(selected or PMRequest(key="(none)", name="(none)", folder=[], depth=0, method="GET", url_raw="", headers=[], body_mode="", body_raw="", body_urlencoded=[])),
        selected_key=sel_key,
        req_key=sel_key,
        resolved_url=resolved_url,
        headers_text=headers_text,
        body_text=body_text,
        body_mode_label=body_mode_label,
        last=STATE.get("last_resp"),
        templates=TEMPLATES,
    )

# -------------------- Routes --------------------

@bp.route("/dcbaas-api", methods=["GET"])
def index():
    tab = (request.args.get("tab") or "runner").strip()
    env_id = (request.args.get("env") or "DEV").strip()
    req_key = (request.args.get("req") or "").strip()
    return _render(tab=tab, env_id=env_id, selected_key=req_key)

@bp.route("/dcbaas-api/connect", methods=["POST"])
def connect():
    cfg = load_cfg()
    env_id = (request.form.get("env_id") or "DEV").strip()
    env = _env(cfg, env_id)

    base_url = (request.form.get("base_url") or env.get("base_url") or "").strip()
    api_prefix = (request.form.get("api_prefix") or env.get("api_prefix") or "").strip()
    token_url = (request.form.get("token_url") or env.get("token_url") or "").strip()
    jwt_aud = (request.form.get("jwt_aud") or env.get("jwt_aud") or "").strip()
    token_audience = (request.form.get("token_audience") or env.get("token_audience") or "").strip()
    origin = (request.form.get("origin") or (cfg.get("defaults", {}) or {}).get("origin", "localhost")).strip()

    iss_sub = (request.form.get("iss_sub") or (cfg.get("defaults", {}) or {}).get("iss_sub", "")).strip()
    kid = (request.form.get("kid") or (cfg.get("defaults", {}) or {}).get("kid", "")).strip()
    exp_offset_raw = (request.form.get("exp_offset") or (cfg.get("defaults", {}) or {}).get("exp_offset", 300)).strip()
    try:
        exp_offset = int(exp_offset_raw)
    except Exception:
        exp_offset = 300

    key_password = request.form.get("key_password") or None
    key_file = request.files.get("key_file")

    do_smoke = (request.form.get("do_smoke") or "0").strip() == "1"
    STATE["last_smoke"] = None

    if not iss_sub:
        STATE["last_auth"] = {"ok": False, "msg": "iss_sub is leeg. Vul je client-id/uuid in."}
        return _render(env_id=env_id)

    if not key_file or not key_file.filename:
        STATE["last_auth"] = {"ok": False, "msg": "Geen key file geselecteerd (.pfx/.pem/.jwk/...)"}
        return _render(env_id=env_id)

    try:
        key_bytes = key_file.read()
        key = _load_private_key_from_upload(key_file.filename, key_bytes, key_password)

        jwt_token = _build_jwt(iss_sub=iss_sub, aud=jwt_aud, key=key, kid=(kid or None), exp_offset=exp_offset)
        aud_for_token = token_audience or iss_sub
        access_token = _request_access_token(token_url=token_url, jwt_token=jwt_token, audience=aud_for_token)

        if not access_token:
            raise RuntimeError("Geen access_token ontvangen.")

        STATE["tokens"][env_id] = access_token
        STATE["last_auth"] = {"ok": True, "msg": f"Token OK voor {env_id}. (base_url={base_url})"}

        # Persist config
        cfg["defaults"]["origin"] = origin
        cfg["defaults"]["iss_sub"] = iss_sub
        cfg["defaults"]["kid"] = kid
        cfg["defaults"]["exp_offset"] = exp_offset
        cfg["environments"][env_id] = {
            **(cfg["environments"].get(env_id, {}) or {}),
            "base_url": base_url,
            "api_prefix": api_prefix,
            "token_url": token_url,
            "jwt_aud": jwt_aud,
            "token_audience": token_audience,
            "label": (cfg["environments"].get(env_id, {}) or {}).get("label", env_id),
        }
        _persist_cfg(cfg)

        if do_smoke:
            health_path = (cfg.get("health_path") or "/health").strip()
            url = f"{base_url.rstrip('/')}{api_prefix}{health_path}"
            headers = {"Origin": origin, "Accept": "application/json", "Authorization": access_token}
            last = _do_request("GET", url, headers, body_text="", timeout=30)
            STATE["last_resp"] = last
            STATE["last_smoke"] = {
                "ok": bool(last.get("ok")),
                "msg": "Health check uitgevoerd." if last.get("ok") else "Health check faalde.",
                "last": {"url": url, "status": last.get("status"), "elapsed_ms": last.get("elapsed_ms")},
            }

    except Exception as e:
        STATE["last_auth"] = {"ok": False, "msg": str(e)}

    return _render(env_id=env_id)

@bp.route("/dcbaas-api/run", methods=["POST"])
def run_request():
    cfg = load_cfg()
    env_id = (request.form.get("env_id") or "DEV").strip()
    env = _env(cfg, env_id)

    selected_key = (request.form.get("selected_key") or "").strip()
    method = (request.form.get("method") or "GET").upper().strip()
    url = (request.form.get("url") or "").strip()

    token = STATE["tokens"].get(env_id, "")
    origin = (cfg.get("defaults", {}) or {}).get("origin", "localhost")

    headers = _parse_headers_text(request.form.get("headers_text") or "")
    if "Origin" not in headers:
        headers["Origin"] = origin
    if token and "Authorization" not in headers:
        headers["Authorization"] = token

    body_text = request.form.get("body_text") or ""

    var_values = {"url": (env.get("base_url") or "").rstrip("/"), "Origin": origin, "DCB TOKEN": token}
    url2 = _apply_vars(url, var_values)
    body2 = _apply_vars(body_text, var_values)
    headers2 = {k: _apply_vars(v, var_values) for k, v in headers.items()}

    STATE["last_resp"] = _do_request(method, url2, headers2, body2, timeout=60)
    return _render(tab="runner", env_id=env_id, selected_key=selected_key)

@bp.route("/dcbaas-api/app", methods=["POST"])
def app_action():
    cfg = load_cfg()
    env_id = (request.form.get("env_id") or "DEV").strip()
    env = _env(cfg, env_id)

    base_url = (env.get("base_url") or "").rstrip("/")
    api_prefix = (env.get("api_prefix") or "").strip()
    token = STATE["tokens"].get(env_id, "")
    origin = (cfg.get("defaults", {}) or {}).get("origin", "localhost")

    action = (request.form.get("action") or "").strip()
    name = (request.form.get("app_name") or "").strip()
    reason = (request.form.get("reason") or "API Test").strip()
    org_code = (request.form.get("org_code") or "").strip()
    duration = (request.form.get("duration") or "1").strip()

    if action == "health":
        url = f"{base_url}{api_prefix}/health"
        hdr = {"Origin": origin, "Accept": "application/json"}
        if token:
            hdr["Authorization"] = token
        STATE["last_resp"] = _do_request("GET", url, hdr, "")
        return _render(tab="apps", env_id=env_id)

    if not name:
        STATE["last_resp"] = {"ok": False, "status": "INPUT ERROR", "elapsed_ms": -1, "headers": "", "body": "Application name is verplicht."}
        return _render(tab="apps", env_id=env_id)

    headers = {"Origin": origin, "Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token

    if action == "add":
        url = f"{base_url}{api_prefix}/application/add"
        payload = {"name": name, "reason": reason}
        STATE["last_resp"] = _do_request("POST", url, headers, json.dumps(payload, ensure_ascii=False))
    elif action == "update":
        url = f"{base_url}{api_prefix}/application/update"
        payload = {"name": name, "reason": reason}
        STATE["last_resp"] = _do_request("POST", url, headers, json.dumps(payload, ensure_ascii=False))
    elif action == "delegate":
        try:
            dur_i = int(duration)
        except Exception:
            dur_i = 1
        url = f"{base_url}{api_prefix}/application/delegate"
        payload = {"name": name, "organization_code_delegated": org_code, "duration": dur_i}
        STATE["last_resp"] = _do_request("POST", url, headers, json.dumps(payload, ensure_ascii=False))
    elif action == "delete":
        url = f"{base_url}{api_prefix}/application/delete"
        payload = {"name": name}
        STATE["last_resp"] = _do_request("POST", url, headers, json.dumps(payload, ensure_ascii=False))
    else:
        STATE["last_resp"] = {"ok": False, "status": "UNKNOWN ACTION", "elapsed_ms": -1, "headers": "", "body": action}

    return _render(tab="apps", env_id=env_id)

@bp.route("/dcbaas-api/cert/add", methods=["POST"])
def cert_add():
    cfg = load_cfg()
    env_id = (request.form.get("env_id") or "DEV").strip()
    env = _env(cfg, env_id)

    base_url = (env.get("base_url") or "").rstrip("/")
    api_prefix = (env.get("api_prefix") or "").strip()
    token = STATE["tokens"].get(env_id, "")
    origin = (cfg.get("defaults", {}) or {}).get("origin", "localhost")

    app_name = (request.form.get("application_name") or "").strip()
    desc = (request.form.get("description") or "").strip()
    org = (request.form.get("organization_code") or "").strip()
    duration = (request.form.get("duration") or "12").strip()
    tpl = (request.form.get("certificate_template") or "").strip()
    tpl_custom = (request.form.get("template_custom") or "").strip()
    csr_text = request.form.get("csr_text") or ""
    csr_file = request.files.get("csr_file")

    if tpl == "Andere" and tpl_custom:
        tpl = tpl_custom

    try:
        dur_i = int(duration)
    except Exception:
        dur_i = 12

    csr_b64 = _csr_to_b64(csr_text, csr_file)

    if not app_name or not csr_b64:
        STATE["last_resp"] = {"ok": False, "status": "INPUT ERROR", "elapsed_ms": -1, "headers": "", "body": "Application name en CSR zijn verplicht."}
        return _render(tab="certs", env_id=env_id)

    headers = {"Origin": origin, "Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token

    url = f"{base_url}{api_prefix}/application/certificate/add"
    payload = {
        "application_name": app_name,
        "description": desc or f"Certificaat {app_name}",
        "organization_code": org,
        "duration": dur_i,
        "certificate_template": tpl,
        "csr": csr_b64,
    }
    STATE["last_resp"] = _do_request("POST", url, headers, json.dumps(payload, ensure_ascii=False))
    return _render(tab="certs", env_id=env_id)

def register_web_routes(app: Flask, settings: dict, tools=None) -> None:
    app.register_blueprint(bp)

if __name__ == "__main__":
    app = Flask(__name__)
    register_web_routes(app, cynit_theme.load_settings(), cynit_theme.load_tools())
    app.run(host="127.0.0.1", port=5451, debug=True)
