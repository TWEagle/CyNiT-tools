#!/usr/bin/env python3
"""
ctools.py

CyNiT Tools webhub:
- Leest tools-config uit config/tools.json (via cynit_theme.load_tools()).
- Homepagina met grid van tools (cards met 3D hover).
- Aantal kolommen instelbaar via settings.json -> home_columns.
- Icons per tool instelbaar via tools.json -> icon_web / icon_gui.
- Web-only tools: volledige card is klikbaar.
- Web+GUI / GUI-tools: aparte knoppen.
- Registreert web-routes van:
  * cert_viewer
  * voica1
  * config_editor
  * dcb_org_export
- /start/ route om GUI-tools te starten (type 'gui' of 'web+gui').
- /yt-launch: PIN-beveiligde launcher voor SP-YT/yt.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import socket
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    send_from_directory,
    session,
    g,
)

import logging

logging.basicConfig(level=logging.DEBUG)

import cynit_theme
import cynit_layout
import cert_viewer
import voica1
import config_editor
import dcb_org_export
import cynit_notify  # nieuwe helper
from cynit_notify import send_signal_message, SignalError

BASE_DIR = Path(__file__).parent
SPYT_DIR = BASE_DIR.parent / "SP-YT"
START_TIME = time.time()
REQUEST_COUNT = 0


# Fallback PIN als er niets in settings.json staat
YTL_PIN_DEFAULT = "3990"


# ===== SETTINGS & TOOLS LADEN =====

SETTINGS: Dict[str, Any] = {}
TOOLS_CFG: Dict[str, Any] = {}
TOOLS: List[Dict[str, Any]] = []
DEV_MODE: bool = False


def get_yt_pin() -> str:
    """
    Haal de YT PIN uit SETTINGS['secrets']['yt_pin'] of SETTINGS['yt_pin'],
    met fallback naar YTL_PIN_DEFAULT.
    """
    global SETTINGS

    if not isinstance(SETTINGS, dict):
        return YTL_PIN_DEFAULT

    cfg_pin = None

    secrets = SETTINGS.get("secrets", {})
    if isinstance(secrets, dict):
        cfg_pin = secrets.get("yt_pin")

    if not cfg_pin:
        cfg_pin = SETTINGS.get("yt_pin")

    if cfg_pin:
        return str(cfg_pin).strip()

    return str(YTL_PIN_DEFAULT)


def reload_config() -> None:
    """
    Herlaad settings.json en tools.json.
    Wordt gebruikt bij startup én door /restart.
    """
    global SETTINGS, TOOLS_CFG, TOOLS, DEV_MODE
    print(">>> RELOADING CONFIG")
    SETTINGS = cynit_theme.load_settings()
    DEV_MODE = bool(SETTINGS.get("dev_mode", False))

    TOOLS_CFG = cynit_theme.load_tools()
    raw_tools = TOOLS_CFG.get("tools", [])

    # Hidden tools alleen tonen in dev_mode
    TOOLS = []
    for t in raw_tools:
        if t.get("hidden") and not DEV_MODE:
            continue
        TOOLS.append(t)


# eerste keer laden bij start
reload_config()

# ===== FLASK-APP =====

app = Flask(__name__)
# Secret key voor sessions (PIN onthouden)
app.secret_key = SETTINGS.get("secret_key", "cynit-dev-key")

# ===== HOME-TEMPLATE =====

HOME_TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>CyNiT Tools</title>
  <style>
  {{ base_css|safe }}

  /* === CyNiT Tools homepage grid === */
  .tools-section {
    margin-top: 32px;
  }

  .tools-grid {
    display: grid;
    grid-template-columns: repeat({{ home_columns }}, minmax(280px, 1fr));
    gap: 20px;
  }

  .tool-card {
    background: #111111;
    border-radius: 16px;
    padding: 16px 20px;
    box-shadow: 0 18px 35px rgba(0, 0, 0, 0.9);
    border: 1px solid rgba(255, 255, 255, 0.03);
    transform: translateY(0) scale(1);
    transition:
      transform 0.18s ease-out,
      box-shadow 0.18s ease-out,
      border-color 0.18s ease-out,
      background 0.18s ease-out;
  }

  .tool-card:hover {
    transform: translateY(-6px) scale(1.01);
    box-shadow: 0 24px 45px rgba(0, 0, 0, 1);
    border-color: rgba(0, 247, 0, 0.35);
    background: #151515;
  }

  /* web-only: volledige card is link */
  .tool-card-link {
    display: block;
    text-decoration: none;
    color: inherit;
    cursor: pointer;
  }

  .tool-card h3 {
    margin: 0 0 8px 0;
    font-size: 1.1rem;
    color: {{ colors.title }};
  }

  .tool-card p {
    margin: 0 0 12px 0;
    color: {{ colors.general_fg }};
    font-size: 0.95rem;
  }

  .tool-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
  }

  .tool-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    border: none;
    background: {{ colors.button_bg }};
    color: {{ colors.button_fg }};
    font-family: {{ ui.font_buttons }};
    font-size: 0.85rem;
    cursor: pointer;
    text-decoration: none;
  }

  .tool-btn:hover {
    filter: brightness(1.15);
  }

  .tool-btn span.icon {
    font-size: 0.95rem;
    line-height: 1;
  }

  .muted {
    color: #999;
    font-size: 0.95rem;
  }

  .page-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 8px;
  }

  .page-header img {
    border-radius: 16px;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.8);
  }

  @media (max-width: 768px) {
    .tools-grid {
      grid-template-columns: 1fr;
    }
  }

  {% if dev_mode %}
  /* Verborgen 'json' easter egg */
  .secret-json {
    color: #00FA00;              /* bijna onzichtbaar op zwarte achtergrond */
    cursor: default;
    transition: color 0.2s ease, transform 0.2s ease;
  }
  .secret-json:hover {
    color: #00FA00;              /* CyNiT groen */
    transform: scale(1.06) rotate(-1deg);
    cursor: pointer;
  }

  /* Sleutel-emoji in de header bij hover */
  .page-header:hover::after {
    content: " 🔑";
    margin-left: 4px;
    font-size: 1.1rem;
    color: #00FA00;
  }
  {% endif %}
  </style>
  <script>
  {{ common_js|safe }}
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Welkom in CyNiT Tools</h1>
        <p class="muted">
          Deze pagina leest automatisch je tools uit
          <code>config/
          {% if dev_mode %}
            <span class="secret-json">tools.json</span>
          {% else %}
            tools.json
          {% endif %}
          </code>.
        </p>
      </div>
    </div>

    <h2>Tools</h2>
    <div class="tools-section">
      <div class="tools-grid">
        {% for tool in tools %}
          {# --- Web-only: volledige card is één <a> --- #}
          {% if tool.type == 'web' and tool.web_path %}
            <a href="{{ tool.web_path }}" class="tool-card tool-card-link">
              <h3>{{ tool.name }}</h3>
              <p>{{ tool.description }}</p>
              <div class="tool-actions">
                <span class="tool-btn">
                  <span class="icon">{{ tool.icon_web or "🌐" }}</span>
                  <span>Open Web</span>
                </span>
              </div>
            </a>

          {# --- Web+GUI of alleen GUI: aparte knoppen --- #}
          {% else %}
            <div class="tool-card">
              <h3>{{ tool.name }}</h3>
              <p>{{ tool.description }}</p>

              <div class="tool-actions">
                {% if tool.type == 'web+gui' %}
                  {% if tool.web_path %}
                    <a class="tool-btn" href="{{ tool.web_path }}">
                      <span class="icon">{{ tool.icon_web or "🌐" }}</span>
                      <span>Open Web</span>
                    </a>
                  {% endif %}
                  <form method="post" action="{{ url_for('start_tool') }}" style="margin:0;">
                    <input type="hidden" name="tool_id" value="{{ tool.id }}">
                    <button type="submit" class="tool-btn">
                      <span class="icon">{{ tool.icon_gui or "🖥️" }}</span>
                      <span>Start GUI</span>
                    </button>
                  </form>
                {% elif tool.type == 'gui' %}
                  <form method="post" action="{{ url_for('start_tool') }}" style="margin:0;">
                    <input type="hidden" name="tool_id" value="{{ tool.id }}">
                    <button type="submit" class="tool-btn">
                      <span class="icon">{{ tool.icon_gui or "🖥️" }}</span>
                      <span>Start GUI</span>
                    </button>
                  </form>
                {% elif tool.type == 'web' and tool.web_path %}
                  {# fallback, zou eigenlijk niet nodig moeten zijn #}
                  <a class="tool-btn" href="{{ tool.web_path }}">
                    <span class="icon">{{ tool.icon_web or "🌐" }}</span>
                    <span>Open Web</span>
                  </a>
                {% endif %}
              </div>
            </div>
          {% endif %}
        {% endfor %}
      </div>
    </div>
  </div>
  {{ footer|safe }}

  {% if dev_mode %}
  <script>
    document.addEventListener("DOMContentLoaded", function () {
      const secretEl = document.querySelector(".secret-json");
      if (secretEl) {
        secretEl.addEventListener("click", function () {
          window.location.href = "/yt-launch";
        });
      }

      // Shortcut: Ctrl+Shift+Y → yt-launch
      document.addEventListener("keydown", function (e) {
        if (e.ctrlKey && e.shiftKey) {
          const key = (e.key || "").toLowerCase();
          if (key === "y") {
            e.preventDefault();
            window.location.href = "/yt-launch";
          }
        }
      });
    });
  </script>
  {% endif %}
</body>
</html>
"""


