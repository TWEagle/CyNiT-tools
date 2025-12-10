# cynit_theme.py
import json
from pathlib import Path
from io import BytesIO

from PIL import Image

# Basis paden
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
IMAGES_DIR = BASE_DIR / "images"

SETTINGS_PATH = CONFIG_DIR / "settings.json"
TOOLS_PATH = CONFIG_DIR / "tools.json"
ABOUT_MD = BASE_DIR / "ABOUT.md"
LOGO_PATH = IMAGES_DIR / "CyNiT-Logo.png"

# ➕ nieuw:
HELPFILES_PATH = CONFIG_DIR / "helpfiles.json"


def default_settings() -> dict:
    return {
        "colors": {
            "background": "#000000",
            "general_fg": "#00B7C3",   # appelblauwzeegroen-ish
            "title": "#00A2FF",

            "table_col1_bg": "#FEF102",
            "table_col1_fg": "#000000",

            "table_col2_bg": "#111111",
            "table_col2_fg": "#00B7C3",

            "button_bg": "#000000",
            "button_fg": "#00B7C3",
        },
        "paths": {
            "logo": "images/CyNiT-Logo.png",
            "help": "ABOUT.md",
        },
        "ui": {
            "logo_max_height": 80,
            "font_main": "Consolas",
            "font_buttons": "Segoe UI",
        },
    }


def default_tools() -> dict:
    """
    Beschrijving van tools voor de hub.
    """
    return {
        "tools": [
            {
                "id": "certviewer",
                "name": "Certificate / CSR Viewer",
                "type": "web+gui",
                "script": "cert_viewer.py",
                "web_path": "/cert",
                "description": "Decode X.509 certificaten en CSRs, bekijk subject/issuer/properties en exporteer naar JSON, CSV, XLSX, HTML, MD."
            },
            {
                "id": "jwt2jwk",
                "name": "JWT Builder",
                "type": "gui",
                "script": "JWT2JWK.py",
                "description": "Jouw bestaande JWT tool (JWT2JWK.py)."
            },
            {
                "id": "passgen",
                "name": "Password Generator",
                "type": "gui",
                "script": "passgen1.py",
                "description": "Jouw bestaande password generator GUI."
            }
        ]
    }

