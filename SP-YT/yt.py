#!/usr/bin/env python3
"""
yt.py - CyNiT YouTube Converter (Flask webapp)

Tabs:
- Converter: batch-conversie + normalisatie naar mp3
- YouTube: meerdere URLs → audio downloaden (parallel, met retries)
- Instellingen: paden + yt-instellingen

Extra:
- Bestandsnaam na download proberen te zetten als "Artist - Titel.ext"
- Bij MP3-export ID3-tags 'artist' en 'title' invullen op basis van bestandsnaam
"""

from __future__ import annotations

from pathlib import Path
import sys
import yt_dlp
import logging
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple

# ====== PAD FIX ======
BASE_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASE_DIR.parent.resolve()
CYNT_ROOT = PROJECT_ROOT / "CyNiT-tools"

for root in [CYNT_ROOT, PROJECT_ROOT]:
    if root.exists() and str(root) not in sys.path:
        sys.path.insert(0, str(root))

import cynit_theme
import cynit_layout

# ====== HIER MOET DEZE STAAN! ======
from flask import Flask, render_template_string, request, redirect, send_from_directory



log = logging.getLogger("cynit-yt")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ====== CONFIG ======

SETTINGS_FILE = BASE_DIR / "yt_settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "paths": {
        "input_folder": "C:/mus",     # bron (bijv. .m4a/.webm)
        "output_folder": "C:/mus-e",  # genormaliseerde mp3
        "download_folder": "C:/mus",  # YouTube-downloads
        "ffmpeg": "ffmpeg",           # ffmpeg in PATH
    },
    "yt": {
        "max_workers": 3,
        "max_retries": 6,
        "sleep_between_retries": 2.0,
    },
}

SETTINGS: Dict[str, Any] = {}


