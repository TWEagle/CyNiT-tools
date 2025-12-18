#!/usr/bin/env python3
"""
voica1.py

VOICA1 device certificaten-tool voor CyNiT Tools.

- Standalone web:  python voica1.py  -> http://127.0.0.1:5445/voica1
- In CyNiT hub:    import voica1; voica1.register_web_routes(app, settings, tools, voica_cfg)

Features:
- UI keuze: Engine = Python (cryptography) of OpenSSL
- Debug toggle (default OFF) op pagina
- Progress overlay bij stap 1 en stap 2
- Batch log: MM_DD.txt in output map (start met password + type)
"""

from __future__ import annotations

import os
import sys
import string
import secrets
import logging
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from flask import Flask, request, render_template_string

import cynit_theme
import cynit_layout

# =========================
# Logging (zorgt dat je wél logs ziet in PowerShell)
# =========================

logger = logging.getLogger("voica1")

def _ensure_console_logging() -> None:
    """Zorgt dat logger output naar stdout gaat, ook als ctools logging niet init."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)

_ensure_console_logging()

# =========================
# Globals / defaults
# =========================

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
MESSAGES_PATH = CONFIG_DIR / "voica1_messages.md"

ROOT_BASE_DIR = r"C:\Users\lemmenmf\OneDrive - Vlaamse overheid - Office 365\DCBaaS\VOICA1"

PASS_LENGTH = 24
KEY_SIZE_DEFAULT = 2048

OPENSSL_BIN = "openssl"
OPENSSL_CONF: Optional[str] = None

CERT_EXTS = (".cer", ".crt", ".pem")

# UI / state
SETTINGS: Dict[str, Any] = {}
TOOLS: List[Dict[str, Any]] = []
VOICA_CFG: Dict[str, Any] = {}

# default: Python engine (dan heb je geen openssl nodig)
DEFAULT_ENGINE = "python"   # "python" | "openssl"
DEBUG_DEFAULT = False


class CommandError(Exception):
    """Fout bij extern commando (openssl, ...)."""
    pass


# =========================
# Config apply
# =========================

def apply_voica_config(voica_cfg: Dict[str, Any]) -> None:
    global VOICA_CFG, ROOT_BASE_DIR, PASS_LENGTH, KEY_SIZE_DEFAULT, OPENSSL_BIN, OPENSSL_CONF, DEFAULT_ENGINE, DEBUG_DEFAULT
    VOICA_CFG = voica_cfg or {}

    ROOT_BASE_DIR = VOICA_CFG.get("root_base_dir", ROOT_BASE_DIR)

    try:
        PASS_LENGTH = int(VOICA_CFG.get("pass_length", PASS_LENGTH))
    except Exception:
        pass

    try:
        KEY_SIZE_DEFAULT = int(VOICA_CFG.get("default_key_size", KEY_SIZE_DEFAULT))
    except Exception:
        pass

    OPENSSL_BIN = VOICA_CFG.get("openssl_bin", OPENSSL_BIN)
    OPENSSL_CONF = VOICA_CFG.get("openssl_conf", OPENSSL_CONF)

    DEFAULT_ENGINE = (VOICA_CFG.get("default_engine") or DEFAULT_ENGINE).strip().lower()
    if DEFAULT_ENGINE not in ("python", "openssl"):
        DEFAULT_ENGINE = "python"

    DEBUG_DEFAULT = bool(VOICA_CFG.get("debug_default", DEBUG_DEFAULT))

    logger.info(
        "[VOICA1] cfg: root=%r pass_len=%r key_default=%r engine=%r openssl=%r conf=%r debug_default=%r",
        ROOT_BASE_DIR, PASS_LENGTH, KEY_SIZE_DEFAULT, DEFAULT_ENGINE, OPENSSL_BIN, OPENSSL_CONF, DEBUG_DEFAULT
    )


# =========================
# Helpers
# =========================

def set_debug_enabled(enabled: bool) -> None:
    """Zet logger level live."""
    logger.setLevel(logging.DEBUG if enabled else logging.INFO)

def generate_password(length: int) -> str:
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%&*()-_=+;[{}]:,.<>?/"

    all_chars = lower + upper + digits + symbols
    non_symbols = lower + upper + digits

    length = max(8, int(length))

    while True:
        pwd = [
            secrets.choice(lower),
            secrets.choice(upper),
            secrets.choice(digits),
            secrets.choice(symbols),
        ]
        pwd += [secrets.choice(all_chars) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)

        if pwd[0] in symbols or pwd[-1] in symbols:
            continue
        if not any(ch in symbols for ch in pwd[1:-1]):
            continue
        if pwd[0] not in non_symbols or pwd[-1] not in non_symbols:
            continue

        return "".join(pwd)

def validate_device_id(device_id: str) -> str:
    d = device_id.strip()
    if not d:
        raise ValueError("Toestelnummer mag niet leeg zijn.")
    return d

def build_cn(device_id: str, device_type: str) -> str:
    if device_type == "ip_phone":
        return f"{device_id}@gidphones.vlaanderen.be"
    return f"{device_id}.alfa.top.vlaanderen.be"

def build_devices_string(devices: List[str]) -> str:
    if not devices:
        return ""
    if len(devices) == 1:
        return devices[0]
    return "; ".join(devices[:-1]) + f" & {devices[-1]}"

def compute_default_base_dir() -> str:
    root = Path(ROOT_BASE_DIR)
    now = datetime.now()
    target = root / f"{now.year}" / f"{now.month:02d}" / f"{now.day}"
    target.mkdir(parents=True, exist_ok=True)
    logger.debug("[VOICA1] compute_default_base_dir -> %s", target)
    return str(target)

def _device_type_label(device_type: str) -> str:
    if device_type == "pc":
        return "PC/VM/Mac"
    if device_type == "ip_phone":
        return "IP Phone"
    return device_type

def write_batch_log(base_dir: Path, device_type: str, password: str, created_files: List[Path]) -> None:
    """
    Bestandsnaam: MM_DD.txt (bv. 12_17.txt)
    Start met wachtwoord en type, dan alle created files met timestamp.
    """
    now = datetime.now()
    log_name = f"{now.month:02d}_{now.day:02d}.txt"
    log_path = base_dir / log_name

    with log_path.open("a", encoding="utf-8") as f:
        header_ts = now.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"PASSWORD: {password}\n")
        f.write(f"TYPE: {_device_type_label(device_type)}\n")
        f.write(f"START: {header_ts}\n")
        f.write("-" * 60 + "\n")
        for p in created_files:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} | CREATED | {p.name}\n")
        f.write("\n")

    logger.debug("[VOICA1] batch log written: %s", log_path)


# =========================
# Engine: OpenSSL
# =========================

def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> str:
    env = os.environ.copy()
    if OPENSSL_CONF:
        env["OPENSSL_CONF"] = OPENSSL_CONF

    logger.debug("[VOICA1] run_cmd: cwd=%r cmd=%r", str(cwd) if cwd else None, cmd)
    if OPENSSL_CONF:
        logger.debug("[VOICA1] run_cmd: OPENSSL_CONF=%r", OPENSSL_CONF)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as e:
        logger.exception("[VOICA1] run_cmd: FileNotFoundError (WinError 2). cmd=%r", cmd)
        raise CommandError(
            "OpenSSL werd niet gevonden (WinError 2).\n"
            f"Commando: {' '.join(cmd)}\n"
            "Fix opties:\n"
            " - Zet in config/voica1.json: openssl_bin naar het volledige pad (bv. C:\\\\openssl\\\\x64\\\\bin\\\\openssl.exe)\n"
            " - Of kies in de UI: Engine = Python (cryptography)\n"
        ) from e

    if result.returncode != 0:
        raise CommandError(
            f"Commando gefaald: {' '.join(cmd)}\n"
            f"OPENSSL_CONF={OPENSSL_CONF}\n"
            f"Returncode: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )

    return result.stdout

def openssl_create_key_and_csr(base_dir: Path, cn: str, key_size: int) -> Tuple[Path, Path]:
    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"

    run_cmd([OPENSSL_BIN, "genrsa", "-out", str(key_path), str(int(key_size))])
    run_cmd([
        OPENSSL_BIN, "req", "-new",
        "-key", str(key_path),
        "-subj", f"/CN={cn}",
        "-out", str(csr_path),
        "-sha256",
    ])
    return key_path, csr_path

def openssl_parse_cert_cn(cert_path: Path) -> Optional[str]:
    try:
        out = run_cmd([OPENSSL_BIN, "x509", "-in", str(cert_path), "-noout", "-subject"])
    except CommandError:
        return None

    line = out.strip()
    if "CN=" not in line:
        return None
    idx = line.find("CN=")
    cn_part = line[idx + 3:]
    slash = cn_part.find("/")
    if slash != -1:
        cn_part = cn_part[:slash]
    cn_part = cn_part.strip()
    return cn_part or None

def openssl_cert_to_pem_text(cert_path: Path) -> str:
    # probeer utf-8 tekst
    try:
        txt = cert_path.read_text(encoding="utf-8")
        if "BEGIN CERTIFICATE" in txt:
            return txt
    except UnicodeDecodeError:
        pass

    # DER -> PEM via openssl
    out = run_cmd([OPENSSL_BIN, "x509", "-in", str(cert_path), "-outform", "PEM"])
    return out

def openssl_create_p12(base_dir: Path, cn: str, password: str, cert_map: Dict[str, Path]) -> Path:
    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"
    if not key_path.exists():
        raise CommandError(f"Key niet gevonden: {key_path}")
    if not csr_path.exists():
        raise CommandError(f"CSR niet gevonden: {csr_path}")

    cert_path = cert_map.get(cn)
    if not cert_path:
        raise CommandError(f"Geen certificaat gevonden in map voor CN {cn}")

    p12_path = base_dir / f"{cn}.p12"
    run_cmd([
        OPENSSL_BIN, "pkcs12", "-export",
        "-inkey", str(key_path),
        "-in", str(cert_path),
        "-out", str(p12_path),
        "-passout", f"pass:{password}",
    ])
    return p12_path


# =========================
# Engine: Python (cryptography)
# =========================

def _crypto_import():
    try:
        from cryptography import x509  # noqa
        from cryptography.hazmat.primitives import hashes, serialization  # noqa
        from cryptography.hazmat.primitives.asymmetric import rsa  # noqa
        from cryptography.hazmat.primitives.serialization import pkcs12  # noqa
        from cryptography.x509.oid import NameOID  # noqa
        return True
    except Exception:
        return False

def py_load_cert(cert_path: Path):
    from cryptography import x509
    data = cert_path.read_bytes()

    # PEM?
    if b"BEGIN CERTIFICATE" in data:
        return x509.load_pem_x509_certificate(data)
    # DER
    return x509.load_der_x509_certificate(data)

def py_parse_cert_cn(cert_path: Path) -> Optional[str]:
    try:
        cert = py_load_cert(cert_path)
        from cryptography.x509.oid import NameOID
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not attrs:
            return None
        return attrs[0].value
    except Exception:
        return None

def py_cert_to_pem_text(cert_path: Path) -> str:
    from cryptography.hazmat.primitives import serialization
    cert = py_load_cert(cert_path)
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

def py_create_key_and_csr(base_dir: Path, cn: str, key_size: int) -> Tuple[Path, Path]:
    if not _crypto_import():
        raise CommandError(
            "Python engine vereist 'cryptography'.\n"
            "Installeer: pip install cryptography\n"
            "Of kies in de UI: Engine = OpenSSL."
        )

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=int(key_size))
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(key_pem)

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .sign(private_key, hashes.SHA256())
    )
    csr_path.write_bytes(csr.public_bytes(serialization.Encoding.PEM))
    return key_path, csr_path

def py_create_p12(base_dir: Path, cn: str, password: str, cert_map: Dict[str, Path]) -> Path:
    if not _crypto_import():
        raise CommandError(
            "Python engine vereist 'cryptography'.\n"
            "Installeer: pip install cryptography\n"
            "Of kies in de UI: Engine = OpenSSL."
        )

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"
    if not key_path.exists():
        raise CommandError(f"Key niet gevonden: {key_path}")
    if not csr_path.exists():
        raise CommandError(f"CSR niet gevonden: {csr_path}")

    cert_path = cert_map.get(cn)
    if not cert_path:
        raise CommandError(f"Geen certificaat gevonden in map voor CN {cn}")

    # private key
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

    # leaf cert
    cert = py_load_cert(cert_path)

    p12_bytes = pkcs12.serialize_key_and_certificates(
        name=cn.encode("utf-8"),
        key=private_key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")),
    )

    p12_path = base_dir / f"{cn}.p12"
    p12_path.write_bytes(p12_bytes)
    return p12_path


# =========================
# Cert scanning / mapping
# =========================

def map_certs_by_cn(base_dir: Path, engine: str) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    if not base_dir.exists():
        return mapping

    for p in base_dir.iterdir():
        if not p.is_file():
            continue

        name = p.name.lower()
        if name.endswith(".key.pem") or name.endswith(".csr") or name.endswith(".p12") or name.endswith(".pfx"):
            continue
        if name.endswith(".zip") or name.endswith(".combined.pem"):
            continue
        if not name.endswith(CERT_EXTS):
            continue

        if engine == "openssl":
            cn = openssl_parse_cert_cn(p)
        else:
            cn = py_parse_cert_cn(p)

        if cn and cn not in mapping:
            mapping[cn] = p

    logger.debug("[VOICA1] map_certs_by_cn: found CNs=%r", list(mapping.keys()))
    return mapping


# =========================
# Output creation (.pem combined, zip)
# =========================

def create_combined_pem(base_dir: Path, cn: str, cert_map: Dict[str, Path], engine: str) -> Path:
    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"
    if not key_path.exists():
        raise CommandError(f"Key niet gevonden: {key_path}")
    if not csr_path.exists():
        raise CommandError(f"CSR niet gevonden: {csr_path}")

    cert_path = cert_map.get(cn)
    if not cert_path:
        raise CommandError(f"Geen certificaat gevonden in map voor CN {cn}")

    combined_path = base_dir / f"{cn}.pem"

    key_txt = key_path.read_text(encoding="utf-8")

    if engine == "openssl":
        cert_pem = openssl_cert_to_pem_text(cert_path)
    else:
        cert_pem = py_cert_to_pem_text(cert_path)

    combined = key_txt.rstrip() + "\n" + cert_pem.strip() + "\n"
    combined_path.write_text(combined, encoding="utf-8")
    return combined_path


def zip_pems(base_dir: Path, pem_files: List[Path], password: Optional[str]) -> Optional[Path]:
    if not pem_files:
        return None

    zip_name = f"{base_dir.name}.zip"
    zip_path = base_dir / zip_name

    # voorkeur: pyzipper (AES + wachtwoord)
    try:
        import pyzipper  # type: ignore
        with pyzipper.AESZipFile(
            zip_path,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))
                zf.setencryption(pyzipper.WZ_AES, nbits=128)
            for f in pem_files:
                zf.write(f, arcname=f.name)
        return zip_path
    except ImportError:
        raise CommandError(
            "Wachtwoord-zip voor phones vereist 'pyzipper'.\n"
            "Installeer: pip install pyzipper"
        )
    except Exception as e:
        raise CommandError(f"Fout bij maken ZIP: {e}")


# =========================
# Messages blocks
# =========================

def load_message_block(path: Path, block_name: str) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    start_token = f"[[{block_name}]]"
    end_token = "[[END]]"
    if start_token not in text:
        return ""
    part = text.split(start_token, 1)[1]
    part = part.split(end_token, 1)[0]
    return part.strip()

def render_template_text(template: str, devices: str, password: str) -> str:
    if not template:
        return ""
    return template.replace("{{devices}}", devices).replace("{{password}}", password)


# =========================
# HTML
# =========================

PAGE_TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>VOICA1 Certificaten</title>
  <style>
    {{ base_css|safe }}

    .voica-container { max-width: 1100px; margin: 0 auto; }
    .card {
      background: #111111; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.7);
    }
    .card h2 { margin-top: 0; margin-bottom: 8px; }
    .card small { color: #aaaaaa; }
    .field-row { margin-bottom: 10px; }
    .field-row label { display: block; margin-bottom: 3px; }
    input[type="text"], select, textarea {
      width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 4px;
      border: 1px solid #333333; background: #050505; color: {{ colors.general_fg }};
      font-family: {{ ui.font_main }}; font-size: 0.9rem;
    }
    textarea { min-height: 100px; resize: vertical; }
    .row-inline { display: flex; gap: 12px; }
    .row-inline > div { flex: 1; }
    .error-box {
      background: #330000; border: 1px solid #aa3333; color: #ffaaaa; padding: 8px 10px;
      border-radius: 6px; margin-bottom: 12px; font-size: 0.9rem;
      white-space: pre-wrap;
    }
    .results-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9rem; }
    .results-table th, .results-table td { border: 1px solid #333; padding: 4px 6px; }
    .results-table th { background: #222; }
    .muted { color: #aaaaaa; font-size: 0.85rem; }
    .text-ok { color: #00ff88; }
    .text-fail { color: #ff6666; }
    .missing-list { margin-top: 8px; font-size: 0.9rem; color: #ffaaaa; }
    .textarea-small { min-height: 60px; }

    /* progress overlay */
    #voica-progress-overlay {
      position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75);
      display: none; align-items: center; justify-content: center; z-index: 2000;
    }
    .voica-progress-box {
      background: #111111; border: 1px solid #444444; padding: 20px 30px;
      border-radius: 8px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.9);
      min-width: 280px; max-width: 520px; text-align: center; color: {{ colors.general_fg }};
      font-family: {{ ui.font_main }}, monospace;
    }
    .voica-progress-title { font-size: 1.1em; margin-bottom: 12px; color: {{ colors.title }}; }
    .voica-progress-bar-outer { width: 100%; height: 10px; background: #222222; border-radius: 6px; overflow: hidden; margin-top: 6px; }
    .voica-progress-bar-inner {
      width: 40%; height: 100%; background: {{ colors.button_fg }}; border-radius: 6px;
      animation: voica-bar-move 1.0s linear infinite;
    }
    @keyframes voica-bar-move { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
  </style>

  <script>
    {{ common_js|safe }}

    function copyText(id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.select();
      el.setSelectionRange(0, 99999);
      document.execCommand("copy");
    }

    function voicaShowProgress(stepText) {
      var overlay = document.getElementById('voica-progress-overlay');
      var label   = document.getElementById('voica-progress-text');
      if (!overlay || !label) return;
      label.textContent = stepText || "Bezig met verwerken...";
      overlay.style.display = 'flex';
    }

    window.addEventListener('load', function() {
      var formGen  = document.getElementById('voica-form-generate');
      var formProc = document.getElementById('voica-form-process');

      if (formGen) formGen.addEventListener('submit', function() {
        voicaShowProgress("Stap 1: CSR generatie bezig...");
      });
      if (formProc) formProc.addEventListener('submit', function() {
        voicaShowProgress("Stap 2: certificaten verwerken...");
      });
    });
  </script>
</head>
<body>
  {{ header|safe }}

  <div id="voica-progress-overlay">
    <div class="voica-progress-box">
      <div class="voica-progress-title" id="voica-progress-text">Bezig met verwerken...</div>
      <div class="voica-progress-bar-outer"><div class="voica-progress-bar-inner"></div></div>
      <div class="muted" style="margin-top:10px;">Even geduld…</div>
    </div>
  </div>

  <div class="page">
    <div class="voica-container">
      <h1>VOICA1 Certificaten aanmaken</h1>
      <p class="muted">Batch CSR + certificaatverwerking voor VOICA1 phones en PCs/VMs.</p>

      {% if error %}
        <div class="error-box">{{ error }}</div>
      {% endif %}

      <div class="card">
        <h2>Stap 1 – CSR aanmaken</h2>
        <small>Genereer key + CSR per toestel (PC/VM of Phone).</small>

        <form id="voica-form-generate" method="post" action="/voica1/generate">
          <div class="row-inline">
            <div>
              <label>Engine</label>
              <select name="engine">
                <option value="python" {% if engine == 'python' %}selected{% endif %}>Python (cryptography)</option>
                <option value="openssl" {% if engine == 'openssl' %}selected{% endif %}>OpenSSL</option>
              </select>
              <small class="muted">Default: Python. OpenSSL vereist correct pad of PATH.</small>
            </div>
            <div>
              <label>Debug logging</label>
              <select name="debug">
                <option value="0" {% if not debug_enabled %}selected{% endif %}>OFF</option>
                <option value="1" {% if debug_enabled %}selected{% endif %}>ON</option>
              </select>
              <small class="muted">Zet extra logging aan/uit.</small>
            </div>
          </div>

          <div class="field-row">
            <label>Doelmap (root: {{ root_base_dir }})</label>
            <input type="text" name="base_dir" value="{{ base_dir }}">
            <small class="muted">Standaard: {{ base_dir }}</small>
          </div>

          <div class="row-inline">
            <div>
              <label>Device type</label>
              <select name="device_type">
                <option value="pc" {% if device_type == 'pc' %}selected{% endif %}>PC / VM (.p12)</option>
                <option value="ip_phone" {% if device_type == 'ip_phone' %}selected{% endif %}>IP Phone (.pem + zip)</option>
              </select>
            </div>
            <div>
              <label>Key size (bits)</label>
              <select name="key_size">
                <option value="2048" {% if key_size == 2048 %}selected{% endif %}>2048</option>
                <option value="4096" {% if key_size == 4096 %}selected{% endif %}>4096</option>
              </select>
            </div>
          </div>

          <div class="field-row">
            <label>Toestellen (één per lijn)</label>
            <textarea name="devices">{{ devices_input }}</textarea>
          </div>

          <div class="field-row">
            <button type="submit">Stap 1: Genereer CSR(s)</button>
          </div>
        </form>
      </div>

      <div class="card">
        <h2>Stap 2 – Certificaten verwerken</h2>
        <small>Na AEG import: koppel CRT/CER aan CSR en maak P12/PEM/ZIP + mailteksten.</small>

        <form id="voica-form-process" method="post" action="/voica1/process">
          <input type="hidden" name="base_dir" value="{{ base_dir }}">
          <input type="hidden" name="device_type" value="{{ device_type }}">
          <input type="hidden" name="key_size" value="{{ key_size }}">
          <input type="hidden" name="devices" value="{{ devices_hidden }}">
          <input type="hidden" name="engine" value="{{ engine }}">
          <input type="hidden" name="debug" value="{{ 1 if debug_enabled else 0 }}">

          <div class="field-row">
            <label>Batch-wachtwoord</label>
            <input type="text" name="password" value="{{ password }}">
            <small class="muted">Zelfde wachtwoord wordt gebruikt voor alle toestellen en ZIP (phones).</small>
          </div>

          <div class="field-row">
            <button type="submit" {% if not step1_done %}disabled{% endif %}>Stap 2: Verwerk certificaten</button>
          </div>
        </form>
      </div>

      <div class="card">
        <h2>Resultaten</h2>

        {% if devices_list %}
          <p class="muted">Toestellen in deze batch: {{ devices_str }}</p>
        {% endif %}

        {% if results %}
          <table class="results-table">
            <tr><th>Device</th><th>Status</th><th>Detail</th></tr>
            {% for r in results %}
              <tr>
                <td>{{ r.device }}</td>
                <td>{% if r.ok %}<span class="text-ok">OK</span>{% else %}<span class="text-fail">FOUT</span>{% endif %}</td>
                <td>{{ r.message }}</td>
              </tr>
            {% endfor %}
          </table>
        {% else %}
          <p class="muted">Nog geen resultaten.</p>
        {% endif %}

        {% if missing_certs %}
          <div class="missing-list">
            <strong>Ontbrekende certificaten (nog niet uit AEG?):</strong>
            <ul>
              {% for m in missing_certs %}
                <li>{{ m.device }} – CN: {{ m.cn }}</li>
              {% endfor %}
            </ul>
          </div>
        {% endif %}

        {% if zip_path %}
          <p class="muted">Phone ZIP: {{ zip_path }}</p>
        {% endif %}
      </div>

      <div class="card">
        <h2>Mailteksten</h2>

        <div class="field-row">
          <label>Certificate mail</label>
          <textarea id="txt_certmail" class="textarea-small">{{ certmail_text }}</textarea>
          <button type="button" onclick="copyText('txt_certmail')">Kopieer CERT mail</button>
        </div>

        <div class="field-row">
          <label>OTS mail</label>
          <textarea id="txt_ots" class="textarea-small">{{ ots_text }}</textarea>
          <button type="button" onclick="copyText('txt_ots')">Kopieer OTS mail</button>
        </div>

        <div class="field-row">
          <label>WhatsApp tekst</label>
          <textarea id="txt_wa" class="textarea-small">{{ wa_text }}</textarea>
          <button type="button" onclick="copyText('txt_wa')">Kopieer WA tekst</button>
        </div>

        <div class="field-row">
          <label>Signal tekst</label>
          <textarea id="txt_signal" class="textarea-small">{{ signal_text }}</textarea>
          <button type="button" onclick="copyText('txt_signal')">Kopieer Signal tekst</button>
        </div>
      </div>
    </div>
  </div>

  {{ footer|safe }}
</body>
</html>
"""