# ===== HULPFUNCTIES =====

def _find_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    for t in TOOLS:
        if t.get("id") == tool_id:
            return t
    return None


def _start_gui_tool(tool: Dict[str, Any]) -> None:
    """Start een GUI-tool via subprocess (python script)."""
    script_name = tool.get("script")
    if not script_name:
        return
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        print(f"[WARN] Script niet gevonden voor tool {tool.get('id')}: {script_path}")
        return

    try:
        subprocess.Popen([sys.executable, str(script_path)], cwd=str(BASE_DIR))
    except Exception as e:
        print(f"[ERROR] Kon GUI-tool niet starten ({tool.get('id')}): {e}")


# ===== ROUTES =====

@app.before_request
def _track_request():
    """Eenvoudige request-teller voor /metrics."""
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    g.request_started = time.time()

@app.route("/restart")
def restart():
    """
    Wordt aangeroepen door de 'Reload app' knop in de topbar.
    Herlaadt settings.json en tools.json in geheugen.
    """
    reload_config()
    return "OK"

@app.route("/health")
def health():
    """
    Snelle healthcheck: zo licht mogelijk.
    Wordt gebruikt door je PowerShell `ctools`-functie.
    """
    uptime = time.time() - START_TIME
    data = {
        "status": "ok",
        "uptime_seconds": round(uptime, 2),
        "dev_mode": DEV_MODE,
        "tools_loaded": len(TOOLS),
    }
    return data, 200

