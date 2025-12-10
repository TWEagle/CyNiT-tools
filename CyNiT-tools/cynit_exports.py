#!/usr/bin/env python3
"""
cynit_exports.py

Gedeelde export-logica (HTML / Markdown / XLSX / ZIP) voor CyNiT Tools.
Wordt gebruikt door o.a.:

• cert_viewer.py
• toekomstige DCBAAS/VOICA exportmodules

Functies:

- ensure_exports_dir()
- slugify_filename()
- load_export_styles()

- build_html_export()
- build_markdown_export()
- build_xlsx_export()
- build_zip_bytes()

Alles is centraal zodat het overal identiek werkt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional
from io import BytesIO
from zipfile import ZipFile
import json

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

import cynit_theme


# ------------------------------------------------------------
#  BASIS PADEN
# ------------------------------------------------------------

BASE_DIR: Path = cynit_theme.BASE_DIR
CONFIG_DIR: Path = cynit_theme.CONFIG_DIR
EXPORT_CONFIG_PATH: Path = CONFIG_DIR / "exports.json"

EXPORTS_DIR: Path = BASE_DIR / "exports"


def ensure_exports_dir() -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def slugify_filename(name: str) -> str:
    base = Path(name).stem or "certificate"
    base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)
    return base or "certificate"


# ------------------------------------------------------------
#  EXPORT STYLES (config/exports.json)
# ------------------------------------------------------------

def default_export_styles(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "xlsx": {
            "sheet": {"default_bg": "#FFFFFF"},
            "title": {"font_size": 16, "bold": True, "italic": False, "color": "#000000"},
            "field_col": {"font_size": 12, "bold": True, "italic": True, "color": "#000000"},
            "value_col": {"font_size": 12, "bold": False, "italic": False, "color": "#000000"},
        },
        "html": {
            "body": {"bg": "#FFFFFF", "fg": "#000000"},
            "title": {"color": "#0000FF", "font_size_px": 16, "bold": True},
            "table": {
                "border_color": "#000000",
                "border_width_px": 1,
                "field_col": {"font_size_px": 14, "bold": True, "italic": True},
                "value_col": {"font_size_px": 12, "bold": False, "italic": False},
            },
        },
        "md": {
            "title_prefix": "# ",
            "section_prefix": "## ",
            "bold_field_names": True,
            "table_header": "| Field | Value |",
            "table_sep": "| --- | --- |"
        }
    }


def load_export_styles(settings: Dict[str, Any]) -> Dict[str, Any]:
    defaults = default_export_styles(settings)

    if not EXPORT_CONFIG_PATH.exists():
        EXPORT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_CONFIG_PATH.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
        return defaults

    try:
        current = json.loads(EXPORT_CONFIG_PATH.read_text(encoding="utf-8"))
        merged = cynit_theme.deep_merge(defaults, current)
    except:
        merged = defaults

    EXPORT_CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


# ------------------------------------------------------------
#  HTML EXPORT
# ------------------------------------------------------------

def build_html_export(info: Dict[str, Any], settings: Dict[str, Any]) -> str:
    styles = load_export_styles(settings)
    html_cfg = styles["html"]

    body = html_cfg["body"]
    title_cfg = html_cfg["title"]
    table_cfg = html_cfg["table"]

    def table_block(title: str, mapping: Optional[Dict[str, Any]], is_issuer=False):
        if is_issuer and mapping is None:
            return f"<h2>{title}</h2><p>CSR heeft geen issuer.</p>"

        if mapping is None:
            return ""

        rows = []
        for k, v in mapping.items():
            rows.append(
                f"<tr>"
                f"<td style='font-weight:bold;font-style:italic;font-size:{table_cfg['field_col']['font_size_px']}px'>{k}</td>"
                f"<td style='font-size:{table_cfg['value_col']['font_size_px']}px'>{v}</td>"
                f"</tr>"
            )

        return f"<h2>{title}</h2><table>{''.join(rows)}</table>"

    html = f"""
<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>CyNiT Certificate Export</title>
<style>
body {{
    background:{body['bg']};
    color:{body['fg']};
    font-family:Arial, sans-serif;
}}
table {{
    border-collapse:collapse;
    min-width:500px;
}}
td {{
    border:{table_cfg['border_width_px']}px solid {table_cfg['border_color']};
    padding:6px 10px;
}}
h1,h2 {{
    color:{title_cfg['color']};
    font-weight:bold;
    font-size:{title_cfg['font_size_px']}px;
}}
</style>
</head>
<body>

<h1>CyNiT Certificate Export</h1>
<p><strong>Bestand:</strong> {info.get("filename","")}</p>
<p><strong>Type:</strong> {info.get("type","")}</p>

{table_block("Subject", info.get("subject"))}
{table_block("Issuer", info.get("issuer"), is_issuer=True)}
{table_block("Properties", info.get("properties"))}

