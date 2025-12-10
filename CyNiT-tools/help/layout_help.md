# CyNiT Layout & Theming Guide

Dit is een korte uitleg voor mezelf over hoe de layout en theming van **CyNiT Tools** werkt.

## 1. Profielen & kleuren (settings.json)

- Bestand: `config/settings.json`
- Belangrijkste keys:
  - `profiles`: alle beschikbare profielen
  - `active_profile`: het profiel dat nu actief is
  - Per profiel:
    - `colors.background`
    - `colors.general_fg`
    - `colors.title`
    - `colors.table_col1_bg`
    - `colors.table_col1_fg`
    - `colors.table_col2_bg`
    - `colors.table_col2_fg`
    - `colors.button_bg`
    - `colors.button_fg`
    - `ui.logo_max_height`

Hier doe ik **95% van het kleur- en tema-werk**.

## 2. Gemeenschappelijke layout (`cynit_layout.py`)

- Bestand: `cynit_layout.py`
- Functies:
  - `common_css(settings)`: globale CSS voor:
    - body, topbar, footer, page
    - wafelmenu links
    - hamburger-menu rechts
  - `header_html(settings, tools, title, right_html)`:
    - topbar HTML (logo, titel, wafelmenu, rechtsblok)
  - `footer_html()`:
    - standaard footer met © CyNiT 2024 - 2026
  - `common_js()`:
    - `toggleWaffle()` en `restartApp()`

### Wat pas ik hier vooral aan?

- Layout die **voor alle tools** gelijk moet zijn:
  - marges, paddings, hoogte van topbar/page/footer
  - algemene button-style (vorm, shadow, border-radius)
  - gedrag van wafel/hamburger

## 3. Tool-specifieke layout (bijv. cert_viewer, hub)

- Bestanden:
  - `cert_viewer.py`
  - `ctools.py`
- Deze doen:
  - `base_css = cynit_layout.common_css(settings)`
  - daaronder extra CSS die specifiek is:
    - kaarten/tiles in hub (`.cards`, `.card`, ...)
    - tabel-styling in cert_viewer

**Regel:**  
- Globale elementen -> `cynit_layout.py`  
- Tool-specifieke extra's -> in dat tool-bestand zelf (wel met `base_css` erboven).

## 4. Hoe voeg ik een nieuwe tool toe?

1. `config/tools.json` uitbreiden met:
   ```json
   {
     "id": "nieuwe_tool",
     "name": "Nieuwe Tool",
     "type": "web",
     "script": "nieuwe_tool.py",
     "web_path": "/nieuwe_tool",
     "description": "Beschrijving..."
   }
