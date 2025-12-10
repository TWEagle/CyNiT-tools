import os
import sys
import json
import threading
import subprocess
from pathlib import Path
from uuid import uuid4
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    redirect,
    url_for,
    send_from_directory,
)

import yt_dlp

# =========================
# CyNiT tools pad toevoegen
# =========================

BASE_DIR = Path(__file__).resolve().parent

def find_cynit_tools_dir() -> Path:
    """
    Zoek dynamisch naar de CyNiT-tools map met ctools.py.
    We proberen een paar logische locaties rond BASE_DIR.
    """
    candidates = []

    # BASE_DIR = .../SP-YT
    # Probeer: SP-YT\CyNiT-tools, SP-YT\CyNiT-Tools
    candidates.append(BASE_DIR / "CyNiT-tools")
    candidates.append(BASE_DIR / "CyNiT-Tools")

    # Eén niveau hoger: ...\ (ouder van SP-YT)
    parent1 = BASE_DIR.parent
    candidates.append(parent1 / "CyNiT-tools")
    candidates.append(parent1 / "CyNiT-Tools")

    # Nog een niveau hoger (voor het geval je later verplaatst)
    parent2 = parent1.parent
    candidates.append(parent2 / "CyNiT-tools")
    candidates.append(parent2 / "CyNiT-Tools")

    for c in candidates:
        ctools_py = c / "ctools.py"
        if ctools_py.exists():
            print(f"[INFO] CyNiT-tools gevonden op: {c}")
            return c

    # Fallback: standaard zoals we eerst deden
    fallback = BASE_DIR.parent / "CyNiT-tools"
    print("[WAARSCHUWING] Geen CyNiT-tools map met ctools.py gevonden in de verwachte locaties.")
    print(f"[WAARSCHUWING] Gebruik fallback pad: {fallback}")
    return fallback

CYTOOLS_DIR = find_cynit_tools_dir()

if CYTOOLS_DIR.exists():
    sys.path.insert(0, str(CYTOOLS_DIR))
else:
    print(f"[WAARSCHUWING] CyNiT-tools map bestaat niet op: {CYTOOLS_DIR}")
    print("Controleer de folderstructuur of pas find_cynit_tools_dir() aan.")

# CyNiT thema / layout importeren vanuit CyNiT-tools
import cynit_theme
import cynit_layout

# =========================
# App-specifieke settings
# =========================

BASE_DIR = Path(__file__).resolve().parent
APP_SETTINGS_FILE = BASE_DIR / "settings.json"

# Default settings voor deze app (NIET de globale CyNiT settings)
APP_DEFAULT_SETTINGS = {
    "default_input_folder": "C:/mus",
    "default_output_folder": "C:/mus-e",
    "default_yt_output_folder": "C:/mus-e",
    "default_start_dir": str(Path.home()),
}


def save_app_settings(data: dict):
    """Schrijf app-settings.json weg."""
    try:
        with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[APP SETTINGS] Opgeslagen naar {APP_SETTINGS_FILE}")
    except Exception as e:
        print(f"[APP SETTINGS] Kon settings.json niet wegschrijven: {e}")


def load_app_settings() -> dict:
    """
    Lees app-settings.json in (in dezelfde map als yt.py).
    Vul ontbrekende keys op met APP_DEFAULT_SETTINGS.
    """
    if APP_SETTINGS_FILE.exists():
        try:
            with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                print("[APP SETTINGS] settings.json is geen dict, opnieuw opbouwen.")
                data = {}
        except Exception as e:
            print(f"[APP SETTINGS] Fout bij lezen settings.json: {e}")
            data = {}
    else:
        data = {}

    changed = False
    for key, default_value in APP_DEFAULT_SETTINGS.items():
        if key not in data or not isinstance(data[key], str) or not data[key]:
            data[key] = default_value
            changed = True

    if changed or not APP_SETTINGS_FILE.exists():
        print("[APP SETTINGS] settings.json wordt aangemaakt/bijgewerkt met defaults.")
        save_app_settings(data)

    return data


APP_SETTINGS = load_app_settings()


def app_s(key: str) -> str:
    """Helper om app-setting op te halen met fallback naar defaults."""
    return APP_SETTINGS.get(key, APP_DEFAULT_SETTINGS[key])


# =========================
# CyNiT THEMA SETTINGS
# =========================

