#!/usr/bin/env python3
"""
voica1.py

VOICA1 device certificaten-tool voor CyNiT Tools.

- Standalone web:  python voica1.py  -> http://127.0.0.1:5445/voica1
- In CyNiT hub:    import voica1; voica1.register_web_routes(app, settings, tools, voica_cfg)
"""

from __future__ import annotations

import string
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, request, render_template_string
import cynit_theme
import cynit_layout

# ===== CONFIG DEFAULTS (kunnen overschreven worden door voica_cfg) =====
OPENSSL_BIN = "openssl"
PASS_LENGTH = 24         # wordt overschreven door voica_cfg["pass_length"] indien aanwezig
KEY_SIZE_DEFAULT = 2048  # idem door voica_cfg["default_key_size"]
CERT_EXTS = (".cer", ".crt", ".pem")


# ===== HELPER FUNCTIES =====

class CommandError(Exception):
    """Fout bij extern commando (openssl, ...)."""
    pass


def run_cmd(cmd, cwd=None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CommandError(
            f"Commando gefaald: {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def generate_password(length: int = PASS_LENGTH) -> str:
    """
    Sterk wachtwoord:
    - minstens 1 kleine letter, 1 hoofdletter, 1 cijfer, 1 symbool
    - eerste en laatste teken zijn NOOIT een symbool
    """
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%&*()-_=+;[{}]:,.<>?/"

    all_chars = lower + upper + digits + symbols
    non_symbols = lower + upper + digits

    while True:
        pwd = [
            secrets.choice(lower),
            secrets.choice(upper),
            secrets.choice(digits),
            secrets.choice(symbols),
        ]
        pwd += [secrets.choice(all_chars) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)

        # eerste/laatste mag geen symbool zijn
        if pwd[0] in symbols or pwd[-1] in symbols:
            continue
        # er moet minstens 1 symbool zitten in de middle
        if not any(ch in symbols for ch in pwd[1:-1]):
            continue
        # eerste/laatste moeten echt letter/cijfer zijn
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


def parse_cert_cn(cert_path: Path) -> Optional[str]:
    """
    Lees CN uit een .cer/.crt/.pem via openssl x509 -subject.
    """
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


def map_certs_by_cn(base_dir: Path) -> Dict[str, Path]:
    """
    Scan map op mogelijke certificaatbestanden (.cer/.crt/.pem) en bouw mapping CN -> path.
    - negeer key/CSR/p12/zip/combined.
    """
    mapping: Dict[str, Path] = {}

    for p in base_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name

        if name.endswith(".key.pem"):
            continue
        if name.endswith(".csr"):
            continue
        if name.endswith(".p12") or name.endswith(".pfx"):
            continue
        if name.endswith(".zip"):
            continue
        if name.endswith(".combined.pem"):
            continue

        if not name.lower().endswith(CERT_EXTS):
            continue

        cn = parse_cert_cn(p)
        if not cn:
            continue
        if cn not in mapping:
            mapping[cn] = p

    return mapping


def create_key_and_csr(base_dir: Path, cn: str, key_size: int) -> None:
    """
    Maak RSA key + CSR, beide in dezelfde map, PEM formaat.
    Output:
      CN.key.pem
      CN.csr
    """
    key_path = base_dir / f"{cn}.key.pem"
    csr_path = base_dir / f"{cn}.csr"

    cmd_key = [OPENSSL_BIN, "genrsa", "-out", str(key_path), str(key_size)]
    run_cmd(cmd_key)

    cmd_csr = [
        OPENSSL_BIN,
        "req",
        "-new",
        "-key",
        str(key_path),
        "-subj",
        f"/CN={cn}",
        "-out",
        str(csr_path),
        "-sha256",
    ]
    run_cmd(cmd_csr)


def create_p12(base_dir: Path, cn: str, password: str, cert_map: Dict[str, Path]) -> Path:
    """
    PC/VM:
      CN.key.pem + CN.csr + cert -> CN.p12 (PKCS#12)
    """
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

    cmd = [
        OPENSSL_BIN,
        "pkcs12",
        "-export",
        "-inkey",
        str(key_path),
        "-in",
        str(cert_path),
        "-out",
        str(p12_path),
        "-passout",
        f"pass:{password}",
    ]
    run_cmd(cmd)
    return p12_path


def create_combined_pem(base_dir: Path, cn: str, cert_map: Dict[str, Path]) -> Path:
    """
    Phone:
      CN.key.pem + CN.csr + cert -> CN.pem (private key + cert)
    """
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
    key = key_path.read_text()
    cert = cert_path.read_text()
    combined = key.rstrip() + "\n" + cert.strip() + "\n"
    combined_path.write_text(combined)
    return combined_path


def zip_pems(base_dir: Path, pem_files: List[Path], password: Optional[str]) -> Optional[Path]:
    """
    Zip alle phone-PEMs:
      - naam = mapnaam.zip
      - wachtwoord = batch-wachtwoord (AES-zip als pyzipper beschikbaar)
    """
    if not pem_files:
        return None

    zip_name = f"{base_dir.name}.zip"
    zip_path = base_dir / zip_name

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
    except Exception:
        import zipfile

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in pem_files:
                zf.write(f, arcname=f.name)

    return zip_path


# ===== TEMPLATE-HELPERS (voica1_messages.md) =====

def load_message_block(path: Path, block_name: str) -> str:
    """
    Leest een block uit voica1_messages.md zoals:

    [[CERTMAIL]]
    ...
    [[END]]
    """
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
    """
    Vervangt placeholders {{devices}} en {{password}}.
    """
    if not template:
        return ""
    return (
        template
        .replace("{{devices}}", devices)
        .replace("{{password}}", password)
    )


# ===== WEB-INTEGRATIE =====

def register_web_routes(app: Flask, settings: dict, tools=None, voica_cfg=None) -> None:
    """
    Registreert /voica1 en /voica1/process in een bestaande Flask-app.
    Gebruikt cynit_layout header/footer/wafel/menu en kleuren uit settings.
    """
    global OPENSSL_BIN, PASS_LENGTH, KEY_SIZE_DEFAULT

    if voica_cfg is None:
        voica_cfg = {}

    # overrides uit config/voica1.json
    OPENSSL_BIN = voica_cfg.get("openssl_bin", OPENSSL_BIN)
    PASS_LENGTH = int(voica_cfg.get("pass_length", PASS_LENGTH))
    KEY_SIZE_DEFAULT = int(voica_cfg.get("default_key_size", KEY_SIZE_DEFAULT))

    def compute_default_base_dir() -> str:
        """
        Bouwt standaard pad als:
        root\\YYYY\\MM\\D
        """
        root = voica_cfg.get("root_base_dir") or voica_cfg.get("default_base_dir", "")
        if not root:
            return ""
        today = datetime.now()
        year = today.year
        month = f"{today.month:02d}"
        day = today.day
        return str(Path(root) / str(year) / month / str(day))

    messages_path = Path(__file__).parent / "config" / "voica1_messages.md"

    base_css = cynit_layout.common_css(settings)
    common_js = cynit_layout.common_js()

    colors_cfg = settings.get("colors", {})
    accent_bg = colors_cfg.get("button_bg", "#facc15")
    accent_fg = colors_cfg.get("button_fg", "#000000")

    extra_css = f"""
.card {{
  max-width: 1000px;
  margin: 0 auto 20px auto;
  background: #1e1e1e;
  padding: 20px;
  border-radius: 16px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.6);
}}
label {{ display:block; margin-top:12px; font-weight:600; }}
input[type=text], textarea, select {{
  width:100%; padding:8px 10px;
  border-radius:8px; border:1px solid #444;
  background:#111; color:#eee;
}}
textarea {{ min-height:80px; font-family:monospace; }}
.btn {{
  display:inline-block;
  margin-top:16px;
  padding:8px 16px;
  border-radius:999px;
  border:none;
  background: {accent_bg};
  color: {accent_fg};
  font-weight:700;
  cursor:pointer;
}}
.btn:hover {{
  filter: brightness(1.05);
}}
#progress-container {{
  width:100%;
  height:10px;
  border-radius:999px;
  background:#111;
  overflow:hidden;
  margin:8px 0 4px 0;
}}
#progress-bar {{
  height:100%;
  width:0%;
  background:{accent_fg};
  transition: width 0.3s ease-out;
}}
.muted {{ color:#aaa; font-size:0.9em; }}
.flash {{ background:#7f1d1d; color:#fecaca;
         padding:8px 12px; border-radius:8px; margin-bottom:8px; }}
.ok {{ color:#bbf7d0; }}
.err {{ color:#fecaca; }}
"""

    js_helpers = """
async function copyText(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const txt = el.value;
  try {
    await navigator.clipboard.writeText(txt);
  } catch (e) {
    el.select();
    document.execCommand("copy");
  }
}

function updatePwText() {
  const kanaal = document.querySelector('input[name="kanaal"]:checked');
  if (!kanaal) return;
  const v = kanaal.value;
  const ots = {{ ots_text | tojson }};
  const wa = {{ wa_text | tojson }};
  const sig = {{ signal_text | tojson }};
  const el = document.getElementById("pw_text");
  if (!el) return;
  if (v === "OTS") el.value = ots;
  else if (v === "WA") el.value = wa;
  else el.value = sig;
}

function initProgress() {
  const container = document.getElementById("progress-container");
  const bar = document.getElementById("progress-bar");
  const text = document.getElementById("progress-text");
  if (!container || !bar || !text) return;
  const total = parseInt(container.getAttribute("data-total") || "0");
  const processed = parseInt(container.getAttribute("data-processed") || "0");
  if (!total) return;
  text.textContent = processed + "/" + total + " devices verwerkt";
  let current = 0;
  const target = Math.round((processed / total) * 100);
  const interval = setInterval(function() {
    current += 5;
    if (current >= target) {
      current = target;
      clearInterval(interval);
    }
    bar.style.width = current + "%";
  }, 30);
}

document.addEventListener("DOMContentLoaded", function() {
  initProgress();
  updatePwText();
});
"""

    header = cynit_layout.header_html(
        settings,
        tools=tools,
        title="CyNiT VOICA1 Device Certs",
        right_html="",
    )
    footer = cynit_layout.footer_html()

    page_template = (
        "<!doctype html>\n"
        "<html lang='nl'>\n"
        "<head>\n"
        "  <meta charset='utf-8'>\n"
        "  <title>CyNiT VOICA1 Tool</title>\n"
        "  <style>\n"
        f"{base_css}\n{extra_css}\n"
        "  </style>\n"
        "  <script>\n"
        f"{common_js}\n{js_helpers}\n"
        "  </script>\n"
        "</head>\n"
        "<body>\n"
        f"{header}\n"
        "<div class='page'>\n"
        "{% if error %}<div class='flash'>{{ error }}</div>{% endif %}\n"
        "<div class='card'>\n"
        "  <h1>VOICA1 Device certificaten</h1>\n"
        "  <p class='muted'>Per device een eigen key + CSR. "
        "Phones → gecombineerde PEM + ZIP, PCs/VMs → PKCS#12 .p12.</p>\n"
        "  <form method='post' action='{{ url_for(\"voica1_generate\") }}'>\n"
        "    <label>Map (volledig pad)</label>\n"
        "    <input type='text' name='base_dir' value='{{ base_dir or \"\" }}' required>\n"
        "    <label>Type devices</label>\n"
        "    <select name='device_type'>\n"
        "      <option value='pc' {% if device_type == 'pc' %}selected{% endif %}>"
        "PC / VM (*.alfa.top.vlaanderen.be)</option>\n"
        "      <option value='ip_phone' {% if device_type == 'ip_phone' %}selected{% endif %}>"
        "IP-telefoon (Pxxxxx@gidphones.vlaanderen.be)</option>\n"
        "    </select>\n"
        "    <label>Key size</label>\n"
        "    <label><input type='radio' name='key_size' value='2048' "
        "{% if key_size == 2048 %}checked{% endif %}> 2048 bits</label>\n"
        "    <label><input type='radio' name='key_size' value='4096' "
        "{% if key_size == 4096 %}checked{% endif %}> 4096 bits</label>\n"
        "    <label>Devices (één per lijn)</label>\n"
        "    <textarea name='devices' "
        "placeholder='S343880&#10;VM123456&#10;P602233'>{{ devices_input or \"\" }}</textarea>\n"
        "    <p class='muted'>PCs/VMs: S-nummer / VM-naam / M-naam / 7 cijfers. "
        "Phones: P-nummer (domein wordt automatisch toegevoegd).</p>\n"
        "    <button type='submit' class='btn'>Stap 1 – Maak keys &amp; CSRs</button>\n"
        "  </form>\n"
        "</div>\n"
        "{% if step1_done %}\n"
        "<div class='card'>\n"
        "  <h2>Stap 1 – Resultaat</h2>\n"
        "  <p><strong>Map:</strong> {{ base_dir }}</p>\n"
        "  <p><strong>Type:</strong> "
        "{% if device_type == 'pc' %}PC / .p12{% else %}IP-telefoon / .pem + ZIP{% endif %}</p>\n"
        "  <p><strong>Key size:</strong> {{ key_size }} bits</p>\n"
        "  <h3>Batch-wachtwoord</h3>\n"
        "  <textarea id='pwd' rows='1' readonly>{{ password }}</textarea>\n"
        "  <button type='button' class='btn' onclick='copyText(\"pwd\")'>Kopieer wachtwoord</button>\n"
        "  <h3>Devices</h3>\n"
        "  <ul>\n"
        "  {% for d in devices_list %}\n"
        "    <li>{{ d }} → CN: {{ cns[d] }}</li>\n"
        "  {% endfor %}\n"
        "  </ul>\n"
        "  <h3>Devices-string</h3>\n"
        "  <textarea id='devs' rows='2' readonly>{{ devices_str }}</textarea>\n"
        "  <button type='button' class='btn' onclick='copyText(\"devs\")'>Kopieer devices-string</button>\n"
        "  <p class='muted'>In de map staan nu per device "
        "<code>CN.key.pem</code> en <code>CN.csr</code> (PEM). "
        "Gebruik deze CSR's in AEG en sla de .CER per device in dezelfde map op.</p>\n"
        "  <form method='post' action='{{ url_for(\"voica1_process\") }}'>\n"
        "    <input type='hidden' name='base_dir' value='{{ base_dir }}'>\n"
        "    <input type='hidden' name='device_type' value='{{ device_type }}'>\n"
        "    <input type='hidden' name='key_size' value='{{ key_size }}'>\n"
        "    <input type='hidden' name='devices' value='{{ devices_hidden }}'>\n"
        "    <input type='hidden' name='password' value='{{ password }}'>\n"
        "    <button type='submit' class='btn'>Stap 2 – Verwerk certificaten</button>\n"
        "  </form>\n"
        "</div>\n"
        "{% endif %}\n"
        "{% if step2_done %}\n"
        "<div class='card'>\n"
        "  <h2>Stap 2 – Verwerking</h2>\n"
        "  <p><strong>Map:</strong> {{ base_dir }}</p>\n"
        "  <div id='progress-container' data-total='{{ results|length }}' "
        "data-processed='{{ results|length }}'>\n"
        "    <div id='progress-bar'></div>\n"
        "  </div>\n"
        "  <p id='progress-text' class='muted'></p>\n"
        "  <h3>Resultaten per device</h3>\n"
        "  <ul>\n"
        "  {% for r in results %}\n"
        "    <li>{% if r.ok %}<span class='ok'>[OK]</span>{% else %}"
        "<span class='err'>[FOUT]</span>{% endif %} "
        "{{ r.device }} – {{ r.message }}</li>\n"
        "  {% endfor %}\n"
        "  </ul>\n"
        "  {% if missing_certs %}\n"
        "  <h3>Ontbrekende certificaten</h3>\n"
        "  <p class='err'>Voor de volgende devices werd geen .CER/.CRT/.PEM gevonden in de map:</p>\n"
        "  <ul>\n"
        "  {% for mc in missing_certs %}\n"
        "    <li>{{ mc.device }} → CN: {{ mc.cn }}</li>\n"
        "  {% endfor %}\n"
        "  </ul>\n"
        "  {% endif %}\n"
        "  {% if zip_path %}\n"
        "  <h3>ZIP-bestand (phones)</h3>\n"
        "  <p>{{ zip_path }}</p>\n"
        "  <p class='muted'>Naam = mapnaam. Wachtwoord = batch-wachtwoord.</p>\n"
        "  {% endif %}\n"
        "  <hr>\n"
        "  <h3>Certificatenmail (certmail)</h3>\n"
        "  <textarea id='certmail' rows='8' readonly>{{ certmail_text }}</textarea>\n"
        "  <button type='button' class='btn' onclick='copyText(\"certmail\")'>"
        "Kopieer cert-mail</button>\n"
        "  <h3 style='margin-top:20px;'>Wachtwoordkanaal</h3>\n"
        "  <p class='muted'>Kies OTS / WhatsApp / Signal en kopieer de tekst.</p>\n"
        "  <label><input type='radio' name='kanaal' value='OTS' checked "
        "onchange='updatePwText()'> OTS</label>\n"
        "  <label><input type='radio' name='kanaal' value='WA' onchange='updatePwText()'> "
        "WhatsApp</label>\n"
        "  <label><input type='radio' name='kanaal' value='SIGNAL' onchange='updatePwText()'> "
        "Signal</label>\n"
        "  <textarea id='pw_text' rows='10' readonly "
        "style='margin-top:8px;'></textarea>\n"
        "  <button type='button' class='btn' onclick='copyText(\"pw_text\")'>"
        "Kopieer wachtwoordtekst</button>\n"
        "  <p class='muted' style='margin-top:16px;'>Teksten komen uit "
        "<code>config/voica1_messages.md</code> (blocks CERTMAIL / OTS / WA / SIGNAL) "
        "met automatisch ingevulde devices en wachtwoord.</p>\n"
        "</div>\n"
        "{% endif %}\n"
        "</div>\n"
        f"{footer}\n"
        "</body>\n"
        "</html>\n"
    )

    def _render(**ctx):
        return render_template_string(page_template, tools=tools, **ctx)

    @app.route("/voica1", methods=["GET"])
    def voica1_index():
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
        )

    @app.route("/voica1/generate", methods=["POST"])
    def voica1_generate():
        base_dir_str = (request.form.get("base_dir") or "").strip()
        device_type = request.form.get("device_type") or "pc"
        key_size_str = request.form.get("key_size") or str(KEY_SIZE_DEFAULT)
        devices_raw = request.form.get("devices") or ""
        error = None

        try:
            key_size = int(key_size_str)
        except ValueError:
            key_size = KEY_SIZE_DEFAULT

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
            )

        password = generate_password()
        cns = {}
        dev_list: List[str] = []

        try:
            for dev in devices:
                dev_id = validate_device_id(dev)
                cn = build_cn(dev_id, device_type)
                cns[dev_id] = cn
                dev_list.append(dev_id)
                create_key_and_csr(base_dir, cn, key_size)
        except Exception as e:
            error = f"Fout bij aanmaken key/CSR: {e}"

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
        )

    @app.route("/voica1/process", methods=["POST"])
    def voica1_process():
        base_dir_str = (request.form.get("base_dir") or "").strip()
        device_type = request.form.get("device_type") or "pc"
        key_size_str = request.form.get("key_size") or str(KEY_SIZE_DEFAULT)
        devices_hidden = request.form.get("devices") or ""
        password = request.form.get("password") or ""
        error = None

        try:
            key_size = int(key_size_str)
        except ValueError:
            key_size = KEY_SIZE_DEFAULT

        base_dir = Path(base_dir_str)
        devices = [line.strip() for line in devices_hidden.splitlines() if line.strip()]

        cns = {d: build_cn(d, device_type) for d in devices}
        devices_str = build_devices_string(devices)

        cert_map = map_certs_by_cn(base_dir)
        results = []
        pem_files: List[Path] = []
        missing_certs = []

        # eerst ontbrekende certificaten bepalen
        for dev in devices:
            cn = build_cn(dev, device_type)
            if cn not in cert_map:
                missing_certs.append({"device": dev, "cn": cn})

        for dev in devices:
            cn = build_cn(dev, device_type)
            try:
                if device_type == "pc":
                    out = create_p12(base_dir, cn, password, cert_map)
                    results.append(
                        {"device": dev, "ok": True, "message": f".p12 aangemaakt: {out.name}"}
                    )
                else:
                    pem = create_combined_pem(base_dir, cn, cert_map)
                    pem_files.append(pem)
                    results.append(
                        {"device": dev, "ok": True, "message": f"PEM aangemaakt: {pem.name}"}
                    )
            except Exception as e:
                results.append({"device": dev, "ok": False, "message": str(e)})

        zip_path = None
        if device_type == "ip_phone" and pem_files:
            zip_path = zip_pems(base_dir, pem_files, password)
            zip_path_str = str(zip_path) if zip_path else None
        else:
            zip_path_str = None

        # --- mailteksten uit voica1_messages.md ---
        certmail_template = load_message_block(messages_path, "CERTMAIL")
        ots_template = load_message_block(messages_path, "OTS")
        wa_template = load_message_block(messages_path, "WA")
        signal_template = load_message_block(messages_path, "SIGNAL")

        certmail_text = render_template_text(certmail_template, devices_str, password)
        ots_text = render_template_text(ots_template, devices_str, password)
        wa_text = render_template_text(wa_template, devices_str, password)
        signal_text = render_template_text(signal_template, devices_str, password)

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
        )


# ===== STANDALONE RUN =====

if __name__ == "__main__":
    # settings & tools uit bestaande CyNiT-theme helpers
    settings = cynit_theme.load_settings()
    tools_cfg = cynit_theme.load_tools()
    tools = tools_cfg.get("tools", [])

    # voica-config uit config/voica1.json
    import json

    cfg_path = Path(__file__).parent / "config" / "voica1.json"
    if cfg_path.exists():
        voica_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        voica_cfg = {}

    app = Flask(__name__)
    register_web_routes(app, settings, tools, voica_cfg)
    app.run(host="127.0.0.1", port=5445, debug=True)
