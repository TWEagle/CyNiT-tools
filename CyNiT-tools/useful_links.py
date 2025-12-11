#!/usr/bin/env python3
"""
useful_links.py

'Nuttige links' pagina voor CyNiT Tools.

- Config in: config/links.json
- Functies:
  * Overzicht van alle links (naam, URL, info)
  * URL's klikbaar (openen in nieuwe tab)
  * Form bovenaan om links toe te voegen
  * Verwijder-knop per link
  * Copy-knop om URL in clipboard te zetten
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Dict, Any

from flask import Blueprint, render_template_string, request, redirect, url_for, flash

import cynit_theme
import cynit_layout

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
LINKS_PATH = CONFIG_DIR / "links.json"

bp = Blueprint("useful_links", __name__)

# We volgen hetzelfde patroon als config_editor.py
SETTINGS = cynit_theme.load_settings()
TOOLS_CFG = cynit_theme.load_tools()
TOOLS = TOOLS_CFG.get("tools", [])


def _default_links() -> Dict[str, Any]:
    """
    Default structuur voor links.json als hij nog niet bestaat.
    """
    return {
        "links": [
            {
                "id": "example",
                "label": "Voorbeeldlink",
                "url": "https://www.vlaanderen.be",
                "info": "Voorbeeld van een nuttige link. Voeg hier je eigen links aan toe."
            }
        ]
    }


def _load_links() -> Dict[str, Any]:
    """
    Leest config/links.json, maakt hem aan indien nodig.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not LINKS_PATH.exists():
        data = _default_links()
        LINKS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    try:
        raw = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        # Bij corrupte JSON: resetten naar default
        raw = _default_links()
        LINKS_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    if "links" not in raw or not isinstance(raw["links"], list):
        raw = _default_links()
        LINKS_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return raw


def _save_links(data: Dict[str, Any]) -> None:
    """
    Schrijft data terug naar config/links.json.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LINKS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Nuttige links - CyNiT Tools</title>
  <style>
    {{ base_css|safe }}

    .links-page-intro {
      margin-bottom: 18px;
    }

    .links-form-card, .links-list-card {
      background: #111111;
      border-radius: 16px;
      padding: 16px 20px;
      box-shadow: 0 14px 30px rgba(0, 0, 0, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.05);
      margin-bottom: 20px;
    }

    .links-form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px 20px;
    }

    .links-form-grid .full-row {
      grid-column: 1 / -1;
    }

    label {
      display: block;
      font-weight: 600;
      margin-bottom: 4px;
    }

    input[type="text"], textarea {
      width: 100%;
      padding: 6px 8px;
      border-radius: 8px;
      border: 1px solid #333;
      background: #050505;
      color: {{ colors.general_fg }};
      font-family: {{ ui.font_main }};
      font-size: 0.9rem;
      box-sizing: border-box;
    }

    textarea {
        min-height: 110px;   /* was 60px */
        resize: vertical;
    }


    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 999px;
      border: none;
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      font-family: {{ ui.font_buttons }};
      font-size: 0.9rem;
      cursor: pointer;
      text-decoration: none;
      box-shadow: 0 3px 8px rgba(0,0,0,0.8);
    }

    .btn:hover {
      filter: brightness(1.12);
    }

    .links-list {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }

    .links-list th, .links-list td {
      border: 1px solid #333;
      padding: 6px 8px;
      vertical-align: top;
    }

    .links-list th {
      background: #181818;
      color: {{ colors.title }};
    }

    .links-list td.actions-cell {
      white-space: nowrap;
    }

    a.link-url {
      color: {{ colors.general_fg }};
      text-decoration: underline;
    }

    a.link-url:hover {
      text-decoration: none;
    }

    .muted {
      color: #999;
      font-size: 0.85rem;
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

    @media (max-width: 900px) {
      .links-form-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
  <script>
    {{ common_js|safe }}

    async function copyLinkToClipboard(url) {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(url);
        } else {
          const tmp = document.createElement("textarea");
          tmp.value = url;
          tmp.style.position = "fixed";
          tmp.style.left = "-1000px";
          document.body.appendChild(tmp);
          tmp.select();
          document.execCommand("copy");
          document.body.removeChild(tmp);
        }
        // optioneel: kleine visuele feedback (console log)
        console.log("Link gekopieerd:", url);
      } catch (e) {
        console.error("Kon link niet kopiëren:", e);
      }
    }
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <h1>Nuttige links</h1>
    <p class="links-page-intro muted">
      Centrale verzamelplaats van handige URL's (documentatie, dashboards, portalen, ...).<br>
      Voeg hier links toe, klik om te openen in een nieuwe tab of kopieer om te delen met collega's.
    </p>

    {% for msg, category in flashes %}
      <div class="flash {% if category == 'error' %}flash-error{% endif %}">
        {{ msg }}
      </div>
    {% endfor %}

    <div class="links-form-card">
      <h2>Nieuwe link toevoegen</h2>
      <form method="post" action="{{ url_for('useful_links.links_page') }}">
        <input type="hidden" name="action" value="add">
        <div class="links-form-grid">
          <div>
            <label for="label">Naam / label</label>
            <input type="text" id="label" name="label" placeholder="Bijv. DCBaaS dashboard" required>
          </div>
          <div>
            <label for="url">URL</label>
            <input type="text" id="url" name="url" placeholder="https://..." required>
          </div>
          <div class="full-row">
            <label for="info">Info / beschrijving</label>
            <textarea id="info" name="info" placeholder="Korte uitleg wat deze link doet of wanneer je hem gebruikt."></textarea>
          </div>
        </div>
        <div style="margin-top: 12px;">
          <button type="submit" class="btn">Link toevoegen</button>
        </div>
      </form>
      <p class="muted" style="margin-top:8px;">
        Alle links worden bewaard in <code>config/links.json</code>.
      </p>
    </div>

    <div class="links-list-card">
      <h2>Overzicht links</h2>
      {% if links %}
        <table class="links-list">
          <thead>
            <tr>
              <th style="width: 20%;">Naam</th>
              <th style="width: 40%;">URL</th>
              <th>Info</th>
              <th style="width: 1%;">Acties</th>
            </tr>
          </thead>
          <tbody>
            {% for link in links %}
              <tr>
                <td>{{ link.label }}</td>
                <td>
                  <a href="{{ link.url }}" target="_blank" rel="noopener noreferrer" class="link-url">
                    {{ link.url }}
                  </a>
                </td>
                <td>{{ link.info }}</td>
                <td class="actions-cell">
                  <button type="button" class="btn" onclick="copyLinkToClipboard('{{ link.url }}')">
                    Kopieer
                  </button>
                  <form method="post" action="{{ url_for('useful_links.links_page') }}" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="link_id" value="{{ link.id }}">
                    <button type="submit" class="btn" style="margin-left:4px;">
                      Verwijder
                    </button>
                  </form>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      {% else %}
        <p class="muted">Er zijn nog geen links geconfigureerd. Voeg er hierboven een toe.</p>
      {% endif %}
    </div>
  </div>
  {{ footer|safe }}
</body>
</html>
"""