@app.route("/health/full")
def health_full():
    """
    Uitgebreide healthcheck:
    - controle op config-bestanden
    - SP-YT aanwezigheid
    - DCBaaS API-config
    """
    config_dir = BASE_DIR / "config"

    checks = {}
    overall_ok = True

    def check_json(name, path: Path, required=True):
        nonlocal overall_ok
        if not path.exists():
            state = "missing"
            ok = not required
        else:
            try:
                _ = json.loads(path.read_text(encoding="utf-8"))
                state = "ok"
                ok = True
            except Exception as e:
                state = f"invalid_json: {e}"
                ok = False
        if required and not ok:
            overall_ok = False
        checks[name] = {
            "path": str(path),
            "status": state,
            "required": required,
        }

    # Belangrijkste configs
    check_json("settings.json", config_dir / "settings.json", required=True)
    check_json("tools.json",    config_dir / "tools.json",    required=True)
    check_json("voica1.json",   config_dir / "voica1.json",   required=False)
    check_json("exports.json",  config_dir / "exports.json",  required=False)
    check_json("helpfiles.json",config_dir / "helpfiles.json",required=False)

    # DCBaaS config
    dcbaas_cfg = BASE_DIR / "config" / "dcbaas_api.json"
    if dcbaas_cfg.exists():
        try:
            _ = json.loads(dcbaas_cfg.read_text(encoding="utf-8"))
            checks["dcbaas_api.json"] = {
                "path": str(dcbaas_cfg),
                "status": "ok",
                "required": False,
            }
        except Exception as e:
            checks["dcbaas_api.json"] = {
                "path": str(dcbaas_cfg),
                "status": f"invalid_json: {e}",
                "required": False,
            }
    else:
        checks["dcbaas_api.json"] = {
            "path": str(dcbaas_cfg),
            "status": "missing",
            "required": False,
        }

    # SP-YT aanwezigheid
    yt_script = SPYT_DIR / "yt.py"
    checks["spyt"] = {
        "path": str(yt_script),
        "status": "ok" if yt_script.exists() else "missing",
        "required": False,
    }

    uptime = time.time() - START_TIME
    status = "ok" if overall_ok else "error"

    data = {
        "status": status,
        "uptime_seconds": round(uptime, 2),
        "dev_mode": DEV_MODE,
        "tools_loaded": len(TOOLS),
        "checks": checks,
    }
    http_status = 200 if status == "ok" else 500
    return data, http_status

