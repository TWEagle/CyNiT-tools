import os
import sys
import time
import subprocess
from flask import Flask, request, render_template_string, jsonify
import threading

# --- Tkinter voor folderselectie (lokaal) ---
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    tk = None
    filedialog = None

app = Flask(__name__)

# ---------- Audio conversie helpers ----------

def convert_to_mp3(input_file, output_file):
    """
    Converteer één audio/video bestand naar .mp3 via ffmpeg.
    Ondersteunt bv. .m4a, .mp4, .webm, ... zolang ffmpeg het snapt.
    """
    cmd = [
        "ffmpeg",
        "-y",  # overschrijf zonder vragen
        "-i", input_file,
        "-codec:a", "libmp3lame",
        "-q:a", "2",  # kwaliteit (0-9, lager = beter)
        output_file,
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def batch_convert(input_folder, output_folder):
    """
    Converteer alle .m4a/.mp4/.webm-bestanden in input_folder naar .mp3 in output_folder.
    Geeft een dict terug met resultaten.
    """
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

    VALID_EXTS = (".m4a", ".mp4", ".webm")

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
        output_name = file.rsplit(".", 1)[0] + ".mp3"
        output_path = os.path.join(output_folder, output_name)

        ok = convert_to_mp3(input_path, output_path)
        if ok:
            result["converted"] += 1
            result["details"].append((file, "OK"))
        else:
            result["errors"].append(f"Fout bij converteren: {file}")
            result["details"].append((file, "FOUT"))

    return result


# ---------- Folder picker (Tkinter) ----------

def ask_directory_dialog(initial_dir=None):
    """
    Opent een native folder-selectiedialoog via Tkinter.
    Geeft (folder, error) terug.
    """
    if tk is None or filedialog is None:
        return None, "Tkinter is niet beschikbaar op dit systeem."

    root = tk.Tk()
    root.withdraw()
    # venster op voorgrond
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    folder = filedialog.askdirectory(
        initialdir=initial_dir or os.getcwd(),
        title="Kies een map"
    )
    root.destroy()

    if not folder:
        return None, "Geen map geselecteerd."
    return folder, None


# ---------- Restart helper ----------

def restart_process_delayed():
    """
    Herstart het huidige Python-proces na een korte delay.
    Wordt in een aparte thread uitgevoerd zodat HTTP-respons eerst kan terugkeren.
    """
    time.sleep(0.5)
    python = sys.executable
    os.execl(python, python, *sys.argv)


# ---------- HTML template (CyNiT style) ----------

PAGE_TEMPLATE = """
<!doctype html>
<html lang="nl">
<head>
    <meta charset="utf-8">
    <title>CyNiT Batch M4A/MP4/WebM → MP3 Converter</title>
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #000;
            color: #f5f5f5;
            margin: 0;
            padding: 0;
        }
        .page {
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            padding: 2rem 1rem;
        }
        .card {
            background: #111;
            border-radius: 16px;
            padding: 1.75rem 2rem;
            max-width: 750px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0,0,0,0.7);
            border: 1px solid #333;
        }
        h1 {
            margin-top: 0;
            margin-bottom: 0.25rem;
            font-size: 1.6rem;
        }
        .badge {
            display: inline-block;
            background: #FEF102;
            color: #000;
            padding: 0.2rem 0.7rem;
            font-size: 0.75rem;
            font-weight: 700;
            border-radius: 999px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
        }
        .subtitle {
            color: #ccc;
            font-size: 0.9rem;
            margin-bottom: 1.25rem;
        }
        label {
            display: block;
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 0.15rem;
        }
        input[type="text"] {
            width: 100%;
            padding: 0.5rem 0.7rem;
            border-radius: 10px;
            border: 1px solid #333;
            background: #181818;
            color: #f5f5f5;
            font-size: 0.9rem;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #009844;
            box-shadow: 0 0 0 1px #00984455;
        }
        .folder-row {
            margin-bottom: 0.75rem;
        }
        .folder-input {
            display: flex;
            gap: 0.5rem;
            align-items: center;
            margin-bottom: 0.4rem;
        }
        .btn-primary {
            background: linear-gradient(135deg, #FEF102, #FFCC00);
            border: none;
            color: #000;
            padding: 0.6rem 1.3rem;
            border-radius: 999px;
            font-size: 0.95rem;
            font-weight: 700;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            box-shadow: 0 8px 18px rgba(254,241,2,0.35);
        }
        .btn-primary:hover {
            filter: brightness(1.05);
        }
        .btn-primary:active {
            transform: translateY(1px);
            box-shadow: 0 4px 10px rgba(254,241,2,0.25);
        }
        .btn-secondary {
            background: #222;
            border: 1px solid #444;
            color: #f5f5f5;
            padding: 0.45rem 0.9rem;
            border-radius: 999px;
            font-size: 0.8rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
        }
        .btn-secondary:hover {
            background: #2b2b2b;
        }
        .icon-dot {
            width: 9px;
            height: 9px;
            border-radius: 999px;
            background: #009844;
            box-shadow: 0 0 10px rgba(0,152,68,0.8);
        }
        .hint {
            font-size: 0.8rem;
            color: #888;
            margin-bottom: 1rem;
        }
        .result-block {
            margin-top: 1.5rem;
            border-top: 1px solid #333;
            padding-top: 1rem;
        }
        .result-summary {
            font-size: 0.9rem;
            margin-bottom: 0.75rem;
        }
        .result-list {
            max-height: 250px;
            overflow-y: auto;
            border: 1px solid #222;
            border-radius: 10px;
            padding: 0.5rem 0.75rem;
            background: #151515;
            font-size: 0.8rem;
        }
        .result-item {
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid #222;
            padding: 0.25rem 0;
        }
        .result-item:last-child {
            border-bottom: none;
        }
        .status-ok {
            color: #55dd88;
        }
        .status-error {
            color: #ff7777;
        }
        .errors {
            color: #ff7777;
            font-size: 0.8rem;
            margin-top: 0.5rem;
        }
        .footer {
            margin-top: 1.25rem;
            font-size: 0.75rem;
            color: #777;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .footer span.cynit {
            color: #FEF102;
            font-weight: 600;
        }
        .button-row {
            display: flex;
            gap: 0.6rem;
            align-items: center;
            margin-top: 0.5rem;
        }
    </style>
</head>
<body>
    <div class="page">
        <div class="card">
            <div class="badge">CyNiT Tools</div>
            <h1>Batch M4A / MP4 / WebM → MP3</h1>
            <div class="subtitle">
                Kies een inputmap met .m4a, .mp4 of .webm bestanden en een outputmap voor de .mp3 bestanden.
            </div>

            <form method="post">
                <div class="folder-row">
                    <label for="input_folder">Input folder:</label>
                    <div class="folder-input">
                        <input type="text" id="input_folder" name="input_folder"
                               value="{{ input_folder or '' }}"
                               placeholder="bv. C:\\Audio\\M4A">
                        <button type="button" class="btn-secondary" onclick="chooseFolder('input')">
                            Kies…
                        </button>
                    </div>
                </div>

                <div class="folder-row">
                    <label for="output_folder">Output folder (voor .mp3):</label>
                    <div class="folder-input">
                        <input type="text" id="output_folder" name="output_folder"
                               value="{{ output_folder or '' }}"
                               placeholder="bv. C:\\Audio\\MP3">
                        <button type="button" class="btn-secondary" onclick="chooseFolder('output')">
                            Kies…
                        </button>
                    </div>
                </div>

                <div class="hint">
                    Dit zijn paden op de machine waar deze webapp draait.<br>
                    De outputmap wordt automatisch aangemaakt indien nodig.
                </div>

                <div class="button-row">
                    <button type="submit" class="btn-primary">
                        <span class="icon-dot"></span>
                        <span>Start batch conversie</span>
                    </button>
                    <button type="button" class="btn-secondary" onclick="restartTool()">
                        Herstart tool
                    </button>
                </div>
            </form>

            {% if result %}
            <div class="result-block">
                <div class="result-summary">
                    <div>Input: {{ result.input_folder }}</div>
                    <div>Output: {{ result.output_folder }}</div>
                    <div>Gevonden bestanden (.m4a/.mp4/.webm): {{ result.files_found }}</div>
                    <div>Succesvol geconverteerd: {{ result.converted }}</div>
                </div>

                {% if result.details %}
                <div class="result-list">
                    {% for fname, status in result.details %}
                        <div class="result-item">
                            <span>{{ fname }}</span>
                            {% if status == 'OK' %}
                                <span class="status-ok">OK</span>
                            {% else %}
                                <span class="status-error">FOUT</span>
                            {% endif %}
                        </div>
                    {% endfor %}
                </div>
                {% endif %}

                {% if result.errors %}
                    <div class="errors">
                        {% for err in result.errors %}
                            <div>⚠ {{ err }}</div>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>
            {% endif %}

            <div class="footer">
                <span class="cynit">CyNiT</span>
                <span>Focus. Automate. Repeat.</span>
            </div>
        </div>
    </div>

    <script>
        async function chooseFolder(kind) {
            try {
                const resp = await fetch("/choose_folder?kind=" + encodeURIComponent(kind), {
                    method: "GET",
                    cache: "no-store"
                });
                const data = await resp.json();
                if (resp.ok && data.folder) {
                    if (kind === "input") {
                        document.getElementById("input_folder").value = data.folder;
                    } else {
                        document.getElementById("output_folder").value = data.folder;
                    }
                } else if (data.error) {
                    alert(data.error);
                } else {
                    alert("Onbekende fout bij kiezen van map.");
                }
            } catch (e) {
                alert("Kon folder niet kiezen: " + e);
            }
        }

        async function restartTool() {
            if (!confirm("Weet je zeker dat je de tool wil herstarten?")) {
                return;
            }
            try {
                await fetch("/restart", { method: "POST" });
                // Kleine delay, dan pagina herladen
                setTimeout(function () {
                    window.location.href = "/";
                }, 1200);
            } catch (e) {
                alert("Kon herstart niet triggeren: " + e);
            }
        }
    </script>
</body>
</html>
"""


# ---------- Routes ----------

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    input_folder = ""
    output_folder = ""

    if request.method == "POST":
        input_folder = request.form.get("input_folder", "").strip()
        output_folder = request.form.get("output_folder", "").strip()

        if input_folder and output_folder:
            result = batch_convert(input_folder, output_folder)
        else:
            result = {
                "input_folder": input_folder,
                "output_folder": output_folder,
                "files_found": 0,
                "converted": 0,
                "errors": ["Gelieve zowel input als output folder in te vullen."],
                "details": [],
            }

    return render_template_string(
        PAGE_TEMPLATE,
        result=result,
        input_folder=input_folder,
        output_folder=output_folder,
    )


@app.route("/choose_folder", methods=["GET"])
def choose_folder():
    kind = request.args.get("kind", "input")
    initial = os.getcwd()
    folder, error = ask_directory_dialog(initial)
    if folder:
        return jsonify({"folder": folder})
    else:
        # gebruiker kan ook gewoon op Cancel klikken → dat is geen “harde fout”
        return jsonify({"error": error or "Geen map geselecteerd."}), 400


@app.route("/restart", methods=["POST"])
def restart():
    # Start een thread die het proces herstart
    t = threading.Thread(target=restart_process_delayed, daemon=True)
    t.start()
    return "Restarting…", 200


if __name__ == "__main__":
    # Let op: debug=False om dubbele processen (reloader) te vermijden met Tkinter
    app.run(debug=False, port=5555)
