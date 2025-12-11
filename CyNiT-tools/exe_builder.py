#!/usr/bin/env python3
"""
exe_builder.py

CyNiT EXE + Installer Builder (web-only)

- Route: /exe-builder
- Upload PNG-logo
- Converteert PNG → ICO
- Draait PyInstaller om een EXE van ctools.py te maken
- Genereert installer_config.json + Inno Setup script (.iss)
- Optioneel: bouwt een echte Windows installer-EXE via ISCC.exe
- Optioneel: maakt een ZIP bundel van EXE + installer + config
"""

from __future__ import annotations

import sys
import os
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, Any, List

from flask import Flask, request, render_template_string
from PIL import Image

import cynit_theme
import cynit_layout


BASE_DIR = cynit_theme.BASE_DIR
SCRIPT_TO_BUILD = BASE_DIR / "ctools.py"


def get_modules_from_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Haal alle 'web'-tools uit tools.json en map naar {id, label}.
    """
    modules: List[Dict[str, str]] = []
    for t in tools:
        if t.get("type") != "web":
            continue
        tid = t.get("id")
        if not tid:
            continue
        modules.append(
            {
                "id": tid,
                "label": t.get("name") or tid,
            }
        )
    return modules


def compute_output_dirs(output_dir: Optional[str]) -> Dict[str, Path]:
    """
    Bepaal basis output directories voor icons / installer / dist / pyinstaller build/spec.
    Als output_dir leeg is, gebruiken we BASE_DIR / 'build' als basis.
    """
    if output_dir:
        base = Path(output_dir)
    else:
        base = BASE_DIR / "build"

    icons_dir = base / "icons"
    installer_dir = base / "installer"
    dist_dir = base / "dist"
    pyi_build_dir = base / "pyi_build"
    pyi_spec_dir = base / "pyi_spec"

    for d in (icons_dir, installer_dir, dist_dir, pyi_build_dir, pyi_spec_dir):
        d.mkdir(parents=True, exist_ok=True)

    return {
        "base": base,
        "icons": icons_dir,
        "installer": installer_dir,
        "dist": dist_dir,
        "pyi_build": pyi_build_dir,
        "pyi_spec": pyi_spec_dir,
    }


def save_png_as_ico(png_bytes: bytes, base_name: str, icons_dir: Path) -> Path:
    """Sla PNG-bytes op als ICO met verschillende sizes (16–256px) in icons_dir."""
    icons_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(BytesIO(png_bytes))

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    ico_path = icons_dir / f"{base_name}.ico"
    img.save(str(ico_path), format="ICO", sizes=sizes)
    return ico_path


def run_pyinstaller(
    exe_name: str,
    icon_path: Path,
    dist_dir: Path,
    pyi_build_dir: Path,
    pyi_spec_dir: Path,
) -> subprocess.CompletedProcess:
    """
    Draai PyInstaller via het huidige Python.
    Bouwt een onefile, noconsole EXE voor ctools.py in een gekozen dist/build/spec map.
    """
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        f"--name={exe_name}",
        f"--icon={str(icon_path)}",
        f"--distpath={str(dist_dir)}",
        f"--workpath={str(pyi_build_dir)}",
        f"--specpath={str(pyi_spec_dir)}",
        "ctools.py",
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    return proc


def write_installer_config(
    settings: Dict[str, Any],
    exe_name: str,
    app_name: str,
    app_version: str,
    modules: List[Dict[str, str]],
    selected_modules: List[str],
    installer_dir: Path,
) -> Path:
    """
    Schrijf installer_config.json met app-info, modules & theme.

    Structuur is afgestemd op apply_installer_config() in ctools.py:

    {
      "app_name": "...",
      "exe_name": "...",
      "version": "...",
      "modules": [
        {"id": "certviewer", "label": "Certificate / CSR Viewer", "enabled": true},
        ...
      ],
      "theme": {
        "active_profile": "...",
        "colors": { ... },
        "paths": { ... },
        "ui": { ... }
      }
    }
    """
    import json

    installer_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "app_name": app_name,
        "exe_name": exe_name,
        "version": app_version,
        "modules": [
            {
                "id": m["id"],
                "label": m.get("label") or m.get("name") or m["id"],
                "enabled": m["id"] in selected_modules,
            }
            for m in modules
        ],
        "theme": {
            "active_profile": settings.get("active_profile"),
            "colors": settings.get("colors", {}),
            "paths": settings.get("paths", {}),
            "ui": settings.get("ui", {}),
        },
    }

    cfg_path = installer_dir / "installer_config.json"
    cfg_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cfg_path


def generate_inno_script(
    exe_name: str,
    app_name: str,
    app_version: str,
    icon_path: Path,
    dist_exe: Path,
    installer_config_path: Path,
    modules: List[Dict[str, str]],
    selected_modules: List[str],
    installer_dir: Path,
) -> Path:
    """
    Genereer een Inno Setup script (.iss) met components per module.

    Script wordt opgeslagen in <installer_dir>/<exe_name>_installer.iss
    """
    installer_dir.mkdir(parents=True, exist_ok=True)
    iss_path = installer_dir / f"{exe_name}_installer.iss"

    components_lines: List[str] = []
    for m in modules:
        comp_id = m["id"]
        desc = m.get("label") or m.get("name") or comp_id
        extra_flags = "" if comp_id in selected_modules else "unchecked"
        components_lines.append(
            f"Name: \"{comp_id}\"; Description: \"{desc}\"; Types: full; Flags: checkablealone {extra_flags}".rstrip()
        )
    components_block = "\n".join(components_lines)

    script = f"""; Auto-generated by exe_builder.py