def _render(
    *,
    error: Optional[str],
    base_dir: str,
    device_type: str,
    key_size: int,
    devices_input: str,
    devices_hidden: str,
    step1_done: bool,
    step2_done: bool,
    devices_list: List[str],
    cns: Dict[str, str],
    devices_str: str,
    password: str,
    results: List[Dict[str, Any]],
    zip_path: Optional[str],
    certmail_text: str,
    ots_text: str,
    wa_text: str,
    signal_text: str,
    missing_certs: List[Dict[str, Any]],
    engine: str,
    debug_enabled: bool,
):
    colors = SETTINGS.get("colors", {})
    ui = SETTINGS.get("ui", {})
    base_css = cynit_layout.common_css(SETTINGS)
    common_js = cynit_layout.common_js()

    header_html = cynit_layout.header_html(
        SETTINGS,
        tools=TOOLS,
        title="VOICA1 Certificaten",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    return render_template_string(
        PAGE_TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        error=error,
        base_dir=base_dir,
        root_base_dir=ROOT_BASE_DIR,
        device_type=device_type,
        key_size=key_size,
        devices_input=devices_input,
        devices_hidden=devices_hidden,
        step1_done=step1_done,
        step2_done=step2_done,
        devices_list=devices_list,
        cns=cns,
        devices_str=devices_str,
        password=password,
        results=results,
        zip_path=zip_path,
        certmail_text=certmail_text,
        ots_text=ots_text,
        wa_text=wa_text,
        signal_text=signal_text,
        missing_certs=missing_certs,
        engine=engine,
        debug_enabled=debug_enabled,
    )


# =========================
# Routes
# =========================

def register_web_routes(app, settings, tools, voica_cfg):
    global SETTINGS, TOOLS
    SETTINGS = settings or {}
    TOOLS = tools or []
    apply_voica_config(voica_cfg or {})

    @app.route("/voica1", methods=["GET"])
    def voica1_index():
        debug_enabled = DEBUG_DEFAULT
        set_debug_enabled(debug_enabled)

        return _render(
            error=None,
            base_dir=compute_default_base_dir(),
            device_type="pc",
            key_size=KEY_SIZE_DEFAULT,
            devices_input="",
            devices_hidden="",
            step1_done=False,
            step2_done=False,
            devices_list=[],
            cns={},
            devices_str="",
            password="",
            results=[],
            zip_path=None,
            certmail_text="",
            ots_text="",
            wa_text="",
            signal_text="",
            missing_certs=[],
            engine=DEFAULT_ENGINE,
            debug_enabled=debug_enabled,
        )

    @app.route("/voica1/generate", methods=["POST"])
    def voica1_generate():
        base_dir_str = (request.form.get("base_dir") or "").strip()
        device_type = (request.form.get("device_type") or "pc").strip()
        engine = (request.form.get("engine") or DEFAULT_ENGINE).strip().lower()
        debug_enabled = (request.form.get("debug") or "0").strip() == "1"
        set_debug_enabled(debug_enabled)

        key_size_str = (request.form.get("key_size") or str(KEY_SIZE_DEFAULT)).strip()
        devices_raw = request.form.get("devices") or ""
        error: Optional[str] = None

        try:
            key_size = int(key_size_str)
        except Exception:
            key_size = KEY_SIZE_DEFAULT

        if engine not in ("python", "openssl"):
            engine = "python"

        if not base_dir_str:
            error = "Map is verplicht."
            return _render(
                error=error,
                base_dir=compute_default_base_dir(),
                device_type=device_type,
                key_size=key_size,
                devices_input=devices_raw,
                devices_hidden="",
                step1_done=False,
                step2_done=False,
                devices_list=[],
                cns={},
                devices_str="",
                password="",
                results=[],
                zip_path=None,
                certmail_text="",
                ots_text="",
                wa_text="",
                signal_text="",
                missing_certs=[],
                engine=engine,
                debug_enabled=debug_enabled,
            )

        base_dir = Path(base_dir_str)
        base_dir.mkdir(parents=True, exist_ok=True)

        devices = [line.strip() for line in devices_raw.splitlines() if line.strip()]
        if not devices:
            error = "Voer minstens één device in."
            return _render(
                error=error,
                base_dir=str(base_dir),
                device_type=device_type,
                key_size=key_size,
                devices_input=devices_raw,
                devices_hidden="",
                step1_done=False,
                step2_done=False,
                devices_list=[],
                cns={},
                devices_str="",
                password="",
                results=[],
                zip_path=None,
                certmail_text="",
                ots_text="",
                wa_text="",
                signal_text="",
                missing_certs=[],
                engine=engine,
                debug_enabled=debug_enabled,
            )

        password = generate_password(PASS_LENGTH)
        logger.debug("[VOICA1] generated password=%r", password)

        cns: Dict[str, str] = {}
        dev_list: List[str] = []

        try:
            for dev in devices:
                dev_id = validate_device_id(dev)
                cn = build_cn(dev_id, device_type)
                cns[dev_id] = cn
                dev_list.append(dev_id)

                if engine == "openssl":
                    openssl_create_key_and_csr(base_dir, cn, key_size)
                else:
                    py_create_key_and_csr(base_dir, cn, key_size)

        except Exception as e:
            if debug_enabled:
                error = f"Fout bij aanmaken key/CSR:\n{e}\n\n{traceback.format_exc()}"
            else:
                error = f"Fout bij aanmaken key/CSR: {e}"
            logger.error("[VOICA1] generate failed: %s", e)
            logger.debug(traceback.format_exc())

        devices_str = build_devices_string(dev_list)
        devices_hidden = "\n".join(dev_list)

        return _render(
            error=error,
            base_dir=str(base_dir),
            device_type=device_type,
            key_size=key_size,
            devices_input="\n".join(dev_list),
            devices_hidden=devices_hidden,
            step1_done=True,
            step2_done=False,
            devices_list=dev_list,
            cns=cns,
            devices_str=devices_str,
            password=password,
            results=[],
            zip_path=None,
            certmail_text="",
            ots_text="",
            wa_text="",
            signal_text="",
            missing_certs=[],
            engine=engine,
            debug_enabled=debug_enabled,
        )

    @app.route("/voica1/process", methods=["POST"])
    def voica1_process():
        base_dir_str = (request.form.get("base_dir") or "").strip()
        device_type = (request.form.get("device_type") or "pc").strip()
        engine = (request.form.get("engine") or DEFAULT_ENGINE).strip().lower()
        debug_enabled = (request.form.get("debug") or "0").strip() == "1"
        set_debug_enabled(debug_enabled)

        key_size_str = (request.form.get("key_size") or str(KEY_SIZE_DEFAULT)).strip()
        devices_hidden = request.form.get("devices") or ""
        password = request.form.get("password") or ""
        error: Optional[str] = None

        try:
            key_size = int(key_size_str)
        except Exception:
            key_size = KEY_SIZE_DEFAULT

        if engine not in ("python", "openssl"):
            engine = "python"

        base_dir = Path(base_dir_str)
        devices = [line.strip() for line in devices_hidden.splitlines() if line.strip()]
        cns = {d: build_cn(d, device_type) for d in devices}
        devices_str = build_devices_string(devices)

        cert_map = map_certs_by_cn(base_dir, engine=engine)

        results: List[Dict[str, Any]] = []
        pem_files: List[Path] = []
        missing_certs: List[Dict[str, Any]] = []
        created_files: List[Path] = []

        # missing certs
        for dev in devices:
            cn = build_cn(dev, device_type)
            if cn not in cert_map:
                missing_certs.append({"device": dev, "cn": cn})

        for dev in devices:
            cn = build_cn(dev, device_type)
            try:
                if device_type == "pc":
                    if engine == "openssl":
                        out = openssl_create_p12(base_dir, cn, password, cert_map)
                    else:
                        out = py_create_p12(base_dir, cn, password, cert_map)
                    created_files.append(out)
                    results.append({"device": dev, "ok": True, "message": f".p12 aangemaakt: {out.name}"})
                else:
                    pem = create_combined_pem(base_dir, cn, cert_map, engine=engine)
                    pem_files.append(pem)
                    created_files.append(pem)
                    results.append({"device": dev, "ok": True, "message": f"PEM aangemaakt: {pem.name}"})

            except Exception as e:
                logger.error("[VOICA1] process error for %r: %s", dev, e)
                logger.debug(traceback.format_exc())
                msg = str(e) if not debug_enabled else (str(e) + "\n" + traceback.format_exc())
                results.append({"device": dev, "ok": False, "message": msg})

        zip_path_str = None
        if device_type == "ip_phone" and pem_files:
            try:
                zip_path = zip_pems(base_dir, pem_files, password)
                if zip_path:
                    created_files.append(zip_path)
                    zip_path_str = str(zip_path)
            except Exception as e:
                logger.error("[VOICA1] zip failed: %s", e)
                logger.debug(traceback.format_exc())
                results.append({"device": "(zip)", "ok": False, "message": str(e)})

        # mail texts
        certmail_template = load_message_block(MESSAGES_PATH, "CERTMAIL")
        ots_template = load_message_block(MESSAGES_PATH, "OTS")
        wa_template = load_message_block(MESSAGES_PATH, "WA")
        signal_template = load_message_block(MESSAGES_PATH, "SIGNAL")

        certmail_text = render_template_text(certmail_template, devices_str, password)
        ots_text = render_template_text(ots_template, devices_str, password)
        wa_text = render_template_text(wa_template, devices_str, password)
        signal_text = render_template_text(signal_template, devices_str, password)

        # batch log
        try:
            write_batch_log(base_dir, device_type, password, created_files)
        except Exception as e:
            logger.error("[VOICA1] write_batch_log failed: %s", e)
            logger.debug(traceback.format_exc())

        return _render(
            error=error,
            base_dir=str(base_dir),
            device_type=device_type,
            key_size=key_size,
            devices_input="\n".join(devices),
            devices_hidden=devices_hidden,
            step1_done=True,
            step2_done=True,
            devices_list=devices,
            cns=cns,
            devices_str=devices_str,
            password=password,
            results=results,
            zip_path=zip_path_str,
            certmail_text=certmail_text,
            ots_text=ots_text,
            wa_text=wa_text,
            signal_text=signal_text,
            missing_certs=missing_certs,
            engine=engine,
            debug_enabled=debug_enabled,
        )


# =========================
# Standalone run
# =========================

if __name__ == "__main__":
    import json

    settings = cynit_theme.load_settings()
    tools_cfg = cynit_theme.load_tools()
    tools = tools_cfg.get("tools", [])

    cfg_path = CONFIG_DIR / "voica1.json"
    if cfg_path.exists():
        voica_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        voica_cfg = {}

    app = Flask(__name__)
    register_web_routes(app, settings, tools, voica_cfg)
    app.run(host="127.0.0.1", port=5445, debug=True)
