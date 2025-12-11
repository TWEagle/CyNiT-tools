#!/usr/bin/env python3
"""
useful_links.py

'Nuttige links' pagina voor CyNiT Tools.

Features:
- Links met: id, label, url, info, category.
- Overzicht in tabblad "Links".
- Toevoegen & bewerken in tabblad "Beheer / toevoegen".
- Categorieën:
  * worden mee opgeslagen in config/links.json
  * lijst gesorteerd per categorie + naam
  * bovenaan filterknoppen per categorie (incl. "Alle")
- Acties per link:
  * ✏️ bewerken
  * ✔️ kopiëren
  * 🗑️ verwijderen
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from flask import Blueprint, render_template_string, request, redirect, url_for

import cynit_theme
import cynit_layout

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
LINKS_PATH = CONFIG_DIR / "links.json"

bp = Blueprint("useful_links", __name__)

SETTINGS = cynit_theme.load_settings()
TOOLS_CFG = cynit_theme.load_tools()
TOOLS = TOOLS_CFG.get("tools", [])


DEFAULT_CATEGORY = "Algemeen"


def _ensure_category(link: Dict[str, Any]) -> Dict[str, Any]:
    """
    Zorgt dat elke link een category heeft.
    """
    cat = (link.get("category") or "").strip()
    if not cat:
        cat = DEFAULT_CATEGORY
    link["category"] = cat
    return link


def _default_links() -> Dict[str, Any]:
    return {
        "links": [
            {
                "id": "example",
                "label": "Voorbeeldlink",
                "url": "https://www.vlaanderen.be",
                "info": "Voorbeeld van een nuttige link. Voeg hier je eigen links aan toe.",
                "category": DEFAULT_CATEGORY,
            }
        ]
    }


def _load_links() -> Dict[str, Any]:
    """
    Leest config/links.json, maakt hem aan indien nodig,
    en zorgt dat alle links een category hebben.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not LINKS_PATH.exists():
        data = _default_links()
        LINKS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    try:
        raw = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = _default_links()
        LINKS_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    if "links" not in raw or not isinstance(raw["links"], list):
        raw = _default_links()
        LINKS_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    # categorieën invullen voor oude items
    new_links = []
    changed = False
    for l in raw["links"]:
        before = dict(l)
        l = _ensure_category(l)
        new_links.append(l)
        if l != before:
            changed = True

    raw["links"] = new_links
    if changed:
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

    .card {
      background: #111111;
      border-radius: 16px;
      padding: 16px 20px;
      box-shadow: 0 14px 30px rgba(0, 0, 0, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.05);
      margin-bottom: 20px;
    }

    .category-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }

    .cat-btn {
      border: none;
      border-radius: 999px;
      padding: 4px 12px;
      font-family: {{ ui.font_buttons }};
      font-size: 0.8rem;
      cursor: pointer;
      background: #050505;
      color: {{ colors.general_fg }};
      opacity: 0.75;
      border: 1px solid #222;
      transition: all 0.15s ease-out;
      white-space: nowrap;
    }

    .cat-btn.active {
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      opacity: 1;
      box-shadow: 0 3px 8px rgba(0,0,0,0.8);
      border-color: rgba(0, 247, 0, 0.4);
    }

    .tabs {
      display: inline-flex;
      border-radius: 999px;
      padding: 3px;
      background: #050505;
      border: 1px solid #222;
      margin-bottom: 14px;
    }

    .tab-btn {
      border: none;
      border-radius: 999px;
      padding: 6px 14px;
      font-family: {{ ui.font_buttons }};
      font-size: 0.9rem;
      cursor: pointer;
      background: transparent;
      color: {{ colors.general_fg }};
      opacity: 0.7;
      transition: all 0.15s ease-out;
      white-space: nowrap;
    }

    .tab-btn.active {
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      opacity: 1;
      box-shadow: 0 3px 8px rgba(0,0,0,0.8);
    }

    .tab-pane {
      display: none;
    }

    .tab-pane.active {
      display: block;
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
      min-height: 110px;
      resize: vertical;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 999px;
      border: none;
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      font-family: {{ ui.font_buttons }};
      font-size: 0.9rem;
      cursor: pointer;
      text-decoration: none;
      box-shadow: 0 3px 8px rgba(0,0,0,0.8);
      min-width: 34px;
    }

    .btn-icon {
      font-size: 0.9rem;
      padding-left: 8px;
      padding-right: 8px;
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

    .actions-cell-inner {
      display: flex;
      gap: 4px;
      align-items: center;
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
        console.log("Link gekopieerd:", url);
      } catch (e) {
        console.error("Kon link niet kopiëren:", e);
      }
    }

    document.addEventListener("DOMContentLoaded", function() {
      const tabButtons = document.querySelectorAll(".tab-btn");
      const tabPanes = document.querySelectorAll(".tab-pane");
      const catButtons = document.querySelectorAll(".cat-btn");
      const rows = document.querySelectorAll("tr[data-category]");

      // Tabs wisselen
      tabButtons.forEach(function(btn) {
        btn.addEventListener("click", function() {
          const target = btn.getAttribute("data-tab");
          tabButtons.forEach(b => b.classList.remove("active"));
          tabPanes.forEach(p => p.classList.remove("active"));

          btn.classList.add("active");
          const pane = document.getElementById(target);
          if (pane) {
            pane.classList.add("active");
          }
        });
      });

      // Categorie-filter
      catButtons.forEach(function(btn) {
        btn.addEventListener("click", function() {
          const selected = btn.getAttribute("data-cat");
          catButtons.forEach(b => b.classList.remove("active"));
          btn.classList.add("active");

          rows.forEach(function(row) {
            const rowCat = row.getAttribute("data-category") || "";
            if (selected === "__all__" || rowCat === selected) {
              row.style.display = "";
            } else {
              row.style.display = "none";
            }
          });
        });
      });

      // fallback: minstens 1 tab actief
      if (!document.querySelector(".tab-btn.active") && tabButtons.length > 0) {
        tabButtons[0].classList.add("active");
        const firstTarget = tabButtons[0].getAttribute("data-tab");
        const firstPane = document.getElementById(firstTarget);
        if (firstPane) {
          firstPane.classList.add("active");
        }
      }

      // fallback: minstens 1 category actief
      if (!document.querySelector(".cat-btn.active") && catButtons.length > 0) {
        catButtons[0].classList.add("active");
      }
    });
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <h1>Nuttige links</h1>
    <p class="links-page-intro muted">
      Centrale verzamelplaats van handige URL's (documentatie, dashboards, portalen, ...).<br>
      Klik om te openen in een nieuwe tab of kopieer om te delen met collega's.
    </p>

    {% for msg, category in flashes %}
      <div class="flash {% if category == 'error' %}flash-error{% endif %}">
        {{ msg }}
      </div>
    {% endfor %}

    <div class="card">
      <div class="category-chips">
        <button type="button" class="cat-btn active" data-cat="__all__">Alle</button>
        {% for cat in categories %}
          <button type="button" class="cat-btn" data-cat="{{ cat }}">{{ cat }}</button>
        {% endfor %}
      </div>

      <div class="tabs">
        <button type="button"
                class="tab-btn {% if not edit_link %}active{% endif %}"
                data-tab="tab-links">Overzicht</button>
        <button type="button"
                class="tab-btn {% if edit_link %}active{% endif %}"
                data-tab="tab-manage">Beheer / toevoegen</button>
      </div>

      <!-- TAB 1: alleen de lijst met links -->
      <div id="tab-links" class="tab-pane {% if not edit_link %}active{% endif %}">
        <h2>Links</h2>
        {% if links %}
          <table class="links-list">
            <thead>
              <tr>
                <th style="width: 14%;">Categorie</th>
                <th style="width: 20%;">Naam</th>
                <th style="width: 38%;">URL</th>
                <th>Info</th>
                <th style="width: 1%;">Acties</th>
              </tr>
            </thead>
            <tbody>
              {% for link in links %}
                <tr data-category="{{ link.category }}">
                  <td>{{ link.category }}</td>
                  <td>{{ link.label }}</td>
                  <td>
                    <a href="{{ link.url }}" target="_blank" rel="noopener noreferrer" class="link-url">
                      {{ link.url }}
                    </a>
                  </td>
                  <td>{{ link.info }}</td>
                  <td class="actions-cell">
                    <div class="actions-cell-inner">
                      <!-- Edit -->
                      <a href="{{ url_for('useful_links.links_page', edit=link.id) }}"
                         class="btn btn-icon"
                         title="Bewerk link">
                        ✏️
                      </a>

                      <!-- Copy -->
                      <button type="button"
                              class="btn btn-icon"
                              title="Kopieer URL"
                              onclick="copyLinkToClipboard('{{ link.url }}')">
                        ✔️
                      </button>

                      <!-- Delete -->
                      <form method="post"
                            action="{{ url_for('useful_links.links_page') }}"
                            style="display:inline;">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="link_id" value="{{ link.id }}">
                        <button type="submit"
                                class="btn btn-icon"
                                title="Verwijder link">
                          🗑️
                        </button>
                      </form>
                    </div>
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <p class="muted">
            Er zijn nog geen links geconfigureerd.
            Voeg er eentje toe in het tabblad <strong>Beheer / toevoegen</strong>.
          </p>
        {% endif %}
      </div>

      <!-- TAB 2: formulier om links toe te voegen of te bewerken -->
      <div id="tab-manage" class="tab-pane {% if edit_link %}active{% endif %}">
        {% if edit_link %}
          <h2>Link bewerken</h2>
          <form method="post" action="{{ url_for('useful_links.links_page') }}">
            <input type="hidden" name="action" value="update">
            <input type="hidden" name="link_id" value="{{ edit_link.id }}">
            <div class="links-form-grid">
              <div>
                <label for="label">Naam / label <span class="muted">(verplicht)</span></label>
                <input type="text"
                       id="label"
                       name="label"
                       value="{{ edit_link.label }}"
                       required>
              </div>
              <div>
                <label for="url">URL <span class="muted">(verplicht)</span></label>
                <input type="text"
                       id="url"
                       name="url"
                       value="{{ edit_link.url }}"
                       required>
              </div>
              <div>
                <label for="category">Categorie <span class="muted">(optioneel)</span></label>
                <input type="text"
                       id="category"
                       name="category"
                       value="{{ edit_link.category }}">
              </div>
              <div class="full-row">
                <label for="info">Info / beschrijving <span class="muted">(optioneel)</span></label>
                <textarea id="info"
                          name="info"
                          placeholder="Korte uitleg wat deze link doet of wanneer je hem gebruikt.">{{ edit_link.info }}</textarea>
              </div>
            </div>
            <div style="margin-top: 12px;">
              <button type="submit" class="btn">Wijzigingen opslaan</button>
              <a href="{{ url_for('useful_links.links_page') }}"
                 class="btn"
                 style="margin-left:6px;">Annuleren</a>
            </div>
          </form>
          <p class="muted" style="margin-top:8px;">
            Je bewerkt nu een bestaande link. Alle data wordt opgeslagen in <code>config/links.json</code>.
          </p>
        {% else %}
          <h2>Link toevoegen</h2>
          <form method="post" action="{{ url_for('useful_links.links_page') }}">
            <input type="hidden" name="action" value="add">
            <div class="links-form-grid">
              <div>
                <label for="label">Naam / label <span class="muted">(verplicht)</span></label>
                <input type="text" id="label" name="label" placeholder="Bijv. DCBaaS dashboard" required>
              </div>
              <div>
                <label for="url">URL <span class="muted">(verplicht)</span></label>
                <input type="text" id="url" name="url" placeholder="https://..." required>
              </div>
              <div>
                <label for="category">Categorie <span class="muted">(optioneel, bijv. DCBaaS, VO, Tools)</span></label>
                <input type="text" id="category" name="category" placeholder="Bijv. DCBaaS, VO, Tools">
              </div>
              <div class="full-row">
                <label for="info">Info / beschrijving <span class="muted">(optioneel)</span></label>
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
        {% endif %}
      </div>
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
    links_list = [_ensure_category(l) for l in links_list]

    flashes: List[Tuple[str, str]] = []

    # Bepalen of we in edit-mode zitten (GET ?edit=...)
    edit_id: Optional[str] = request.args.get("edit")
    edit_link: Optional[Dict[str, Any]] = None
    if edit_id:
        for l in links_list:
            if l.get("id") == edit_id:
                edit_link = l
                break

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()

        if action == "add":
            label = (request.form.get("label") or "").strip()
            url = (request.form.get("url") or "").strip()
            info = (request.form.get("info") or "").strip()
            category = (request.form.get("category") or "").strip() or DEFAULT_CATEGORY

            if not label or not url:
                flashes.append(("Naam en URL zijn verplicht.", "error"))
            else:
                new_link = {
                    "id": str(uuid.uuid4()),
                    "label": label,
                    "url": url,
                    "info": info,
                    "category": category,
                }
                links_list.append(new_link)
                data["links"] = links_list
                _save_links(data)
                return redirect(url_for("useful_links.links_page"))

        elif action == "update":
            link_id = (request.form.get("link_id") or "").strip()
            label = (request.form.get("label") or "").strip()
            url = (request.form.get("url") or "").strip()
            info = (request.form.get("info") or "").strip()
            category = (request.form.get("category") or "").strip() or DEFAULT_CATEGORY

            if not label or not url:
                flashes.append(("Naam en URL zijn verplicht.", "error"))
            else:
                updated = False
                new_list = []
                for l in links_list:
                    if l.get("id") == link_id:
                        l["label"] = label
                        l["url"] = url
                        l["info"] = info
                        l["category"] = category
                        updated = True
                    new_list.append(l)
                links_list = new_list
                data["links"] = links_list
                if updated:
                    _save_links(data)
                return redirect(url_for("useful_links.links_page"))

        elif action == "delete":
            link_id = (request.form.get("link_id") or "").strip()
            new_list = [l for l in links_list if l.get("id") != link_id]
            if len(new_list) != len(links_list):
                links_list = new_list
                data["links"] = links_list
                _save_links(data)
            return redirect(url_for("useful_links.links_page"))

    # categorieën + sortering voor render
    categories = sorted({l.get("category", DEFAULT_CATEGORY) for l in links_list})
    links_sorted = sorted(
        links_list,
        key=lambda l: (
            (l.get("category") or DEFAULT_CATEGORY).lower(),
            (l.get("label") or "").lower(),
        ),
    )

    return render_template_string(
        TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        links=links_sorted,
        categories=categories,
        flashes=flashes,
        edit_link=edit_link,
    )


def register_web_routes(app, settings, tools):
    app.register_blueprint(bp)