; Je kan dit script openen in Inno Setup (ISCC) en aanpassen indien nodig.

[Setup]
AppName={app_name}
AppVersion={app_version}
DefaultDirName={{pf}}\\{app_name}
DefaultGroupName={app_name}
DisableDirPage=no
DisableProgramGroupPage=no
OutputDir={installer_dir}
OutputBaseFilename={exe_name}_Setup
SetupIconFile={icon_path}
Compression=lzma
SolidCompression=yes

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Maak een snelkoppeling op het bureaublad"; GroupDescription: "Extra snelkoppelingen:"

[Components]
{components_block}

[Files]
; hoofd EXE
Source: "{dist_exe}"; DestDir: "{{app}}"; Flags: ignoreversion

; installer-config (theme + modules)
Source: "{installer_config_path}"; DestDir: "{{app}}\\config"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\{app_name}"; Filename: "{{app}}\\{exe_name}.exe"; WorkingDir: "{{app}}"; IconFilename: "{{app}}\\{exe_name}.exe"
Name: "{{commondesktop}}\\{app_name}"; Filename: "{{app}}\\{exe_name}.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{exe_name}.exe"; Description: "Start {app_name}"; Flags: nowait postinstall skipifsilent
"""

    iss_path.write_text(script, encoding="utf-8")
    return iss_path


def run_inno_compiler(iss_path: Path) -> Optional[subprocess.CompletedProcess]:
    """
    Probeer ISCC.exe (Inno Setup compiler) te vinden en uit te voeren.

    Als ISCC niet gevonden wordt, returnt None en wordt alleen een script aangemaakt.
    """
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    exe = None
    for c in candidates:
        if c.exists():
            exe = c
            break

    if exe is None:
        return None

    proc = subprocess.run(
        [str(exe), str(iss_path)],
        cwd=str(iss_path.parent),
        capture_output=True,
        text=True,
    )
    return proc


def create_zip_bundle(
    dist_exe: Path,
    installer_exe: Optional[Path],
    installer_cfg_path: Path,
    iss_path: Path,
    zip_target: Path,
) -> Path:
    """
    Maak een ZIP bundel aan met de belangrijkste artefacten:
    - EXE
    - installer-EXE (indien aanwezig)
    - installer_config.json (onder config/)
    - .iss script
    """
    import zipfile

    zip_target.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_target, "w", zipfile.ZIP_DEFLATED) as zf:
        def add_file(p: Optional[Path], arcname: Optional[str] = None) -> None:
            if not p:
                return
            if not p.exists():
                return
            zf.write(p, arcname or p.name)

        # hoofd exe
        add_file(dist_exe, dist_exe.name)
        # installer exe
        if installer_exe:
            add_file(installer_exe, installer_exe.name)
        # config onder config/
        add_file(installer_cfg_path, "config/installer_config.json")
        # script
        add_file(iss_path, iss_path.name)

    return zip_target


def register_web_routes(
    app: Flask,
    settings: Dict[str, Any],
    tools_cfg_or_list: Optional[Any] = None,
) -> None:
    """
    Registreer de /exe-builder route in de bestaande Flask-app.

    tools_cfg_or_list kan zijn:
    - dict met sleutel 'tools'  (zoals cynit_theme.load_tools())
    - list van tool-dicts       (zoals ctools.TOOLS)
    - None                      (geen tools → lege lijst)
    """
    # 1) Normaliseer naar lijst
    if isinstance(tools_cfg_or_list, dict):
        tools_list: List[Dict[str, Any]] = tools_cfg_or_list.get("tools", [])
    elif isinstance(tools_cfg_or_list, list):
        tools_list = tools_cfg_or_list
    else:
        tools_list = []

    base_css = cynit_layout.common_css(settings)
    common_js = cynit_layout.common_js()
    header_html = cynit_layout.header_html(
        settings,
        tools=tools_list,
        title="CyNiT EXE + Installer Builder",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    modules = get_modules_from_tools(tools_list)

    template = """<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>CyNiT EXE + Installer Builder</title>
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    {{ base_css|safe }}

    .card {
      max-width: 900px;
      margin: 0 auto 20px auto;
      background: #1e1e1e;
      padding: 20px;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
    }
    .muted { color:#aaa; font-size:0.9em; }
    .flash-error {
      background:#331111;
      border:1px solid #aa3333;
      color:#ffaaaa;
      padding:8px 12px;
      border-radius:8px;
      margin-bottom:10px;
    }
    .flash-ok {
      background:#112211;
      border:1px solid #22aa33;
      color:#aaffaa;
      padding:8px 12px;
      border-radius:8px;
      margin-bottom:10px;
    }
    pre.log {
      background:#050505;
      border-radius:8px;
      padding:10px;
      max-height:260px;
      overflow:auto;
      font-size:0.8em;
    }
    fieldset {
      border:1px solid #333;
      border-radius:10px;
      padding:10px 14px;
      margin-top:10px;
    }
    legend {
      padding:0 6px;
      font-size:0.9em;
      color:#ccc;
    }
    label.inline {
      display:inline-flex;
      align-items:center;
      margin-right:12px;
      margin-top:4px;
    }
    input[type=text] {
      width:260px;
      max-width:100%;
    }
  </style>
  <script>
    {{ common_js|safe }}
  </script>
</head>
<body>
  {{ header_html|safe }}
  <div class="page">
    <div class="card">
      <h1>CyNiT EXE + Installer Builder</h1>
      <p class="muted">
        Bouw een Windows EXE van <code>ctools.py</code> én genereer een Inno Setup installer
        (met modules als components en een aparte config met theme &amp; modules).
        Deze tool draait PyInstaller (en optioneel Inno Setup) lokaal op deze machine.
      </p>

      {% if error %}
        <div class="flash-error">{{ error }}</div>
      {% endif %}

      {% if info %}
        <div class="flash-ok">{{ info }}</div>
      {% endif %}

      <form method="post" enctype="multipart/form-data">
        <fieldset>
          <legend>Basis</legend>
          <label>EXE naam:</label><br>
          <input type="text" name="exe_name" value="{{ exe_name }}" /><br><br>

          <label>Applicatie-naam (installer titel):</label><br>
          <input type="text" name="app_name" value="{{ app_name }}" /><br><br>

          <label>Versie:</label><br>
          <input type="text" name="app_version" value="{{ app_version }}" /><br><br>
        </fieldset>

        <fieldset>
          <legend>Output map</legend>
          <label>Absolute pad (bv. C:\\Builds\\CyNiT). Leeg laten = standaard <code>build/</code> onder de app.</label><br>
          <input type="text" name="output_dir" value="{{ output_dir }}" style="width:350px;"><br>
          <span class="muted">Deze basis-map bevat submappen: dist/, installer/, icons/, pyi_build/, pyi_spec/.</span>
        </fieldset>

        <fieldset>
          <legend>Logo / icoon</legend>
          <label>PNG logo uploaden (wordt .ico):</label><br>
          <input type="file" name="icon_png" accept=".png" /><br>
          <span class="muted">Tip: bij voorkeur een vierkante PNG met transparante achtergrond.</span>
        </fieldset>

        <fieldset>
          <legend>Modules</legend>
          <p class="muted">
            Deze modules worden in de installer als "components" getoond én in de config JSON opgeslagen.
          </p>
          {% for m in modules %}
            <label class="inline">
              <input type="checkbox" name="modules" value="{{ m.id }}" {% if m.id in selected_modules %}checked{% endif %}>
              {{ m.label }}
            </label><br>
          {% endfor %}
        </fieldset>

        <fieldset>
          <legend>ZIP bundel</legend>
          <label class="inline">
            <input type="checkbox" name="zip_enabled" {% if zip_enabled %}checked{% endif %}>
            Maak een ZIP met EXE + installer + config
          </label>
          <br>
          <label>ZIP pad (bestand of map):</label><br>
          <input type="text" name="zip_path" value="{{ zip_path }}" style="width:350px;"><br>
          <span class="muted">
            Voorbeeld: <code>C:\\Temp\\CyNiT-Tools_bundle.zip</code> of <code>C:\\Temp</code>.
            Als je een map opgeeft, wordt de bestandsnaam automatisch <code>&lt;exe_name&gt;_bundle.zip</code>.
          </span>
        </fieldset>

        <br>
        <button type="submit">🔨 Build EXE + Installer</button>
      </form>

      {% if build_log %}
        <hr>
        <h3>Build log</h3>
        <pre class="log">{{ build_log }}</pre>
      {% endif %}

      {% if exe_path %}
        <p class="muted">
          EXE zou nu beschikbaar moeten zijn op:<br>
          <code>{{ exe_path }}</code>
        </p>
      {% endif %}

      {% if installer_script %}
        <p class="muted">
          Inno Setup script:<br>
          <code>{{ installer_script }}</code>
        </p>
      {% endif %}

      {% if installer_exe %}
        <p class="muted">
          Installer EXE (als Inno Setup compile gelukt is):<br>
          <code>{{ installer_exe }}</code>
        </p>
      {% endif %}

      {% if zip_file %}
        <p class="muted">
          ZIP bundel:<br>
          <code>{{ zip_file }}</code>
        </p>
      {% endif %}
    </div>
  </div>
  {{ footer_html|safe }}
</body>
</html>
"""

    @app.route("/exe-builder", methods=["GET", "POST"])
    def exe_builder_index():
        error: Optional[str] = None
        info: Optional[str] = None
        build_log_parts: List[str] = []
        exe_path_str: str = ""
        installer_script_str: str = ""
        installer_exe_str: str = ""
        zip_file_str: str = ""

        # defaults
        exe_name = "CyNiT-Tools"
        app_name = "CyNiT Tools"
        app_version = "1.0.0"
        output_dir = ""
        zip_enabled = False
        zip_path = ""
        selected_modules: List[str] = [m["id"] for m in modules]

        if request.method == "POST":
            exe_name = (request.form.get("exe_name") or exe_name).strip() or exe_name
            app_name = (request.form.get("app_name") or app_name).strip() or app_name
            app_version = (request.form.get("app_version") or app_version).strip() or app_version
            output_dir = (request.form.get("output_dir") or "").strip()

            selected_modules = request.form.getlist("modules") or [m["id"] for m in modules]

            zip_enabled = request.form.get("zip_enabled") is not None
            zip_path = (request.form.get("zip_path") or "").strip()

            if not SCRIPT_TO_BUILD.is_file():
                error = f"ctools.py werd niet gevonden op: {SCRIPT_TO_BUILD}"
            else:
                file = request.files.get("icon_png")
                if not file or file.filename == "":
                    error = "Geen PNG-logo geselecteerd."
                else:
                    try:
                        # 0) Output directories
                        dirs = compute_output_dirs(output_dir)
                        icons_dir = dirs["icons"]
                        installer_dir = dirs["installer"]
                        dist_dir = dirs["dist"]
                        pyi_build_dir = dirs["pyi_build"]
                        pyi_spec_dir = dirs["pyi_spec"]

                        # 1) PNG -> ICO
                        png_bytes = file.read()
                        ico_path = save_png_as_ico(png_bytes, exe_name.replace(" ", "_"), icons_dir)

                        # 2) PyInstaller
                        proc = run_pyinstaller(exe_name, ico_path, dist_dir, pyi_build_dir, pyi_spec_dir)
                        build_log_parts.append("[PyInstaller] cmd exit code: " + str(proc.returncode))
                        if proc.stdout:
                            build_log_parts.append("[PyInstaller STDOUT]\n" + proc.stdout)
                        if proc.stderr:
                            build_log_parts.append("[PyInstaller STDERR]\n" + proc.stderr)

                        dist_exe = dist_dir / f"{exe_name}.exe"
                        exe_path_str = str(dist_exe)

                        if proc.returncode == 0 and dist_exe.is_file():
                            info = "EXE build succesvol afgerond."
                        else:
                            error = "PyInstaller gaf een foutmelding (zie log hieronder)."

                        installer_cfg_path: Optional[Path] = None
                        iss_path: Optional[Path] = None
                        installer_exe: Optional[Path] = None

                        # 3) Installer-config JSON (alleen proberen als EXE er is)
                        if dist_exe.is_file():
                            installer_cfg_path = write_installer_config(
                                settings,
                                exe_name,
                                app_name,
                                app_version,
                                modules,
                                selected_modules,
                                installer_dir,
                            )
                            build_log_parts.append(f"[Builder] installer_config.json → {installer_cfg_path}")

                        # 4) Inno Setup script
                        if dist_exe.is_file() and installer_cfg_path is not None:
                            iss_path = generate_inno_script(
                                exe_name=exe_name,
                                app_name=app_name,
                                app_version=app_version,
                                icon_path=ico_path,
                                dist_exe=dist_exe,
                                installer_config_path=installer_cfg_path,
                                modules=modules,
                                selected_modules=selected_modules,
                                installer_dir=installer_dir,
                            )
                            installer_script_str = str(iss_path)
                            build_log_parts.append(f"[Builder] Inno Setup script → {iss_path}")

                        # 5) Probeer Inno Setup compiler (optioneel)
                        inno_proc = None
                        if iss_path is not None:
                            inno_proc = run_inno_compiler(iss_path)

                        if inno_proc is None and iss_path is not None:
                            build_log_parts.append(
                                "[Inno] ISCC.exe niet gevonden. Script is wel aangemaakt; "
                                "compileer het manueel in Inno Setup."
                            )
                        elif inno_proc is not None:
                            build_log_parts.append("[Inno] cmd exit code: " + str(inno_proc.returncode))
                            if inno_proc.stdout:
                                build_log_parts.append("[Inno STDOUT]\n" + inno_proc.stdout)
                            if inno_proc.stderr:
                                build_log_parts.append("[Inno STDERR]\n" + inno_proc.stderr)
                            installer_exe = installer_dir / f"{exe_name}_Setup.exe"
                            if installer_exe.is_file():
                                installer_exe_str = str(installer_exe)
                                if not error:
                                    info = (info or "") + " Installer build is ook afgerond."

                        # 6) ZIP bundel (optioneel)
                        if zip_enabled and dist_exe.is_file() and installer_cfg_path is not None and iss_path is not None:
                            # Bepaal doelpad
                            zp = Path(zip_path) if zip_path else None
                            if zp is None or str(zp).strip() == "":
                                # geen pad opgegeven → standaard in installer_dir
                                zp = installer_dir / f"{exe_name}_bundle.zip"
                            else:
                                # als suffix niet .zip is, behandelen als directory
                                if zp.suffix.lower() != ".zip":
                                    zp = zp / f"{exe_name}_bundle.zip"

                            bundle = create_zip_bundle(
                                dist_exe=dist_exe,
                                installer_exe=installer_exe if installer_exe and installer_exe.exists() else None,
                                installer_cfg_path=installer_cfg_path,
                                iss_path=iss_path,
                                zip_target=zp,
                            )
                            zip_file_str = str(bundle)
                            build_log_parts.append(f"[ZIP] Bundel aangemaakt → {bundle}")
                            if not error:
                                info = (info or "") + " ZIP bundel aangemaakt."

                    except Exception as e:  # safety
                        error = f"Fout tijdens build: {e}"

        build_log = "\n\n".join(build_log_parts) if build_log_parts else None

        templ_modules = [{"id": m["id"], "label": m.get("label") or m.get("name") or m["id"]} for m in modules]

        return render_template_string(
            template,
            error=error,
            info=info,
            build_log=build_log,
            exe_path=exe_path_str,
            installer_script=installer_script_str,
            installer_exe=installer_exe_str,
            zip_file=zip_file_str,
            exe_name=exe_name,
            app_name=app_name,
            app_version=app_version,
            output_dir=output_dir,
            modules=templ_modules,
            selected_modules=selected_modules,
            tools=tools_list,
            base_css=base_css,
            common_js=common_js,
            header_html=header_html,
            footer_html=footer_html,
            zip_enabled=zip_enabled,
            zip_path=zip_path,
        )


def run_web() -> None:
    """
    Losse debug-run: start alleen de exe-builder op poort 5451.
    """
    settings = cynit_theme.load_settings()
    tools_cfg = cynit_theme.load_tools()

    app = Flask(__name__)
    register_web_routes(app, settings, tools_cfg)
    app.run(host="127.0.0.1", port=5451, debug=True)


if __name__ == "__main__":
    run_web()
