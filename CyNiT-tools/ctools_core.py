#!/usr/bin/env python3
"""
ctools_core.py

Core routes van de CyNiT Tools hub:

- before_request: request teller voor /metrics
- /restart        : reload settings/tools via callback
- /health         : simpele healthcheck
- /metrics        : Prometheus-achtige tekst
- /               : homepage met tool-cards
- /logo.png       : logo naast ctools.py
- /start/         : GUI-tools starten
- /debug/routes   : lijst van alle geregistreerde routes
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from flask import (
    Blueprint,
    render_template_string,
    request,
    redirect,
    url_for,
    send_from_directory,
    g,
)

import cynit_layout

bp = Blueprint("cynit_core", __name__)

# Globals die we invullen via register_core_routes(...)
SETTINGS: Dict[str, Any] = {}
TOOLS: List[Dict[str, Any]] = []
DEV_MODE: bool = False
BASE_DIR: Path = Path(".")
START_TIME: float = time.time()
REQUEST_COUNT: int = 0
RELOAD_CALLBACK: Optional[Callable[[], None]] = None
APP = None  # referentie naar Flask app voor /debug/routes


# ===== HOME TEMPLATE =====

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
    position: relative;
    background: #111111;
    border-radius: 16px;
    padding: 16px;
    box-shadow:
      0 0 0 1px rgba(0, 255, 0, 0.05),
      0 10px 30px rgba(0, 0, 0, 0.85);
    transform: translateY(0) translateZ(0);
    transition:
      transform 0.2s ease-out,
      box-shadow 0.2s ease-out,
      border-color 0.2s ease-out,
      background 0.2s;
    border: 1px solid #222222;
    overflow: hidden;
  }

  .tool-card::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at top left, rgba(0, 255, 128, 0.12), transparent 60%);
    opacity: 0;
    transition: opacity 0.2s ease-out;
    pointer-events: none;
  }

  .tool-card:hover {
    transform: translateY(-4px) translateZ(0);
    box-shadow:
      0 0 0 1px rgba(0, 255, 0, 0.15),
      0 20px 45px rgba(0, 0, 0, 0.9);
    border-color: rgba(0, 255, 0, 0.5);
    background: #111818;
  }

  .tool-card:hover::before {
    opacity: 1;
  }

  .tool-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .tool-icon {
    font-size: 1.8rem;
  }

  .tool-title {
    font-size: 1.1rem;
    font-weight: bold;
    color: {{ colors.title }};
  }

  .tool-badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 4px;
    font-size: 0.7rem;
  }

  .tool-badge {
    border-radius: 999px;
    border: 1px solid rgba(0, 170, 255, 0.7);
    padding: 2px 6px;
    color: rgba(180, 235, 255, 0.95);
    background: rgba(0, 0, 0, 0.7);
  }

  .tool-badge.dev-only {
    border-color: rgba(255, 215, 0, 0.8);
    color: rgba(255, 235, 175, 0.95);
  }

  .tool-badge.hidden {
    border-color: rgba(180, 180, 180, 0.8);
    color: rgba(230, 230, 230, 0.95);
  }

  .tool-badge.local {
    border-color: rgba(180, 180, 180, 0.9);
    color: rgba(230, 230, 230, 0.96);
  }

  .tool-badge.ctools {
    border-color: rgba(0, 255, 128, 0.9);
    color: rgba(210, 255, 230, 0.96);
  }

  .tool-body {
    font-size: 0.9rem;
    color: {{ colors.general_fg }};
    margin-bottom: 12px;
  }

  .tool-footer {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
  }

  .tool-btn {
    background: {{ colors.button_bg }};
    color: {{ colors.button_fg }};
    border-radius: 999px;
    border: 1px solid rgba(0, 255, 170, 0.4);
    padding: 6px 12px;
    font-size: 0.85rem;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    text-decoration: none;
    cursor: pointer;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.8);
  }

  .tool-btn:hover {
    background: #1a2933;
    box-shadow:
      0 0 0 1px rgba(0, 255, 170, 0.35),
      0 10px 26px rgba(0, 0, 0, 0.9);
  }

  .muted {
    color: #aaaaaa;
    font-size: 0.9rem;
  }

  .dev-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border-radius: 999px;
    padding: 2px 8px;
    border: 1px solid rgba(255, 215, 0, 0.8);
    color: rgba(255, 235, 175, 0.98);
    background: rgba(80, 70, 0, 0.35);
    font-size: 0.8rem;
  }

  .dev-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ffd700;
    box-shadow: 0 0 6px rgba(255, 215, 0, 0.8);
  }
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
          Eén centrale plek voor al je certificate-, VOICA-, export- en helper-tools.
        </p>
      </div>
      <div>
        {% if dev_mode %}
          <div class="dev-chip">
            <div class="dev-dot"></div>
            <span>DEV mode actief</span>
          </div>
        {% endif %}
      </div>
    </div>

    <div class="tools-section">
      <h2>Beschikbare tools</h2>
      <div class="tools-grid">
        {% for tool in tools %}
          {% if not tool.hidden or dev_mode %}
            <div class="tool-card {% if tool.hidden %}disabled{% endif %}">
              {% if tool.type == 'web' and tool.web_path %}
                <a class="card-click-overlay" href="{{ tool.web_path }}"></a>
              {% endif %}
              <div class="card-inner">
                <div class="tool-header">
                  <div class="tool-icon">
                    {{ tool.icon_web or tool.icon_gui or "🛠️" }}
                  </div>
                  <div>
                    <div class="tool-title">{{ tool.name }}</div>
                    <div class="tool-badges">
                      {% if tool.type == 'web' %}
                        <span class="tool-badge local">Web</span>
                      {% elif tool.type == 'gui' %}
                        <span class="tool-badge local">GUI</span>
                      {% elif tool.type == 'web+gui' %}
                        <span class="tool-badge local">Web + GUI</span>
                      {% endif %}
                      {% if tool.ctools %}
                        <span class="tool-badge ctools">Hub helper</span>
                      {% endif %}
                      {% if tool.dev_only %}
                        <span class="tool-badge dev-only">Dev only</span>
                      {% endif %}
                      {% if tool.hidden %}
                        <span class="tool-badge hidden">Hidden</span>
                      {% endif %}
                    </div>
                  </div>
                </div>
                <div class="tool-body">
                  {{ tool.description or "Geen beschrijving." }}
                </div>
                <div class="tool-footer">
                  {% if tool.type in ('web', 'web+gui') and tool.web_path %}
                    <a class="tool-btn" href="{{ tool.web_path }}">
                      <span>🌐</span>
                      <span>Open Web</span>
                    </a>
                  {% endif %}
                  {% if tool.type in ('gui', 'web+gui') %}
                    <form method="post" action="/start/">
                      <input type="hidden" name="tool_id" value="{{ tool.id }}">
                      <button type="submit" class="tool-btn">
                        <span>🖥️</span>
                        <span>Start GUI</span>
                      </button>
                    </form>
                  {% endif %}
                </div>
              </div>
            </div>
          {% endif %}
        {% endfor %}
      </div>
    </div>
  </div>
  {{ footer|safe }}
</body>
</html>
"""