def ensure_folder(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.error("Kon map niet aanmaken %s: %s", path, e)


def load_yt_settings() -> Dict[str, Any]:
    """Laad yt_settings.json; maak aan met defaults als hij niet bestaat."""
    if not SETTINGS_FILE.exists():
        log.info("yt_settings.json niet gevonden → wordt aangemaakt met defaults.")
        data = DEFAULT_SETTINGS.copy()
        try:
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Kon yt_settings.json niet schrijven: %s", e)
        return data

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Kon yt_settings.json niet lezen, gebruik defaults: %s", e)
        data = DEFAULT_SETTINGS.copy()

    # zachte merge met defaults zodat nieuwe keys er ook zijn
    merged = DEFAULT_SETTINGS.copy()
    for k, v in data.items():
        if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def save_yt_settings(data: Dict[str, Any]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Kon yt_settings.json niet opslaan: %s", e)


SETTINGS = load_yt_settings()

# ====== HULP: bestandsnaam & metadata ======

def safe_filename(name: str) -> str:
    """Maak een bestandsnaam veilig voor Windows."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in name)
    cleaned = cleaned.strip().strip(".")
    if not cleaned:
        return "track"
    return cleaned


def parse_artist_title_from_basename(basename: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Probeer uit 'Artist - Titel' de velden te halen.
    Als er geen ' - ' staat, gebruiken we alles als title.
    """
    base = basename.strip()
    if " - " in base:
        artist, title = base.split(" - ", 1)
        return artist.strip() or None, title.strip() or None
    return None, base or None


# ====== FFMPEG CONVERT + NORMALISATIE ======

def convert_to_mp3_normalized(
    input_path: Path,
    output_path: Path,
    ffmpeg_bin: str,
    max_retries: int = 3,
) -> bool:
    """
    Converteer audio naar MP3 met loudnorm en vul metadata in:
    - artist/title op basis van bestandsnaam 'Artist - Titel.mp3'
    """
    artist, title = parse_artist_title_from_basename(output_path.stem)

    for attempt in range(1, max_retries + 1):
        log.info(
            "[FFMPEG] (%d/%d) Converteer + normaliseer: %s -> %s",
            attempt,
            max_retries,
            input_path,
            output_path,
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",  # alleen errors tonen
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            "192k",
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
        ]

        # Metadata instellen
        if artist:
            cmd += ["-metadata", f"artist={artist}"]
        if title:
            cmd += ["-metadata", f"title={title}"]

        cmd.append(str(output_path))

        try:
            import subprocess

            subprocess.check_call(cmd)
            return True
        except subprocess.CalledProcessError as e:
            log.error("[FFMPEG] Fout bij conversie: %s", e)
            time.sleep(1.0 * attempt)
        except FileNotFoundError:
            log.error("[FFMPEG] ffmpeg niet gevonden. ffmpeg_bin=%s", ffmpeg_bin)
            return False

    return False


def batch_convert(input_folder: str, output_folder: str) -> Dict[str, Any]:
    inp = Path(input_folder).expanduser()
    outp = Path(output_folder).expanduser()

    result: Dict[str, Any] = {
        "input_folder": str(inp),
        "output_folder": str(outp),
        "files_found": 0,
        "converted": 0,
        "errors": [],
        "details": [],  # lijst van dicts
    }

    if not inp.is_dir():
        result["errors"].append(f"Inputfolder bestaat niet: {inp}")
        return result

    ensure_folder(outp)

    VALID_EXTS = (".m4a", ".webm", ".mp4", ".opus")
    files = sorted(f for f in inp.iterdir() if f.suffix.lower() in VALID_EXTS)

    result["files_found"] = len(files)
    if not files:
        return result

    ffmpeg_bin = SETTINGS.get("paths", {}).get("ffmpeg", "ffmpeg")

    for f in files:
        output_name = f.stem + ".mp3"
        output_path = outp / output_name

        ok = convert_to_mp3_normalized(f, output_path, ffmpeg_bin, max_retries=3)
        row = {
            "input": f.name,
            "output": output_name,
            "status": "OK" if ok else "FOUT",
        }
        result["details"].append(row)
        if ok:
            result["converted"] += 1
        else:
            result["errors"].append(f"Fout bij converteren: {f.name}")

    return result


# ====== YOUTUBE DOWNLOAD (PARALLEL + METADATA) ======

def youtube_download_single(url: str, download_folder: Path) -> Dict[str, Any]:
    """
    Download één YouTube-URL.
    - Slaat audio op in download_folder
    - Probeert 'Artist - Titel.ext' als bestandsnaam te gebruiken
    - Returnt dict met info voor de UI
    """
    download_folder = download_folder.expanduser()
    ensure_folder(download_folder)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(download_folder / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
    }

    res: Dict[str, Any] = {
        "url": url,
        "ok": False,
        "filename": None,
        "title": None,
        "artist": None,
        "error": None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("Geen info van yt-dlp (video mogelijk niet beschikbaar).")

            # Bepaal originele pad zoals yt-dlp het gemaakt heeft
            orig_path = Path(ydl.prepare_filename(info))
            ext = orig_path.suffix

            # Haal metadata uit info
            title = info.get("track") or info.get("title") or ""
            artist = (
                info.get("artist")
                or info.get("uploader")
                or info.get("channel")
                or ""
            )

            if artist:
                nice_base = f"{artist} - {title}"
            else:
                nice_base = title or "track"

            nice_base = safe_filename(nice_base)
            new_path = orig_path.with_name(nice_base + ext)

            if new_path != orig_path:
                try:
                    orig_path.rename(new_path)
                except Exception as e:
                    log.warning("Kon %s niet hernoemen naar %s: %s", orig_path, new_path, e)
                    new_path = orig_path  # fallback

            res.update(
                {
                    "ok": True,
                    "filename": new_path.name,
                    "title": title,
                    "artist": artist or None,
                }
            )
            log.info("[YT-DLP] Downloaded: %s (%s)", new_path.name, url)

    except Exception as e:
        res["error"] = str(e)
        log.error("[YT-DLP] Fout bij %s: %s", url, e)

    return res


def youtube_batch_download(urls: List[str]) -> Dict[str, Any]:
    """
    Download meerdere URLs parallel, met retries.
    Geeft dict terug met 'results' (lijst) en 'summary'.
    """
    download_folder = Path(SETTINGS.get("paths", {}).get("download_folder", "C:/mus"))
    yt_cfg = SETTINGS.get("yt", {})
    max_workers = int(yt_cfg.get("max_workers", 3) or 3)
    max_retries = int(yt_cfg.get("max_retries", 6) or 6)
    sleep_between = float(yt_cfg.get("sleep_between_retries", 2.0) or 2.0)

    total = len(urls)
    done_counter = 0
    done_lock = threading.Lock()
    results: List[Dict[str, Any]] = []

    def worker(u: str) -> Dict[str, Any]:
        nonlocal done_counter
        res: Dict[str, Any] = {}
        for attempt in range(1, max_retries + 1):
            log.info("[YT] %s → poging %d/%d", u, attempt, max_retries)
            res = youtube_download_single(u, download_folder)
            if res.get("ok"):
                break
            time.sleep(sleep_between * attempt)

        with done_lock:
            done_counter += 1
            log.info("[YT] voortgang: %d/%d klaar", done_counter, total)

        if not res.get("ok"):
            res["error"] = res.get("error") or f"Download faalde na {max_retries} pogingen."
        return res

    if total == 0:
        return {
            "results": [],
            "summary": {"total": 0, "ok": 0, "failed": 0},
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(worker, u) for u in urls]
        for fut in as_completed(futs):
            results.append(fut.result())

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = total - ok_count

    return {
        "results": results,
        "summary": {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
        },
    }


# ====== FLASK APP ======

app = Flask(__name__)
app.secret_key = "cynit-yt-dev-key"  # enkel lokaal, dus prima

PAGE_TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>CyNiT YouTube Converter</title>
  <style>
    {{ base_css|safe }}

    .page {
      max-width: 1100px;
      margin: 24px auto 40px;
    }

    .tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      border-bottom: 1px solid #333;
      padding-bottom: 4px;
    }
    .tab {
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.9rem;
      cursor: pointer;
      border: 1px solid transparent;
      text-decoration: none;
      color: {{ colors.general_fg }};
    }
    .tab.active {
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      border-color: {{ colors.button_fg }};
    }
    .tab:hover {
      filter: brightness(1.1);
    }

    .card {
      background: #111;
      border-radius: 16px;
      padding: 16px 20px;
      box-shadow: 0 18px 35px rgba(0,0,0,0.9);
      border: 1px solid rgba(255,255,255,0.04);
      margin-bottom: 18px;
    }
    .card h2 {
      margin-top: 0;
      color: {{ colors.title }};
      font-size: 1.1rem;
    }

    label {
      display: block;
      margin-top: 10px;
      margin-bottom: 4px;
      font-size: 0.9rem;
    }
    input[type="text"], textarea, input[type="number"] {
      width: 100%;
      padding: 6px 8px;
      border-radius: 8px;
      border: 1px solid #333;
      background: #050505;
      color: {{ colors.general_fg }};
      font-family: Consolas, monospace;
      font-size: 0.9rem;
    }
    textarea {
      min-height: 120px;
      resize: vertical;
    }

    .button-row {
      margin-top: 12px;
      display: flex;
      gap: 8px;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 999px;
      border: none;
      background: {{ colors.button_bg }};
      color: {{ colors.button_fg }};
      font-family: {{ ui.font_buttons }};
      font-size: 0.9rem;
      cursor: pointer;
      text-decoration: none;
    }
    .btn:hover {
      filter: brightness(1.15);
    }

    .muted {
      color: #999;
      font-size: 0.9rem;
    }

    .result-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 0.9rem;
    }
    .result-table th,
    .result-table td {
      border: 1px solid #333;
      padding: 4px 6px;
    }
    .result-table th {
      background: #222;
      color: {{ colors.title }};
    }
    .row-ok {
      background: #0f2410;
    }
    .row-err {
      background: #241010;
    }
  </style>
  <script>
    {{ common_js|safe }}
  </script>
</head>
<body>
  {{ header|safe }}
  <div class="page">
    <div class="tabs">
      <a href="{{ url_for('index', tab='converter') }}" class="tab {% if active_tab=='converter' %}active{% endif %}">Converter</a>
      <a href="{{ url_for('index', tab='youtube') }}" class="tab {% if active_tab=='youtube' %}active{% endif %}">YouTube → audio</a>
      <a href="{{ url_for('index', tab='settings') }}" class="tab {% if active_tab=='settings' %}active{% endif %}">Instellingen</a>
    </div>

    {# === CONVERTER TAB === #}
    {% if active_tab == 'converter' %}
      <div class="card">
        <h2>Batch converteren & normaliseren naar MP3</h2>
        <p class="muted">
          Converteer alle <code>.m4a / .webm / .mp4 / .opus</code> in de inputmap naar
          genormaliseerde MP3 in de outputmap. Metadata <code>artist/title</code> wordt
          afgeleid van de bestandsnaam, bij voorkeur <code>Artist - Titel.mp3</code>.
        </p>
        <form method="post" action="{{ url_for('convert') }}">
          <label>Input folder</label>
          <input type="text" name="input_folder" value="{{ input_folder }}">

          <label>Output folder</label>
          <input type="text" name="output_folder" value="{{ output_folder }}">

          <div class="button-row">
            <button type="submit" class="btn">Convert → MP3</button>
          </div>
        </form>

        {% if convert_result %}
          <hr>
          <p class="muted">
            Gevonden bestanden: {{ convert_result.files_found }} ·
            Geconverteerd: {{ convert_result.converted }} ·
            Fouten: {{ convert_result.errors|length }}
          </p>

          {% if convert_result.details %}
            <table class="result-table">
              <thead>
                <tr>
                  <th>Input</th>
                  <th>Output</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {% for row in convert_result.details %}
                  <tr class="{% if row.status == 'OK' %}row-ok{% else %}row-err{% endif %}">
                    <td>{{ row.input }}</td>
                    <td>{{ row.output }}</td>
                    <td>{{ row.status }}</td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          {% endif %}

          {% if convert_result.errors %}
            <p class="muted" style="margin-top:8px;">
              <strong>Errors:</strong><br>
              {% for e in convert_result.errors %}
                • {{ e }}<br>
              {% endfor %}
            </p>
          {% endif %}
        {% endif %}
      </div>
    {% endif %}

    {# === YOUTUBE TAB === #}
    {% if active_tab == 'youtube' %}
      <div class="card">
        <h2>YouTube → audio download</h2>
        <p class="muted">
          Plak meerdere YouTube URLs onder elkaar. Ze worden parallel gedownload naar
          <code>{{ download_folder }}</code>. Bestandsnamen worden zoveel mogelijk
          <code>Artist - Titel.ext</code>, zodat de converter er mooie MP3-tags van kan maken.
        </p>
        <form method="post" action="{{ url_for('download_youtube') }}">
          <label>YouTube URLs (één per lijn)</label>
          <textarea name="urls">{{ urls_text }}</textarea>

          <div class="button-row">
            <button type="submit" class="btn">Download audio</button>
          </div>
        </form>

        {% if yt_summary %}
          <hr>
          <p class="muted">
            Totaal: {{ yt_summary.total }} ·
            OK: {{ yt_summary.ok }} ·
            Fout: {{ yt_summary.failed }}
          </p>
        {% endif %}

        {% if yt_results %}
          <table class="result-table">
            <thead>
              <tr>
                <th>Titel</th>
                <th>Artiest / Uploader</th>
                <th>Bestand</th>
                <th>Status</th>
                <th>Fout</th>
              </tr>
            </thead>
            <tbody>
              {% for r in yt_results %}
                <tr class="{% if r.ok %}row-ok{% else %}row-err{% endif %}">
                  <td>{{ r.title or "—" }}</td>
                  <td>{{ r.artist or "—" }}</td>
                  <td>{{ r.filename or "—" }}</td>
                  <td>{% if r.ok %}✅ OK{% else %}❌ Fout{% endif %}</td>
                  <td>{{ r.error or "" }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}
      </div>
    {% endif %}

    {# === SETTINGS TAB === #}
    {% if active_tab == 'settings' %}
      <div class="card">
        <h2>Instellingen</h2>
        <form method="post" action="{{ url_for('update_settings') }}">
          <label>Download folder (YouTube)</label>
          <input type="text" name="download_folder" value="{{ download_folder }}">

          <label>Input folder (Converter)</label>
          <input type="text" name="input_folder" value="{{ input_folder }}">

          <label>Output folder (Converter)</label>
          <input type="text" name="output_folder" value="{{ output_folder }}">

          <label>ffmpeg pad (optioneel, leeg = 'ffmpeg')</label>
          <input type="text" name="ffmpeg" value="{{ ffmpeg_path }}">

          <label>Max. parallelle downloads</label>
          <input type="number" name="yt_max_workers" min="1" max="10" value="{{ yt_max_workers }}">

          <label>Max. retries per URL</label>
          <input type="number" name="yt_max_retries" min="1" max="20" value="{{ yt_max_retries }}">

          <div class="button-row">
            <button type="submit" class="btn">Instellingen opslaan</button>
          </div>
        </form>
      </div>
    {% endif %}
  </div>
  {{ footer|safe }}
</body>
</html>
"""


def render_main_page(
    active_tab: str = "converter",
    convert_result: Optional[Dict[str, Any]] = None,
    yt_results: Optional[List[Dict[str, Any]]] = None,
    yt_summary: Optional[Dict[str, Any]] = None,
    urls_text: str = "",
):
    global SETTINGS
    colors = cynit_theme.load_settings().get("colors", {})
    ui = cynit_theme.load_settings().get("ui", {})

    paths_cfg = SETTINGS.get("paths", {})
    yt_cfg = SETTINGS.get("yt", {})

    input_folder = paths_cfg.get("input_folder", DEFAULT_SETTINGS["paths"]["input_folder"])
    output_folder = paths_cfg.get("output_folder", DEFAULT_SETTINGS["paths"]["output_folder"])
    download_folder = paths_cfg.get("download_folder", DEFAULT_SETTINGS["paths"]["download_folder"])
    ffmpeg_path = paths_cfg.get("ffmpeg", DEFAULT_SETTINGS["paths"]["ffmpeg"])

    yt_max_workers = int(yt_cfg.get("max_workers", DEFAULT_SETTINGS["yt"]["max_workers"]))
    yt_max_retries = int(yt_cfg.get("max_retries", DEFAULT_SETTINGS["yt"]["max_retries"]))

    base_css = cynit_layout.common_css(cynit_theme.load_settings())
    common_js = cynit_layout.common_js()
    header_html = cynit_layout.header_html(
        cynit_theme.load_settings(),
        tools=[],
        title="CyNiT YouTube Converter",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    # simpele wrapper-structs zodat we in jinja .files_found etc kunnen doen
    class Obj(dict):
        def __getattr__(self, item):
            return self.get(item)

    if isinstance(convert_result, dict):
        convert_result = Obj(convert_result)
        if isinstance(convert_result.get("details"), list):
            convert_result["details"] = [Obj(d) for d in convert_result["details"]]

    if isinstance(yt_summary, dict):
        yt_summary = Obj(yt_summary)

    return render_template_string(
        PAGE_TEMPLATE,
        base_css=base_css,
        common_js=common_js,
        header=header_html,
        footer=footer_html,
        colors=colors,
        ui=ui,
        active_tab=active_tab,
        input_folder=input_folder,
        output_folder=output_folder,
        download_folder=download_folder,
        ffmpeg_path=ffmpeg_path,
        yt_max_workers=yt_max_workers,
        yt_max_retries=yt_max_retries,
        convert_result=convert_result,
        yt_results=yt_results or [],
        yt_summary=yt_summary,
        urls_text=urls_text,
    )


# ====== ROUTES ======

@app.route("/", methods=["GET"])
def index():
    tab = request.args.get("tab") or "converter"
    return render_main_page(active_tab=tab)

@app.route("/logo.png")
def logo_png():
    return send_from_directory(str(CYNT_ROOT), "logo.png")


@app.route("/convert", methods=["POST"])
def convert():
    global SETTINGS
    paths_cfg = SETTINGS.get("paths", {})

    input_folder = request.form.get("input_folder", "").strip() or paths_cfg.get(
        "input_folder", DEFAULT_SETTINGS["paths"]["input_folder"]
    )
    output_folder = request.form.get("output_folder", "").strip() or paths_cfg.get(
        "output_folder", DEFAULT_SETTINGS["paths"]["output_folder"]
    )

    # kleine update in settings zodat de volgende keer de waarden onthouden worden
    paths_cfg["input_folder"] = input_folder
    paths_cfg["output_folder"] = output_folder
    SETTINGS["paths"] = paths_cfg
    save_yt_settings(SETTINGS)

    result = batch_convert(input_folder, output_folder)
    return render_main_page(active_tab="converter", convert_result=result)


@app.route("/download_youtube", methods=["POST"])
def download_youtube():
    urls_raw = request.form.get("urls", "").strip()
    urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]

    batch_res = youtube_batch_download(urls)
    yt_results = batch_res.get("results", [])
    yt_summary = batch_res.get("summary", {})

    return render_main_page(
        active_tab="youtube",
        yt_results=yt_results,
        yt_summary=yt_summary,
        urls_text=urls_raw,
    )


@app.route("/update_settings", methods=["POST"])
def update_settings():
    global SETTINGS
    paths_cfg = SETTINGS.get("paths", {})
    yt_cfg = SETTINGS.get("yt", {})

    download_folder = request.form.get("download_folder", "").strip()
    input_folder = request.form.get("input_folder", "").strip()
    output_folder = request.form.get("output_folder", "").strip()
    ffmpeg_path = request.form.get("ffmpeg", "").strip()
    yt_max_workers = request.form.get("yt_max_workers", "").strip()
    yt_max_retries = request.form.get("yt_max_retries", "").strip()

    if download_folder:
        paths_cfg["download_folder"] = download_folder
    if input_folder:
        paths_cfg["input_folder"] = input_folder
    if output_folder:
        paths_cfg["output_folder"] = output_folder
    if ffmpeg_path:
        paths_cfg["ffmpeg"] = ffmpeg_path

    if yt_max_workers:
        try:
            yt_cfg["max_workers"] = int(yt_max_workers)
        except ValueError:
            pass
    if yt_max_retries:
        try:
            yt_cfg["max_retries"] = int(yt_max_retries)
        except ValueError:
            pass

    SETTINGS["paths"] = paths_cfg
    SETTINGS["yt"] = yt_cfg
    save_yt_settings(SETTINGS)

    return redirect(url_for("index", tab="settings"))


# ====== MAIN ======

if __name__ == "__main__":
    # Alle IP’s zodat je ook via je LAN-IP kunt testen
    app.run(host="0.0.0.0", port=5555, debug=False)