@app.route("/metrics")
def metrics():
    """
    Eenvoudige Prometheus-achtige metrics.
    Tekst-formaat, zodat bv. Prometheus het kan scrapen.
    """
    uptime = time.time() - START_TIME
    lines = [
        "# HELP cynit_tools_uptime_seconds Uptime van de CyNiT Tools hub in seconden.",
        "# TYPE cynit_tools_uptime_seconds gauge",
        f"cynit_tools_uptime_seconds {uptime:.0f}",
        "",
        "# HELP cynit_tools_requests_total Aantal HTTP requests sinds start.",
        "# TYPE cynit_tools_requests_total counter",
        f"cynit_tools_requests_total {REQUEST_COUNT}",
        "",
        "# HELP cynit_tools_tools_loaded Aantal geladen tools uit tools.json.",
        "# TYPE cynit_tools_tools_loaded gauge",
        f"cynit_tools_tools_loaded {len(TOOLS)}",
        "",
        "# HELP cynit_tools_dev_mode Dev mode actief (1) of niet (0).",
        "# TYPE cynit_tools_dev_mode gauge",
        f"cynit_tools_dev_mode {1 if DEV_MODE else 0}",
    ]
    body = "\n".join(lines) + "\n"
    return body, 200, {"Content-Type": "text/plain; version=0.0.4"}