@bp.route("/links", methods=["GET", "POST"])
def links_page():
    colors = SETTINGS.get("colors", {})
    ui = SETTINGS.get("ui", {})
    base_css = cynit_layout.common_css(SETTINGS)
    common_js = cynit_layout.common_js()

    header_html = cynit_layout.header_html(
        SETTINGS,
        tools=TOOLS,
        title="Nuttige links",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    data = _load_links()
    links_list: List[Dict[str, Any]] = data.get("links", [])

    flashes: List[tuple[str, str]] = []

    if request.method == "POST":
        action = request.form.get("action", "").strip().lower()

        if action == "add":
            label = (request.form.get("label") or "").strip()
            url = (request.form.get("url") or "").strip()
            info = (request.form.get("info") or "").strip()

            if not label or not url:
                flashes.append(("Naam en URL zijn verplicht.", "error"))
            else:
                new_link = {
                    "id": str(uuid.uuid4()),
                    "label": label,
                    "url": url,
                    "info": info,
                }
                links_list.append(new_link)
                data["links"] = links_list
                _save_links(data)
                flashes.append((f"Link '{label}' toegevoegd.", "ok"))
                # Kleine redirect om F5-resubmit te vermijden
                return redirect(url_for("useful_links.links_page"))

        elif action == "delete":
            link_id = (request.form.get("link_id") or "").strip()
            new_list = [l for l in links_list if l.get("id") != link_id]
            if len(new_list) != len(links_list):
                links_list = new_list
                data["links"] = links_list
                _save_links(data)
                flashes.append(("Link verwijderd.", "ok"))
            else:
                flashes.append(("Link niet gevonden.", "error"))
            return redirect(url_for("useful_links.links_page"))

    return render_template_string(
        TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        links=links_list,
        flashes=flashes,
    )


def register_web_routes(app, settings, tools):
    """
    Wordt aangeroepen door ctools.register_external_routes(app).
    """
    app.register_blueprint(bp)
