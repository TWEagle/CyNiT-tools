#!/usr/bin/env python3
"""
config_editor.py

Eenvoudige centrale editor voor:
- config/settings.json
- config/tools.json
- config/exports.json
- config/helpfiles.json
- config/voica1.json
- config/voica1_messages.md
... en alle andere .json/.md/.txt in de config-map.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any

from flask import Blueprint, render_template_string, request, redirect, url_for, flash

import cynit_layout
import cynit_theme

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"

bp = Blueprint("config_editor", __name__)

SETTINGS = cynit_theme.load_settings()
TOOLS_CFG = cynit_theme.load_tools()
TOOLS = TOOLS_CFG.get("tools", [])


TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Config & Theme Editor</title>
  <style>
    {{ base_css|safe }}

    .config-select-row {
      margin-bottom: 12px;
    }

    select.config-select {
      width: 100%;
      padding: 6px 10px;
      border-radius: 6px;
      border: 1px solid #333;
      background: #111;
      color: {{ colors.general_fg }};
      font-family: {{ ui.font_main }};
    }

    textarea.config-editor {
      width: 100%;
      min-height: 420px;
      resize: vertical;
      padding: 10px;
      border-radius: 8px;
      border: 1px solid #333;
      background: #050505;
      color: {{ colors.general_fg }};
      font-family: Consolas, monospace;
      font-size: 0.9rem;
      line-height: 1.4;
      box-sizing: border-box;
    }

    .help-text {
      margin-top: 8px;
      font-size: 0.85rem;
      color: #999;
    }

    .flash {
      margin-bottom: 10px;
      padding: 8px 12px;
      border-radius: 6px;
      background: #112211;
      border: 1px solid #228822;
      color: #88ff88;
      font-size: 0.85rem;
    }

    .flash-error {
      background: #221111;
      border-color: #aa3333;
      color: #ff8888;
    }
  </style>
  <script>
    {{ common_js|safe }}
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <h1>Config & Theme Editor</h1>
    <p class="muted">
      Pas centraal je settings, VOICA1-config en templates aan.
    </p>

    {% for msg, category in flashes %}
      <div class="flash {% if category == 'error' %}flash-error{% endif %}">
        {{ msg }}
      </div>
    {% endfor %}

    <form method="post" action="{{ url_for('config_editor.edit') }}">
      <div class="config-select-row">
        <label for="filename"><strong>Kies bestand</strong></label><br>
        <select id="filename" name="filename" class="config-select" onchange="this.form.submit()">
          {% for f in files %}
            <option value="{{ f.id }}" {% if f.id == current_file %}selected{% endif %}>
              {{ f.label }}
            </option>
          {% endfor %}
        </select>
      </div>

      <textarea name="content" class="config-editor">{{ content }}</textarea>

      <div class="help-text">
        JSON-bestanden worden gevalideerd en mooi ingesprongen opgeslagen.
        Markdown/tekst wordt rechtstreeks bewaard.
      </div>

      <div style="margin-top: 12px;">
        <button type="submit" name="action" value="save" class="btn">
          Opslaan
        </button>
      </div>
    </form>
  </div>
  {{ footer|safe }}
</body>
</html>
"""


def _list_config_files() -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    if not CONFIG_DIR.exists():
        return files

    for p in sorted(CONFIG_DIR.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".json", ".md", ".txt"}:
            continue
        files.append(
            {
                "id": p.name,
                "label": f"{p.name} (config/{p.name})",
            }
        )

    return files


def _read_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception:
        # fallback: binary-ish, maar we proberen toch
        text = path.read_text(errors="ignore")

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            return json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            # is geen geldige JSON, toon dan raw zodat user het kan fixen
            return text
    else:
        return text


def _write_file(path: Path, content: str) -> str | None:
    """
    Schrijft content naar path.
    Returnt None bij succes, of een foutboodschap (string) bij error.
    """
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(content)
        except Exception as exc:
            return f"JSON is niet geldig: {exc}"
        try:
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            path.write_text(pretty, encoding="utf-8")
        except Exception as exc:
            return f"Kon JSON niet opslaan: {exc}"
    else:
        try:
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"Kon bestand niet opslaan: {exc}"

    return None


@bp.route("/config-editor", methods=["GET", "POST"])
def edit():
    colors = SETTINGS.get("colors", {})
    ui = SETTINGS.get("ui", {})
    base_css = cynit_layout.common_css(SETTINGS)
    common_js = cynit_layout.common_js()

    header_html = cynit_layout.header_html(
        SETTINGS,
        tools=TOOLS,
        title="Config & Theme Editor",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    files = _list_config_files()
    if not files:
        # geen configmap of geen files
        return "Geen config-bestanden gevonden in config/."

    # bepaal current_file
    if request.method == "POST":
        current_file = request.form.get("filename") or files[0]["id"]
    else:
        current_file = request.args.get("filename") or files[0]["id"]

    current_path = CONFIG_DIR / current_file
    flashes: List[tuple[str, str]] = []

    if request.method == "POST" and request.form.get("action") == "save":
        content = request.form.get("content", "")
        error = _write_file(current_path, content)
        if error:
            flashes.append((error, "error"))
        else:
            flashes.append((f"{current_file} opgeslagen.", "ok"))

    # altijd opnieuw inlezen (zeker na save)
    content = _read_file(current_path)

    return render_template_string(
        TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        files=files,
        current_file=current_file,
        content=content,
        flashes=flashes,
    )


def register_web_routes(app, settings, tools):
    # settings & tools worden al globaal geladen, maar we laten signatuur zo
    app.register_blueprint(bp)