THEME_SETTINGS = cynit_theme.load_settings()
# Hierin zitten o.a. colors, paths, ui, active_profile, etc.

# =========================
# Overige config / globals
# =========================

APP_TITLE = "CyNiT Audio Converter"
VALID_EXTS = (".m4a", ".mp4", ".webm")

# YouTube download jobs (voor progress + queue)
YOUTUBE_JOBS = {}
YOUTUBE_LOCK = Lock()
YOUTUBE_MAX_WORKERS = 3  # aantal parallelle downloads

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me-for-production"


# =========================
# Helper functies
# =========================

def ask_directory_dialog(initial_dir: str):
    """Native folderselectie via Tkinter."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None, "Tkinter is niet beschikbaar op dit systeem."

    try:
        root = tk.Tk()
        root.withdraw()
        root.update()

        folder = filedialog.askdirectory(initialdir=initial_dir)
        root.destroy()

        if not folder:
            return None, None  # cancel is geen harde fout

        return folder, None
    except Exception as e:
        return None, str(e)


def convert_to_mp3(input_path: str, output_path: str) -> bool:
    """Converteer één bestand naar MP3 via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ab", "192k",
        output_path,
    ]

    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            print(f"[FFMPEG ERROR] {input_path} → {output_path}")
            print(completed.stderr)
            return False

        return True
    except FileNotFoundError:
        print("[ERROR] ffmpeg niet gevonden. Staat ffmpeg in je PATH?")
        return False
    except Exception as e:
        print(f"[ERROR] Onverwachte fout bij ffmpeg: {e}")
        return False


def batch_convert(input_folder: str, output_folder: str) -> dict:
    """Batch converteer alle geldige bestanden in input_folder naar MP3 in output_folder."""
    input_folder = os.path.abspath(input_folder)
    output_folder = os.path.abspath(output_folder)

    result = {
        "input_folder": input_folder,
        "output_folder": output_folder,
        "files_found": 0,
        "converted": 0,
        "errors": [],
        "details": [],
    }

    if not os.path.isdir(input_folder):
        result["errors"].append(f"Inputfolder bestaat niet: {input_folder}")
        return result

    os.makedirs(output_folder, exist_ok=True)

    files = [
        f
        for f in os.listdir(input_folder)
        if f.lower().endswith(VALID_EXTS)
    ]

    result["files_found"] = len(files)
    if not files:
        return result

    for file in files:
        input_path = os.path.join(input_folder, file)
        output_name = os.path.splitext(file)[0] + ".mp3"
        output_path = os.path.join(output_folder, output_name)

        ok = convert_to_mp3(input_path, output_path)
        if ok:
            result["converted"] += 1
            result["details"].append((file, "OK"))
        else:
            msg = f"Fout bij converteren: {file}"
            result["errors"].append(msg)
            result["details"].append((file, "FOUT"))

    return result