# ===== helpers =====

def _find_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    for t in TOOLS:
        if t.get("id") == tool_id:
            return t
    return None


def _start_gui_tool(tool: Dict[str, Any]) -> None:
    script = tool.get("script")
    if not script:
        return
    try:
        subprocess.Popen([sys.executable, script], cwd=str(BASE_DIR))
    except Exception as exc:
        print("[ERROR] Kon GUI-tool niet starten:", exc)


# ===== hooks =====

@bp.before_app_request
def _track_request():
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    g.request_started = time.time()


# ====== routes ======

@bp.route("/restart")
def restart():
    """
    Reload settings/tools via callback uit ctools.py
    """
    if RELOAD_CALLBACK is not None:
        RELOAD_CALLBACK()
    return "OK"


@bp.route("/health")
def health():
    uptime = time.time() - START_TIME
    data = {
        "status": "ok",
        "uptime_seconds": round(uptime, 2),
        "dev_mode": DEV_MODE,
        "tools_loaded": len(TOOLS),
    }
    return data, 200


@bp.route("/metrics")
def metrics():
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


@bp.route("/", methods=["GET"])
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


@bp.route("/logo.png")
def logo_png():
    return send_from_directory(str(BASE_DIR), "logo.png")


@bp.route("/start/", methods=["POST"])
def start_tool():
    tool_id = request.form.get("tool_id", "").strip()
    tool = _find_tool_by_id(tool_id)
    if tool is None:
        return redirect(url_for("cynit_core.index"))

    if tool.get("type") in ("gui", "web+gui"):
        _start_gui_tool(tool)

    return redirect(url_for("cynit_core.index"))


@bp.route("/debug/routes")
def debug_routes():
    if APP is None:
        return "<p>APP niet ingesteld</p>", 500
    output = ["<h1>Registered Routes</h1><ul>"]
    for rule in APP.url_map.iter_rules():
        output.append(f"<li>{rule}</li>")
    output.append("</ul>")
    return "\n".join(output)


def register_core_routes(
    app,
    settings: Dict[str, Any],
    tools: List[Dict[str, Any]],
    dev_mode: bool,
    base_dir: Path,
    reload_callback: Optional[Callable[[], None]] = None,
) -> None:
    """
    Wordt vanuit ctools.py aangeroepen.
    """
    global SETTINGS, TOOLS, DEV_MODE, BASE_DIR, START_TIME, REQUEST_COUNT, RELOAD_CALLBACK, APP
    SETTINGS = settings
    TOOLS = tools
    DEV_MODE = dev_mode
    BASE_DIR = base_dir
    START_TIME = time.time()
    REQUEST_COUNT = 0
    RELOAD_CALLBACK = reload_callback
    APP = app

    app.register_blueprint(bp)
