#!/usr/bin/env python3
"""
cynit_layout.py

Gemeenschappelijke layout-elementen voor ALLE CyNiT web-UI pagina's
(bv. ctools hub, cert_viewer, toekomstige tools).

Hier definieer je:
- common_css()  : basis CSS (body, topbar, footer, wafel-menu, hamburger-menu)
- header_html() : HTML voor de topbar
- footer_html() : HTML voor de footer
- common_js()   : JavaScript helpers (toggle wafel, restart app)

Belangrijk:
- Kleuren & fonts komen uit settings.json via cynit_theme (profiel-gebonden).
- Als je de algemene look & feel wilt aanpassen voor ALLE pagina's,
  doe je dat bij voorkeur HIER of in settings.json, NIET in elke tool apart.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any

import cynit_theme


def common_css(settings: dict) -> str:
    """
    Basis CSS voor:
    - body: achtergrond, tekstkleur, font
    - topbar: bovenbalk met wafel, logo, titel, rechtsblok
    - page: inhoudsgebied onder de topbar (padding en min-height)
    - footer: onderste balk met copyright
    - wafelmenu: links boven (▦)
    - hamburger-menu: rechts boven (☰), vooral gebruikt voor exports in cert_viewer
    """
    colors = settings["colors"]
    ui = settings["ui"]

    BG = colors["background"]
    FG = colors["general_fg"]
    TITLE = colors["title"]
    BTN_BG = colors["button_bg"]
    BTN_FG = colors["button_fg"]
    logo_h = ui.get("logo_max_height", 80)

    return f"""
    /* === Basis body === */
    body {{
      background: {BG};
      color: {FG};
      font-family: Arial, sans-serif;
      margin: 0;
    }}

    /* === Bovenbalk (topbar) === */
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 16px;
      background: #111111;
      border-bottom: 1px solid #333333;
    }}
    .topbar-left {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .topbar-right {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    /* Logo in de topbar */
    .logo {{
      max-height: {logo_h}px;
    }}

    /* Inhoudsgebied onder de topbar */
    .page {{
      padding: 20px;
      min-height: calc(100vh - 120px);
    }}

    /* Standaard kopteksten */
    h1, h2, h3 {{
      color: {TITLE};
    }}

    /* Footer onderaan de pagina */
    .footer {{
      padding: 8px 16px;
      background: #111111;
      border-top: 1px solid #333333;
      color: {FG};
      font-size: 0.85em;
      text-align: right;
    }}

    /* Algemene label/knop/link stijlen */
    label, button, a {{
      color: {FG};
    }}
    input[type="file"] {{
      color: {FG};
    }}

    button {{
      background: {BTN_BG};
      color: {BTN_FG};
      border: 1px solid {FG};
      padding: 5px 10px;
      cursor: pointer;
      margin-right: 5px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.6);
      border-radius: 4px;
    }}
    button:hover {{
      background: #222222;
    }}

    /* === Wafelmenu links boven === */
    .waffle-wrapper {{
      position: relative;
      display: inline-block;
    }}
    .waffle-icon {{
      width: 26px;
      height: 26px;
      border-radius: 4px;
      border: 1px solid {FG};
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 16px;
      margin-right: 8px;
    }}
    .waffle-dropdown {{
      display: none;
      position: absolute;
      top: 30px;
      left: 0;
      background: #111;
      border: 1px solid #333;
      min-width: 220px;
      z-index: 999;
      border-radius: 4px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.7);
    }}
    .waffle-dropdown a {{
      display: block;
      padding: 6px 10px;
      font-size: 0.9em;
      white-space: nowrap;
      text-decoration: none;
    }}
    .waffle-dropdown a:hover {{
      background: #222;
    }}

    /* === Hamburger menu rechts (exports, opties, ...) === */
    .hamburger-wrapper {{
      position: relative;
      display: inline-block;
    }}
    .hamburger-icon {{
      width: 26px;
      height: 26px;
      border-radius: 4px;
      border: 1px solid {FG};
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 16px;
    }}
    .hamburger-dropdown {{
      display: none;
      position: absolute;
      top: 30px;
      right: 0;
      background: #111;
      border: 1px solid #333;
      min-width: 200px;
      z-index: 999;
      border-radius: 4px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.7);
    }}
    .hamburger-dropdown a {{
      display: block;
      padding: 6px 10px;
      font-size: 0.9em;
      white-space: nowrap;
      text-decoration: none;
    }}
    .hamburger-dropdown a:hover {{
      background: #222;
    }}
    """


def header_html(
    settings: dict,
    tools: Optional[List[Dict[str, Any]]] = None,
    title: str = "CyNiT Tools",
    right_html: str = "",
) -> str:
    """
    Genereert de HTML voor de topbar (bovenbalk).

    We bouwen de wafel-links volledig in Python (NIET met Jinja),
    zodat de string direct in andere templates ingevoegd kan worden.
    """
    # logo-pad uit settings, fallback naar 'logo.png'
    paths = settings.get("paths", {})
    logo_src = paths.get("logo", "logo.png")

    # wafel-links genereren
    links_html = ""
    if tools:
        for t in tools:
            web_path = t.get("web_path")
            if not web_path:
                continue
            name = t.get("name") or t.get("id") or "(tool)"
            links_html += f'<a href="{web_path}">{name}</a>\n'

    return f"""
  <div class="topbar">
    <div class="topbar-left">
      <div class="waffle-wrapper">
        <div class="waffle-icon" onclick="toggleWaffle()">▦</div>
        <div id="waffle-menu" class="waffle-dropdown">
          {links_html}
          <a href="/">🏠 Hub home</a>
          <a href="#" onclick="restartApp(); return false;">🔄 Reload app</a>
        </div>
      </div>
      <a href="/"><img src="{logo_src}" alt="CyNiT Logo" class="logo"></a>
      <span>{title}</span>
    </div>
    <div class="topbar-right">
      {right_html}
    </div>
  </div>
"""


def footer_html() -> str:
    return """
  <div class="footer">
    © CyNiT 2024 - 2026
  </div>
"""


def common_js() -> str:
    return """
    function toggleWaffle() {
      var el = document.getElementById('waffle-menu');
      if (!el) return;
      el.style.display = (el.style.display === 'block') ? 'none' : 'block';
    }

    async function restartApp() {
      try {
        await fetch('/restart');
      } catch (e) {
        // tijdens restart kan de fetch mislukken, is oké
      }
      setTimeout(function() {
        window.location.href = '/';
      }, 1000);
    }
    """