@app.route("/signal-test", methods=["GET", "POST"])
def signal_test():
    colors = SETTINGS.get("colors", {})
    ui = SETTINGS.get("ui", {})
    base_css = cynit_layout.common_css(SETTINGS)
    common_js = cynit_layout.common_js()
    header_html = cynit_layout.header_html(
        SETTINGS,
        tools=TOOLS,
        title="Signal test",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    msg = ""
    err = None
    ok = None

    if request.method == "POST":
        msg = request.form.get("message", "").strip()
        recips_raw = request.form.get("recipients", "").strip()
        recips = [r.strip() for r in recips_raw.splitlines() if r.strip()]

        try:
            if recips:
                send_signal_message(msg, recips)
            else:
                send_signal_message(msg)
            ok = "Bericht via Signal verzonden."
        except SignalError as e:
            err = str(e)

    template = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Signal Test</title>
  <style>
    {{ base_css|safe }}
    textarea {
      width: 100%;
      min-height: 120px;
      padding: 8px;
      border-radius: 8px;
      border: 1px solid #333;
      background: #050505;
      color: {{ colors.general_fg }};
      font-family: Consolas, monospace;
      font-size: 0.9rem;
    }
    .flash-ok {
      background: #112211;
      border: 1px solid #22aa22;
      padding: 8px 10px;
      border-radius: 6px;
      margin-bottom: 10px;
      color: #bbf7d0;
      font-size: 0.9rem;
    }
    .flash-err {
      background: #221111;
      border: 1px solid #aa3333;
      padding: 8px 10px;
      border-radius: 6px;
      margin-bottom: 10px;
      color: #fecaca;
      font-size: 0.9rem;
    }
  </style>

  <script>
    {{ common_js|safe }}
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <h1>Signal test</h1>
    <p class="muted">
      Verstuur een testbericht via Signal (config uit <code>config/notify.json</code>).
    </p>

    {% if ok %}
      <div class="flash-ok">{{ ok }}</div>
    {% endif %}
    {% if err %}
      <div class="flash-err">{{ err }}</div>
    {% endif %}

    <form method="post">
      <label><strong>Bericht</strong></label><br>
      <textarea name="message">{{ msg }}</textarea>

      <p class="muted" style="margin-top:4px;">
        Laat ontvangers leeg om <code>default_recipients</code> uit notify.json te gebruiken.
      </p>

      <label><strong>Ontvangers (één per lijn, optioneel)</strong></label><br>
      <textarea name="recipients" style="min-height:60px;"></textarea>

      <div style="margin-top:12px;">
        <button type="submit" class="tool-btn">Verstuur via Signal</button>
      </div>
    </form>
  </div>
  {{ footer|safe }}
</body>
</html>
    """

    return render_template_string(
        template,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        msg=msg,
        ok=ok,
        err=err,
    )


@app.route("/", methods=["GET"])
def index():
    colors = SETTINGS.get("colors", {})
    ui = SETTINGS.get("ui", {})

    home_columns = SETTINGS.get("home_columns", 3)
    try:
        home_columns = int(home_columns)
        if home_columns < 1:
            home_columns = 1
        if home_columns > 5:
            home_columns = 5
    except Exception:
        home_columns = 3

    paths = SETTINGS.get("paths", {})
    logo_url = paths.get("logo", "logo.png")

    base_css = cynit_layout.common_css(SETTINGS)
    common_js = cynit_layout.common_js()
    header_html = cynit_layout.header_html(
        SETTINGS,
        tools=TOOLS,
        title="CyNiT Tools",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    return render_template_string(
        HOME_TEMPLATE,
        tools=TOOLS,
        colors=colors,
        ui=ui,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        home_columns=home_columns,
        logo_url=logo_url,
        dev_mode=DEV_MODE,
    )


@app.route("/logo.png")
def logo_png():
    # Serveert het logo naast ctools.py
    return send_from_directory(str(BASE_DIR), "logo.png")


@app.route("/start/", methods=["POST"])
def start_tool():
    tool_id = request.form.get("tool_id", "").strip()
    tool = _find_tool_by_id(tool_id)
    if tool is None:
        return redirect(url_for("index"))

    if tool.get("type") in ("gui", "web+gui"):
        _start_gui_tool(tool)

    return redirect(url_for("index"))


@app.route("/yt-launch", methods=["GET", "POST"])
def yt_launch():
    """
    PIN-beveiligde launcher voor de CyNiT YouTube Converter (SP-YT/yt.py).
    - PIN komt uit settings (secrets.yt_pin of yt_pin) met fallback.
    - PIN wordt in session onthouden (yt_unlocked=True).
    """
    def port_open(host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.3)
                return sock.connect_ex((host, port)) == 0
        except Exception:
            return False

    # Als we al ontgrendeld zijn deze sessie → direct starten/redirect
    if session.get("yt_unlocked") is True and request.method == "GET":
        yt_script = SPYT_DIR / "yt.py"

        if not yt_script.exists():
            return "yt.py niet gevonden", 500

        # Draait YT al?
        if port_open("127.0.0.1", 5555):
            return redirect("http://127.0.0.1:5555")

        # Anders: starten
        subprocess.Popen(
            [sys.executable, str(yt_script)],
            cwd=str(SPYT_DIR),
        )

        start = time.time()
        while time.time() - start < 10:
            if port_open("127.0.0.1", 5555):
                return redirect("http://127.0.0.1:5555")
            time.sleep(0.4)

        return "YT-app start niet correct op.", 500

    # GET → PIN-vraag tonen
    if request.method == "GET":
        return render_template_string("""
        <html><body style="background:#0a0a0a;color:#fff;font-family:system-ui;">
            <div style="max-width:300px;margin:120px auto;text-align:center;">
                <h2 style="margin-bottom:20px;">YT Launcher PIN</h2>
                <form method="POST">
                    <input name="pin" type="password"
                           style="padding:8px;width:100%;border-radius:6px;
                                  border:1px solid #333;background:#111;color:#0f0;font-size:1rem;
                                  text-align:center;letter-spacing:4px;" autofocus>
                    <button style="margin-top:15px;padding:8px 16px;border:0;
                                    border-radius:6px;background:#0f0;color:#000;font-weight:600;">
                        Unlock
                    </button>
                </form>
            </div>
        </body></html>
        """)

    # POST → PIN checken
    pin = (request.form.get("pin") or "").strip()
    if pin != get_yt_pin():
        return "<h3 style='color:red;font-family:system-ui;'>Foute PIN</h3>", 403

    # PIN is ok → onthouden in deze sessie
    session["yt_unlocked"] = True

    # En dan via GET-logica verdergaan (zodat code niet dubbel is)
    return redirect(url_for("yt_launch"))


@app.route("/debug/routes")
def debug_routes():
    output = ["<h1>Registered Routes</h1><ul>"]
    for rule in app.url_map.iter_rules():
        output.append(f"<li>{rule}</li>")
    output.append("</ul>")
    return "\n".join(output)


# ===== EXTERNE TOOL-ROUTES REGISTREREN =====

def register_external_routes(app: Flask) -> None:
    print(">>> REGISTERING ROUTES")

    try:
        print(" - Registering CERT VIEWER...")
        cert_viewer.register_web_routes(app, SETTINGS, TOOLS)
        print("   OK: cert_viewer routes registered")
    except Exception as exc:
        print("   ERROR: cert_viewer.register_web_routes FAILED:")
        print("   -->", exc)

    print(" - Loading voica1.json...")
    voica_cfg_path = BASE_DIR / "config" / "voica1.json"
    try:
        voica_cfg = json.loads(voica_cfg_path.read_text(encoding="utf-8"))
        print("   OK: voica1.json loaded")
    except Exception as exc:
        print("   ERROR: Could not load voica1.json:", exc)
        voica_cfg = {}

    try:
        print(" - Registering VOICA1...")
        voica1.register_web_routes(app, SETTINGS, TOOLS, voica_cfg)
        print("   OK: voica1 routes registered")
    except Exception as exc:
        print("   ERROR: voica1.register_web_routes FAILED:", exc)

    try:
        print(" - Registering CONFIG EDITOR...")
        config_editor.register_web_routes(app, SETTINGS, TOOLS)
        print("   OK: config editor registered")
    except Exception as exc:
        print("   ERROR: config_editor.register_web_routes FAILED:", exc)

    try:
        print(" - Registering DCBAAS ORG EXPORT...")
        dcb_org_export.register_web_routes(app, SETTINGS, TOOLS)
        print("   OK: dcbaas-org-export routes registered")
    except Exception as exc:
        print("   ERROR: dcb_org_export.register_web_routes FAILED:")
        print("   -->", exc)


# ===== MAIN =====

if __name__ == "__main__":
    register_external_routes(app)
    app.run(host="0.0.0.0", port=5000, debug=False)