</body>
</html>
"""
    return html


# ------------------------------------------------------------
#  MARKDOWN EXPORT  (HERWERKT / FIXED)
# ------------------------------------------------------------

def build_markdown_export(info: Dict[str, Any], settings: Dict[str, Any]) -> str:
    styles = load_export_styles(settings)
    md_cfg = styles["md"]

    title = md_cfg["title_prefix"] + "CyNiT Certificate Export"
    section = md_cfg["section_prefix"]

    TABLE_HEADER = md_cfg.get("table_header", "| Field | Value |")
    TABLE_SEP = md_cfg.get("table_sep", "| --- | --- |")

    def md_table(title: str, mapping: Optional[Dict[str, Any]], issuer=False):
        if issuer and mapping is None:
            return f"{section}{title}\n\nCSR heeft geen issuer.\n"

        if mapping is None:
            return ""

        lines = [f"{section}{title}", "", TABLE_HEADER, TABLE_SEP]

        for k, v in mapping.items():
            field = f"**{k}**" if md_cfg.get("bold_field_names", True) else k
            lines.append(f"| {field} | {v} |")

        lines.append("")  # newline na tabel
        return "\n".join(lines)

    md = [
        title,
        "",
        f"**Bestand:** `{info.get('filename','')}`",
        f"**Type:** {info.get('type','')}",
        "",
        md_table("Subject", info.get("subject")),
        md_table("Issuer", info.get("issuer"), issuer=True),
        md_table("Properties", info.get("properties")),
    ]

    return "\n".join(md).strip() + "\n"


# ------------------------------------------------------------
#  XLSX EXPORT
# ------------------------------------------------------------

def build_xlsx_export(info: Dict[str, Any], settings: Dict[str, Any]) -> bytes:
    styles = load_export_styles(settings)
    cfg = styles["xlsx"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Certificate"

    default_bg = cfg["sheet"]["default_bg"].lstrip("#")

    fill = PatternFill(start_color=default_bg, end_color=default_bg, fill_type="solid")

    title_font = Font(
        size=cfg["title"]["font_size"],
        bold=cfg["title"]["bold"],
        italic=cfg["title"]["italic"],
        color=cfg["title"]["color"].lstrip("#"),
    )
    field_font = Font(
        size=cfg["field_col"]["font_size"],
        bold=cfg["field_col"]["bold"],
        italic=cfg["field_col"]["italic"],
        color=cfg["field_col"]["color"].lstrip("#"),
    )
    value_font = Font(
        size=cfg["value_col"]["font_size"],
        bold=cfg["value_col"]["bold"],
        italic=cfg["value_col"]["italic"],
        color=cfg["value_col"]["color"].lstrip("#"),
    )

    row = 1
    ws["A1"] = "CyNiT Certificate Export"
    ws["A1"].font = title_font
    ws["A1"].fill = fill
    row += 2

    def write_row(key, value):
        nonlocal row
        ws[f"A{row}"] = key
        ws[f"B{row}"] = value
        ws[f"A{row}"].font = field_font
        ws[f"B{row}"].font = value_font
        ws[f"A{row}"].fill = fill
        ws[f"B{row}"].fill = fill
        row += 1

    write_row("Bestand", info.get("filename", ""))
    write_row("Type", info.get("type", ""))
    row += 1

    def write_section(title, mapping, issuer=False):
        nonlocal row
        ws[f"A{row}"] = title
        ws[f"A{row}"].font = title_font
        ws[f"A{row}"].fill = fill
        row += 1

        if issuer and mapping is None:
            write_row("Issuer", "CSR heeft geen issuer.")
            row += 1
            return

        for k, v in (mapping or {}).items():
            write_row(k, v)
        row += 1

    write_section("Subject", info.get("subject"))
    write_section("Issuer", info.get("issuer"), issuer=True)
    write_section("Properties", info.get("properties"))

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 60

    mem = BytesIO()
    wb.save(mem)
    mem.seek(0)
    return mem.getvalue()


# ------------------------------------------------------------
#  ZIP EXPORT
# ------------------------------------------------------------

def build_zip_bytes(info: Dict[str, Any], settings: Dict[str, Any], formats: List[str]) -> bytes:
    base = slugify_filename(info.get("filename", "certificate"))
    mem = BytesIO()

    with ZipFile(mem, "w") as z:
        for fmt in formats:
            fmt = fmt.lower()

            if fmt == "json":
                z.writestr(f"{base}.json", json.dumps(info, indent=2, ensure_ascii=False))

            elif fmt == "csv":
                lines = ["Section;Field;Value"]
                for sec_key, sec_name in [
                    ("subject", "Subject"),
                    ("issuer", "Issuer"),
                    ("properties", "Properties"),
                ]:
                    section = info.get(sec_key)
                    if not section:
                        continue
                    for k, v in section.items():
                        lines.append(f"{sec_name};{k};{str(v).replace(';', ',')}")

                z.writestr(f"{base}.csv", "\n".join(lines))

            elif fmt == "html":
                html = build_html_export(info, settings)
                z.writestr(f"{base}.html", html)

            elif fmt == "md":
                md = build_markdown_export(info, settings)
                z.writestr(f"{base}.md", md)

            elif fmt == "xlsx":
                z.writestr(f"{base}.xlsx", build_xlsx_export(info, settings))

    mem.seek(0)
    return mem.getvalue()