def deep_merge(default: dict, override: dict) -> dict:
    out = dict(default)
    for k, v in override.items():
        if isinstance(v, dict) and k in out and isinstance(out[k], dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def default_helpfiles() -> dict:
    """
    Default inhoud voor config/helpfiles.json.
    - 'about' verwijst naar ABOUT.md in de hoofdmap
    - 'layout' verwijst naar config/layout_help.md
    """
    return {
        "helpfiles": [
            {
                "id": "about",
                "name": "About CyNiT Tools",
                "md": "ABOUT.md",
            },
            {
                "id": "layout",
                "name": "Layout & theming",
                "md": "config/layout_help.md",
            },
        ]
    }


def load_helpfiles() -> dict:
    """
    Leest config/helpfiles.json.
    - Bestaat hij niet -> maak aan met defaults.
    - Bij corrupte JSON -> overschrijven met defaults.
    Maakt ook een standaard layout_help.md aan als die nog niet bestaat.
    """
    if not HELPFILES_PATH.exists():
        HELPFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = default_helpfiles()
        HELPFILES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # layout_help.md aanmaken als basis
        layout_md = BASE_DIR / "config" / "layout_help.md"
        if not layout_md.exists():
            layout_md.write_text(
                "# CyNiT layout & theming\n\n"
                "Deze pagina legt in gewone mensentaal uit hoe de layout van CyNiT Tools in elkaar zit.\n\n"
                "## Belangrijkste files\n"
                "- `config/settings.json`: profielen, kleuren, fonts, logo-pad.\n"
                "- `config/exports.json`: opmaak voor Excel/HTML/Markdown exports.\n"
                "- `cynit_layout.py`: gedeelde header/footer/wafel/hamburger CSS & HTML.\n"
                "- `cert_viewer.py`: de Certificate/CSR viewer (web + GUI).\n\n"
                "## Wat pas ik waar aan?\n"
                "- Thema-kleuren: in `config/settings.json` per profiel.\n"
                "- Export-opmaak: in `config/exports.json` (HTML/XLSX/MD blokken).\n"
                "- Layout-structuur (header/footer): in `cynit_layout.py`.\n"
                "\n"
                "Gebruik deze file als intern naslagwerk als je later nog eens wil sleutelen aan de layout.\n",
                encoding="utf-8",
            )

        return data

    try:
        raw = json.loads(HELPFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = default_helpfiles()
        HELPFILES_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return raw


def load_settings() -> dict:
    """
    Laadt settings.json, merged met defaults, en past daarna de actieve profile toe
    (colors/paths/ui). Resultaat heeft top-level 'colors', 'paths', 'ui' die
    al het actieve profiel bevatten, plus 'active_profile' en 'profiles' zelf.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    base_default = default_settings()

    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(json.dumps(base_default, indent=2), encoding="utf-8")
        return base_default

    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        # kapotte settings -> reset naar default
        SETTINGS_PATH.write_text(json.dumps(base_default, indent=2), encoding="utf-8")
        return base_default

    # Stap 1: defaults + raw samenvoegen
    merged = deep_merge(base_default, raw)

    # Stap 2: actieve profile toepassen indien aanwezig
    active_profile = raw.get("active_profile")
    profiles = raw.get("profiles", {})

    if isinstance(profiles, dict) and active_profile in profiles:
        prof = profiles[active_profile]

        # Enkel relevante keys overriden
        if "colors" in prof and isinstance(prof["colors"], dict):
            merged["colors"] = deep_merge(merged.get("colors", {}), prof["colors"])
        if "paths" in prof and isinstance(prof["paths"], dict):
            merged["paths"] = deep_merge(merged.get("paths", {}), prof["paths"])
        if "ui" in prof and isinstance(prof["ui"], dict):
            merged["ui"] = deep_merge(merged.get("ui", {}), prof["ui"])

    # Stap 3: profiel-info bijhouden op top-level
    merged["active_profile"] = active_profile
    merged["profiles"] = profiles

    # Terug wegschrijven (zodat nieuwe defaults ook persistent zijn)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged

def load_tools() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    dflt = default_tools()
    if not TOOLS_PATH.exists():
        TOOLS_PATH.write_text(json.dumps(dflt, indent=2), encoding="utf-8")
        return dflt
    try:
        data = json.loads(TOOLS_PATH.read_text(encoding="utf-8"))
    except Exception:
        TOOLS_PATH.write_text(json.dumps(dflt, indent=2), encoding="utf-8")
        return dflt
    # heel simpele validatie
    if "tools" not in data or not isinstance(data["tools"], list):
        data = dflt
        TOOLS_PATH.write_text(json.dumps(dflt, indent=2), encoding="utf-8")
    return data


ABOUT_DEFAULT = """# CyNiT Tools

Centrale omgeving voor jouw tools:

- Certificate / CSR Viewer (web + GUI)
- JWT Builder (JWT2JWK.py)
- Password Generator (passgen1.py)

Kleuren en paden: `config/settings.json`  
Tools en paden: `config/tools.json`
"""


def ensure_about():
    if not ABOUT_MD.exists():
        ABOUT_MD.write_text(ABOUT_DEFAULT, encoding="utf-8")


def markdown_to_html_simple(text: str) -> str:
    """
    Render Markdown naar HTML.

    - Eerst proberen we de 'markdown' library (pip install markdown)
      met o.a. de 'tables' extensie zodat je | Field | Value |-tabellen
      netjes gerenderd worden.
    - Als die lib ontbreekt of crasht, vallen we terug op een heel
      simpele converter zodat de pagina toch leesbaar blijft.
    """
    # 1) "Echte" Markdown-renderer als die beschikbaar is
    try:
        import markdown as mdlib  # type: ignore

        return mdlib.markdown(
            text,
            extensions=[
                "extra",      # kopjes, lijsten, etc.
                "tables",     # pipe-tables zoals in jouw exports
                "sane_lists", # wat nettere lijsten
            ],
            output_format="html5",
        )
    except Exception:
        # 2) Heel eenvoudige fallback (zonder tabellen)
        lines = text.splitlines()
        html_lines = []

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("### "):
                html_lines.append(f"<h3>{stripped[4:]}</h3>")
            elif stripped.startswith("## "):
                html_lines.append(f"<h2>{stripped[3:]}</h2>")
            elif stripped.startswith("# "):
                html_lines.append(f"<h1>{stripped[2:]}</h1>")
            elif stripped == "":
                html_lines.append("<br>")
            else:
                esc = (
                    stripped
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                html_lines.append(f"<p>{esc}</p>")

        return "\n".join(html_lines)

def _load_logo_image():
    path = LOGO_PATH
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def generate_ico_bytes():
    img = _load_logo_image()
    if img is None:
        return None
    size = 256
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    scale = min(size / img.width, size / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    offset = ((size - new_w) // 2, (size - new_h) // 2)
    square.paste(resized, offset, resized)
    buf = BytesIO()
    try:
        square.save(buf, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None