def download_youtube_video(video_url: str, output_folder: str) -> dict:
    """
    Download één YouTube-video (bestaudio) naar output_folder.
    Geeft status-dict terug (ok, title, error, dest_folder).
    """
    output_folder = os.path.abspath(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_folder, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": "player_client=default"
        },
    }

    status = {
        "ok": False,
        "title": None,
        "error": None,
        "dest_folder": output_folder,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            status["ok"] = True
            status["title"] = info_dict.get("title")
            print(f"[YT-DLP] Downloaded: {status['title']}")
    except Exception as e:
        status["error"] = str(e)
        print(f"[YT-DLP ERROR] {e}")

    return status


def restart_process_delayed(delay_seconds: float = 1.0):
    """Restart het huidige Python proces na een kleine delay."""
    import time
    time.sleep(delay_seconds)
    print("[RESTART] Herstart applicatie...")
    python = sys.executable
    os.execl(python, python, *sys.argv)


# =========================
# YouTube job management
# =========================

def start_yt_job(urls, output_folder):
    """
    Maak een nieuwe YouTube-downloadjob, start deze in de achtergrond
    en geef job_id terug.
    """
    job_id = str(uuid4())
    job = {
        "id": job_id,
        "output_folder": os.path.abspath(output_folder),
        "total": len(urls),
        "completed": 0,
        "error_count": 0,
        "status": "running",  # running | done
        "items": [
            {
                "index": i + 1,
                "url": url,
                "title": None,
                "status": "queued",  # queued | downloading | done | error
                "error": None,
            }
            for i, url in enumerate(urls)
        ],
    }

    with YOUTUBE_LOCK:
        YOUTUBE_JOBS[job_id] = job

    t = threading.Thread(target=run_yt_job, args=(job_id,), daemon=True)
    t.start()
    return job_id


def run_yt_job(job_id: str):
    """Worker in aparte thread die parallel downloads uitvoert en progress bijwerkt."""
    with YOUTUBE_LOCK:
        job = YOUTUBE_JOBS.get(job_id)
        if not job:
            return
        urls = [item["url"] for item in job["items"]]
        output_folder = job["output_folder"]

    def worker(idx, url):
        with YOUTUBE_LOCK:
            job = YOUTUBE_JOBS.get(job_id)
            if not job:
                return
            item = job["items"][idx]
            item["status"] = "downloading"

        status = download_youtube_video(url, output_folder)

        with YOUTUBE_LOCK:
            job = YOUTUBE_JOBS.get(job_id)
            if not job:
                return
            item = job["items"][idx]
            item["title"] = status.get("title") or item["url"]

            if status.get("ok"):
                item["status"] = "done"
            else:
                item["status"] = "error"
                item["error"] = status.get("error")
                job["error_count"] += 1

            job["completed"] += 1

    with ThreadPoolExecutor(max_workers=YOUTUBE_MAX_WORKERS) as executor:
        futures = []
        for idx, url in enumerate(urls):
            futures.append(executor.submit(worker, idx, url))
        for f in futures:
            try:
                f.result()
            except Exception as e:
                print(f"[JOB ERROR] {e}")

    with YOUTUBE_LOCK:
        job = YOUTUBE_JOBS.get(job_id)
        if job:
            job["status"] = "done"


# =========================
# HTML Template (met tabs + CyNiT header/footer)
# =========================

PAGE_TEMPLATE = r"""
<!doctype html>
<html lang="nl">
<head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
    <style>
        {{ base_css|safe }}

        body {
            background: #000000;
            color: {{ colors.general_fg }};
        }
        h1 {
            color: {{ colors.title }};
            margin-bottom: 0.2rem;
        }
        h2 {
            margin-top: 1rem;
        }
        .tabs {
            display: flex;
            gap: 8px;
            margin: 16px 0 20px 0;
        }
        .tab-btn {
            flex: 1;
            text-align: center;
            padding: 10px 12px;
            border-radius: 999px;
            border: 1px solid #333;
            background: #181818;
            color: #ccc;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.95rem;
        }
        .tab-btn.tab-active {
            background: #00FA00;
            color: #000;
            border-color: #00FA00;
        }
        .card {
            background: #050505;
            border-radius: 16px;
            padding: 16px 20px;
            margin-bottom: 1rem;
            box-shadow: 0 18px 35px rgba(0, 0, 0, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.03);
        }
        .tab-panel {
            display: none;
        }
        .tab-panel.tab-active {
            display: block;
        }
        label {
            display: block;
            margin-top: 0.5rem;
            font-weight: 500;
        }
        input[type=text] {
            width: 100%;
            padding: 8px 10px;
            margin-top: 0.25rem;
            border-radius: 6px;
            border: 1px solid #444;
            background: #111;
            color: #eee;
        }
        textarea {
            width: 100%;
            padding: 8px 10px;
            margin-top: 0.25rem;
            border-radius: 6px;
            border: 1px solid #444;
            background: #111;
            color: #eee;
            resize: vertical;
        }
        .row {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        button {
            padding: 8px 14px;
            border-radius: 999px;
            border: none;
            cursor: pointer;
            font-weight: 600;
        }
        .btn-primary {
            background: {{ colors.button_bg }};
            color: {{ colors.button_fg }};
            border: 1px solid {{ colors.button_fg }};
        }
        .btn-secondary {
            background: #333;
            color: #eee;
        }
        .btn-danger {
            background: #f44336;
            color: #fff;
        }
        .btn-small {
            font-size: 0.85rem;
            padding: 5px 10px;
        }
        .buttons {
            margin-top: 1rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .status-ok {
            color: #00FA00;
        }
        .status-error {
            color: #ff5555;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }
        th, td {
            border-bottom: 1px solid #333;
            padding: 6px 4px;
        }
        th {
            text-align: left;
            color: #ccc;
        }
        .errors {
            color: #ff5555;
        }
        .flash {
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }
        .section {
            margin-top: 1.5rem;
        }
        a {
            color: #00FAFF;
        }
        ul.yt-list {
            list-style: none;
            padding-left: 0;
        }
        ul.yt-list li {
            margin-bottom: 6px;
            padding-bottom: 4px;
            border-bottom: 1px solid #333;
        }
        small {
            color: #888;
        }
        .badge {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 999px;
            background: #333;
            font-size: 0.75rem;
            margin-left: 4px;
        }
        .badge-ok {
            background: #00FA00;
            color: #000;
        }
        .badge-warn {
            background: #ff9800;
            color: #000;
        }
    </style>
    <script>
        {{ common_js|safe }}
    </script>
</head>
<body data-active-tab="{{ active_tab }}">
    {{ header|safe }}
    <div class="page">
        <h1>{{ title }}</h1>
        <p>Lokale CyNiT webtool om audio te converteren naar MP3 en YouTube-audio te downloaden.</p>

        <!-- TABS -->
        <div class="tabs">
            <button class="tab-btn {% if active_tab == 'converter' %}tab-active{% endif %}"
                    data-tab="converter">Converter</button>
            <button class="tab-btn {% if active_tab == 'youtube' %}tab-active{% endif %}"
                    data-tab="youtube">YouTube → audio</button>
            <button class="tab-btn {% if active_tab == 'settings' %}tab-active{% endif %}"
                    data-tab="settings">Instellingen</button>
        </div>

        <!-- TAB: CONVERTER -->
        <div class="card tab-panel {% if active_tab == 'converter' %}tab-active{% endif %}" id="tab-converter">
            <h2>Converter</h2>
            <form method="POST" action="/">
                <label for="input_folder">Input folder</label>
                <div class="row">
                    <input type="text" id="input_folder" name="input_folder"
                           value="{{ input_folder|default('') }}" />
                    <button type="button" class="btn-secondary btn-small"
                            onclick="chooseFolder('input')">Kies…</button>
                </div>

                <label for="output_folder">Output folder</label>
                <div class="row">
                    <input type="text" id="output_folder" name="output_folder"
                           value="{{ output_folder|default('') }}" />
                    <button type="button" class="btn-secondary btn-small"
                            onclick="chooseFolder('output')">Kies…</button>
                </div>

                <div class="buttons">
                    <button type="submit" class="btn-primary">Convert naar MP3</button>
                    <button type="button" class="btn-secondary" onclick="clearForm()">Leeg formulier</button>
                    <button type="button" class="btn-danger" onclick="restartApp()">Herstart app</button>
                </div>
            </form>

            {% if result %}
                <div class="section">
                    <h2>Resultaat</h2>
                    <p>
                        Input: <code>{{ result.input_folder }}</code><br>
                        Output: <code>{{ result.output_folder }}</code>
                    </p>
                    <p>
                        Bestanden gevonden: {{ result.files_found }}<br>
                        Succesvol geconverteerd: <span class="status-ok">{{ result.converted }}</span>
                    </p>

                    {% if result.details %}
                        <table>
                            <thead>
                                <tr>
                                    <th>Bestand</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for fname, status in result.details %}
                                    <tr>
                                        <td>{{ fname }}</td>
                                        <td>
                                            {% if status == "OK" %}
                                                <span class="status-ok">OK</span>
                                            {% else %}
                                                <span class="status-error">{{ status }}</span>
                                            {% endif %}
                                        </td>
                                    </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    {% endif %}

                    {% if result.errors %}
                        <div class="errors">
                            <h3>Fouten</h3>
                            <ul>
                                {% for err in result.errors %}
                                    <li>{{ err }}</li>
                                {% endfor %}
                            </ul>
                        </div>
                    {% endif %}
                </div>
            {% endif %}
        </div>

        <!-- TAB: YOUTUBE -->
        <div class="card tab-panel {% if active_tab == 'youtube' %}tab-active{% endif %}" id="tab-youtube">
            <h2>YouTube → audio download (meerdere URL's)</h2>
            <form id="yt-form">
                <label for="yt_urls">YouTube URLs (één per lijn)</label>
                <textarea id="yt_urls" name="yt_urls" rows="5"
                          placeholder="https://youtu.be/xxxxxxx
https://www.youtube.com/watch?v=yyyyyyy"></textarea>

                <label for="yt_output_folder">Output folder</label>
                <div class="row">
                    <input type="text" id="yt_output_folder" name="yt_output_folder"
                           value="{{ yt_output_folder|default('') }}" />
                    <button type="button" class="btn-secondary btn-small"
                            onclick="chooseFolder('yt_output')">Kies…</button>
                </div>

                <div class="buttons">
                    <button type="button" class="btn-primary" onclick="startYtJob()">Start downloads</button>
                </div>
            </form>

            <div id="yt-status" class="flash" style="display:none;">
                <h3>YouTube download queue</h3>
                <p id="yt-summary"></p>
                <ul id="yt-items" class="yt-list"></ul>
                <div id="yt-errors" class="errors"></div>
            </div>
        </div>

        <!-- TAB: INSTELLINGEN -->
        <div class="card tab-panel {% if active_tab == 'settings' %}tab-active{% endif %}" id="tab-settings">
            <h2>Instellingen <span class="badge">yt settings.json</span></h2>
            <form method="POST" action="/settings">
                <label for="s_default_input_folder">
                    Standaard input folder
                    <span class="badge badge-ok">converter</span>
                </label>
                <input type="text" id="s_default_input_folder" name="default_input_folder"
                       value="{{ settings.default_input_folder }}" />

                <label for="s_default_output_folder">
                    Standaard output folder
                    <span class="badge badge-ok">converter</span>
                </label>
                <input type="text" id="s_default_output_folder" name="default_output_folder"
                       value="{{ settings.default_output_folder }}" />

                <label for="s_default_yt_output_folder">
                    Standaard YouTube output folder
                    <span class="badge badge-ok">YT downloads</span>
                </label>
                <input type="text" id="s_default_yt_output_folder" name="default_yt_output_folder"
                       value="{{ settings.default_yt_output_folder }}" />

                <label for="s_default_start_dir">
                    Startmap voor map-kiezer
                    <span class="badge badge-warn">Tk dialog</span>
                </label>
                <input type="text" id="s_default_start_dir" name="default_start_dir"
                       value="{{ settings.default_start_dir }}" />

                <div class="buttons">
                    <button type="submit" class="btn-primary">Instellingen opslaan</button>
                </div>
            </form>

            <form method="POST" action="/settings" style="margin-top:0.5rem;">
                <input type="hidden" name="reset" value="1" />
                <button type="submit" class="btn-secondary btn-small">
                    Reset naar defaults
                </button>
            </form>
        </div>
    </div>
        <div id="ctools-overlay"
         style="display:none;position:fixed;inset:0;
                background:rgba(0,0,0,0.85);z-index:9999;
                align-items:center;justify-content:center;
                flex-direction:column;color:#fefefe;
                font-family:system-ui;">
      <div style="border-radius:16px;padding:20px 28px;
                  background:#050505;border:1px solid rgba(255,255,255,0.1);
                  box-shadow:0 18px 40px rgba(0,0,0,0.9);text-align:center;
                  max-width:320px;">
        <div style="font-size:2rem;margin-bottom:8px;">⏳</div>
        <div style="font-weight:600;margin-bottom:4px;">
          CyNiT Tools wordt opgestart…
        </div>
        <div style="font-size:0.9rem;color:#aaa;">
          Even geduld, de hub op poort 5000 wordt gecontroleerd.
        </div>
      </div>
    </div>
    {{ footer|safe }}

    <script>
        // TAB LOGICA
        document.addEventListener("DOMContentLoaded", function () {
            const tabButtons = document.querySelectorAll(".tab-btn");
            const tabPanels = {
                "converter": document.getElementById("tab-converter"),
                "youtube": document.getElementById("tab-youtube"),
                "settings": document.getElementById("tab-settings"),
            };

            function activateTab(name) {
                tabButtons.forEach(btn => {
                    if (btn.dataset.tab === name) {
                        btn.classList.add("tab-active");
                    } else {
                        btn.classList.remove("tab-active");
                    }
                });

                Object.entries(tabPanels).forEach(([key, panel]) => {
                    if (key === name) {
                        panel.classList.add("tab-active");
                    } else {
                        panel.classList.remove("tab-active");
                    }
                });
            }

            tabButtons.forEach(btn => {
                btn.addEventListener("click", () => {
                    activateTab(btn.dataset.tab);
                });
            });

            const initialTab = document.body.getAttribute("data-active-tab") || "converter";
            activateTab(initialTab);
        });

        async function openCtools(evt) {
            if (evt) evt.preventDefault();
            const overlay = document.getElementById("ctools-overlay");
            if (overlay) {
                overlay.style.display = "flex";
            }
            try {
                const resp = await fetch("/open_ctools");
                const data = await resp.json();

                if (!resp.ok || !data.ok) {
                    alert("Kon CyNiT Tools niet openen: " + (data.error || resp.statusText));
                    if (overlay) overlay.style.display = "none";
                    return;
                }

                // Alleen redirecten als alles klaar is
                window.location = data.url;
            } catch (e) {
                alert("Fout bij openen CyNiT Tools: " + e);
                if (overlay) overlay.style.display = "none";
            }
        }

        async function chooseFolder(kind) {
            try {
                const resp = await fetch(`/choose_folder?kind=${encodeURIComponent(kind)}`);
                const data = await resp.json();

                if (data.folder) {
                    if (kind === "input") {
                        document.getElementById("input_folder").value = data.folder;
                    } else if (kind === "output") {
                        document.getElementById("output_folder").value = data.folder;
                    } else if (kind === "yt_output") {
                        document.getElementById("yt_output_folder").value = data.folder;
                    }
                } else if (data.error) {
                    alert("Fout: " + data.error);
                }
            } catch (e) {
                alert("Kon mapselectie niet uitvoeren: " + e);
            }
        }

        function clearForm() {
            document.getElementById("input_folder").value = "";
            document.getElementById("output_folder").value = "";
        }

        async function restartApp() {
            if (!confirm("Weet je zeker dat je de app wilt herstarten?")) {
                return;
            }
            try {
                await fetch("/restart", { method: "POST" });
                setTimeout(() => {
                    window.location.href = "/";
                }, 1500);
            } catch (e) {
                alert("Kon herstart niet triggeren: " + e);
            }
        }

        let currentYtJobId = null;

        async function startYtJob() {
            const form = document.getElementById("yt-form");
            const fd = new FormData(form);

            try {
                const resp = await fetch("/download_youtube", {
                    method: "POST",
                    body: fd
                });
                const data = await resp.json();

                if (!resp.ok || data.error) {
                    alert("Fout bij starten downloads: " + (data.error || resp.statusText));
                    return;
                }

                currentYtJobId = data.job_id;
                document.getElementById("yt-status").style.display = "block";
                document.getElementById("yt-summary").textContent = "Downloads gestart…";
                document.getElementById("yt-items").innerHTML = "";
                document.getElementById("yt-errors").textContent = "";

                pollYtStatus();
            } catch (e) {
                alert("Kon downloads niet starten: " + e);
            }
        }

        async function pollYtStatus() {
            if (!currentYtJobId) {
                return;
            }
            try {
                const resp = await fetch(`/yt_status/${currentYtJobId}`);
                if (!resp.ok) {
                    console.error("yt_status resp not OK");
                    return;
                }
                const job = await resp.json();
                updateYtUI(job);

                if (job.status === "running") {
                    setTimeout(pollYtStatus, 1000);
                } else {
                    const errCount = job.error_count || 0;
                    if (errCount > 0) {
                        alert(`Klaar met fouten: ${errCount} download(s) mislukt. Zie de lijst voor details.`);
                    } else {
                        alert("Alle downloads zijn klaar ✅");
                    }
                    currentYtJobId = null;
                }
            } catch (e) {
                console.error("pollYtStatus error", e);
            }
        }

        function updateYtUI(job) {
            const summary = document.getElementById("yt-summary");
            summary.textContent = `${job.completed}/${job.total} downloads klaar. Status: ${job.status}`;

            const list = document.getElementById("yt-items");
            list.innerHTML = "";

            job.items.forEach(item => {
                const li = document.createElement("li");
                const title = item.title || "(titel nog onbekend)";

                let statusText = "";
                let cls = "";
                if (item.status === "queued") {
                    statusText = "In wachtrij";
                } else if (item.status === "downloading") {
                    statusText = "Bezig met downloaden…";
                } else if (item.status === "done") {
                    statusText = "Klaar";
                    cls = "status-ok";
                } else if (item.status === "error") {
                    statusText = "FOUT";
                    cls = "status-error";
                }

                li.innerHTML = `<strong>{{ '{{' }}item.index{{ '}}' }}. ${title}</strong><br>
                                <span class="${cls}">${statusText}</span>
                                <br><small>${item.url}</small>`;

                if (item.error) {
                    const errDiv = document.createElement("div");
                    errDiv.className = "errors";
                    errDiv.textContent = item.error;
                    li.appendChild(errDiv);
                }

                list.appendChild(li);
            });

            const errBox = document.getElementById("yt-errors");
            if (job.error_count && job.error_count > 0) {
                errBox.textContent = `${job.error_count} fout(en) tot nu toe.`;
            } else {
                errBox.textContent = "";
            }
        }
    </script>
</body>
</html>
"""


# =========================
# Routes
# =========================

@app.route("/", methods=["GET", "POST"])
def index():
    global APP_SETTINGS, THEME_SETTINGS

    result = None

    # Actieve tab uit query (converter | youtube | settings)
    active_tab = request.args.get("tab", "converter")
    if active_tab not in ("converter", "youtube", "settings"):
        active_tab = "converter"

    # App-settings defaults
    input_folder = app_s("default_input_folder")
    output_folder = app_s("default_output_folder")
    yt_output_folder = app_s("default_yt_output_folder")

    # Converter POST
    if request.method == "POST":
        active_tab = "converter"
        input_folder = (request.form.get("input_folder") or app_s("default_input_folder")).strip()
        output_folder = (request.form.get("output_folder") or app_s("default_output_folder")).strip()

        if input_folder and output_folder:
            try:
                result = batch_convert(input_folder, output_folder)
            except Exception as e:
                result = {
                    "input_folder": input_folder,
                    "output_folder": output_folder,
                    "files_found": 0,
                    "converted": 0,
                    "errors": [str(e)],
                    "details": [],
                }
        else:
            result = {
                "input_folder": input_folder,
                "output_folder": output_folder,
                "files_found": 0,
                "converted": 0,
                "errors": ["Gelieve zowel input als output folder in te vullen."],
                "details": [],
            }

    # ---------- CyNiT theming klaarzetten ----------
    colors = THEME_SETTINGS.get("colors", {})
    ui = THEME_SETTINGS.get("ui", {})

    base_css = cynit_layout.common_css(THEME_SETTINGS)
    common_js = cynit_layout.common_js()

    # Link rechtsboven: terug naar CyNiT Tools hub
    right_html = """
      <a href="#" onclick="openCtools(event)"
         style="display:inline-flex;align-items:center;gap:6px;
                padding:6px 12px;border-radius:999px;
                border:1px solid rgba(255,255,255,0.25);
                background:rgba(0,0,0,0.4);
                color:#fefefe;text-decoration:none;font-size:0.85rem;">
        <span style="font-size:1.1rem;">⬅</span>
        <span>Terug naar CyNiT Tools</span>
      </a>
    """

    header_html = cynit_layout.header_html(
        THEME_SETTINGS,
        tools=[],          # later eventueel tools-lijst
        title=APP_TITLE,
        right_html=right_html,
    )
    footer_html = cynit_layout.footer_html()
    # -----------------------------------------------

    return render_template_string(
        PAGE_TEMPLATE,
        title=APP_TITLE,
        active_tab=active_tab,
        result=result,
        input_folder=input_folder,
        output_folder=output_folder,
        yt_output_folder=yt_output_folder,
        settings=APP_SETTINGS,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
    )

@app.route("/logo.png")
def logo_png():
    """
    Serveert hetzelfde CyNiT logo als de hoofd-hub (ctools.py),
    zodat cynit_layout.header_html de afbeelding kan tonen.
    """
    # CYTOOLS_DIR hebben we bovenaan gedefinieerd als .../CyNiT-tools
    return send_from_directory(str(CYTOOLS_DIR), "logo.png")

@app.route("/download_youtube", methods=["POST"])
def download_youtube_route():
    yt_raw = (request.form.get("yt_urls") or "").strip()
    yt_output_folder = (request.form.get("yt_output_folder") or app_s("default_yt_output_folder")).strip()

    if not yt_raw or not yt_output_folder:
        return jsonify({"error": "Gelieve YouTube URLs en een output folder in te vullen."}), 400

    urls = [u.strip() for u in yt_raw.splitlines() if u.strip()]
    if not urls:
        return jsonify({"error": "Geen geldige URLs gevonden."}), 400

    job_id = start_yt_job(urls, yt_output_folder)
    return jsonify({"job_id": job_id})


@app.route("/yt_status/<job_id>")
def yt_status(job_id):
    with YOUTUBE_LOCK:
        job = YOUTUBE_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Onbekende download job."}), 404
        return jsonify(job)

@app.route("/open_ctools")
def open_ctools():
    """
    Checkt of CyNiT Tools (ctools.py) op poort 5000 draait.
    Zo niet: zoek ctools.py in CYTOOLS_DIR, start het met cwd=die map,
    wacht tot de poort open is en geef dan een URL terug.
    """
    import socket
    import subprocess
    import time

    print("[DEBUG] /open_ctools aangeroepen")

    def port_open(host, port) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.3)
                ok = (sock.connect_ex((host, port)) == 0)
                print(f"[DEBUG] port_open {host}:{port} = {ok}")
                return ok
        except Exception as e:
            print(f"[DEBUG] port_open fout: {e}")
            return False

    # 0. Bestaat onze CyNiT tools map?
    if not CYTOOLS_DIR.exists():
        msg = f"CyNiT-tools map bestaat niet op: {CYTOOLS_DIR}"
        print("[ERROR]", msg)
        return jsonify({"ok": False, "error": msg}), 500

    ctools_path = CYTOOLS_DIR / "ctools.py"
    print(f"[DEBUG] Verwachte ctools.py: {ctools_path}")

    if not ctools_path.exists():
        msg = f"ctools.py niet gevonden op {ctools_path}"
        print("[ERROR]", msg)
        return jsonify({"ok": False, "error": msg}), 500

    # 1. Draait ctools al?
    if port_open("127.0.0.1", 5000):
        print("[DEBUG] CTools draait al → direct OK")
        return jsonify({"ok": True, "url": "http://127.0.0.1:5000/", "started": False})

    print("[INFO] CyNiT Tools draait niet → wordt nu opgestart...")

    # 2. Starten van ctools.py in de juiste map
    try:
        subprocess.Popen(
            [sys.executable, str(ctools_path)],
            cwd=str(CYTOOLS_DIR),            # <<< belangrijk!
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        msg = f"Fout bij starten ctools.py: {e}"
        print("[ERROR]", msg)
        return jsonify({"ok": False, "error": msg}), 500

    # 3. Wachten tot poort 5000 open is (max 10s)
    print("[DEBUG] Wachten tot poort 5000 open is...")
    timeout_sec = 10
    start_time = time.time()

    while (time.time() - start_time) < timeout_sec:
        if port_open("127.0.0.1", 5000):
            print("[DEBUG] Poort 5000 is nu open → redirect mogelijk")
            return jsonify({"ok": True, "url": "http://127.0.0.1:5000/", "started": True})
        time.sleep(0.5)

    msg = "Poort 5000 opent niet (ctools start niet of crasht meteen)."
    print("[ERROR]", msg)
    return jsonify({"ok": False, "error": msg}), 500


@app.route("/choose_folder", methods=["GET"])
def choose_folder():
    kind = request.args.get("kind", "input")
    initial = app_s("default_start_dir")
    folder, error = ask_directory_dialog(initial)

    if folder:
        return jsonify({"folder": folder})
    else:
        if error:
            return jsonify({"error": error}), 400
        else:
            return jsonify({"error": "Geen map geselecteerd."}), 400


@app.route("/settings", methods=["POST"])
def settings_route():
    global APP_SETTINGS

    # Reset naar defaults?
    if request.form.get("reset") == "1":
        APP_SETTINGS = APP_DEFAULT_SETTINGS.copy()
        save_app_settings(APP_SETTINGS)
        return redirect(url_for("index", tab="settings"))

    # Anders: update vanuit formulier
    updated = dict(APP_SETTINGS)

    def update_key(form_key, setting_key):
        val = (request.form.get(form_key) or "").strip()
        if val:
            updated[setting_key] = val

    update_key("default_input_folder", "default_input_folder")
    update_key("default_output_folder", "default_output_folder")
    update_key("default_yt_output_folder", "default_yt_output_folder")
    update_key("default_start_dir", "default_start_dir")

    APP_SETTINGS = updated
    save_app_settings(APP_SETTINGS)

    return redirect(url_for("index", tab="settings"))


@app.route("/restart", methods=["POST"])
def restart():
    t = threading.Thread(target=restart_process_delayed, args=(1.0,), daemon=True)
    t.start()
    return "Restarting…", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# =========================
# Entry point
# =========================

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5555, debug=False)
