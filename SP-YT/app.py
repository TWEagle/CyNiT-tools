import os
import pathlib
import subprocess
import threading
import uuid
import yt_dlp

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    send_from_directory,
    render_template_string,
    jsonify,
    flash,
)

# === Basisconfig ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DEFAULT_OUTPUT_FOLDER = os.path.join(BASE_DIR, "output")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DEFAULT_OUTPUT_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"mp4", "mkv", "mov", "avi", "webm", "flv"}

app = Flask(__name__)
app.secret_key = "change-me-to-a-random-string"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Eenvoudige job-tracker in geheugen
JOBS = {}


# === Helpers ===
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_audio_to_mp3(video_path: str, output_folder: str) -> str:
    """
    Neemt een videobestand en maakt er een MP3 van in output_folder.
    Returnt de bestandsnaam van de MP3.
    """
    video_name = pathlib.Path(video_path).name
    stem = pathlib.Path(video_name).stem
    mp3_name = f"{stem}.mp3"
    mp3_path = os.path.join(output_folder, mp3_name)

    os.makedirs(output_folder, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",
        mp3_path,
    ]

    subprocess.run(cmd, check=True)
    return mp3_name


def run_job(job_id: str, video_path: str, output_folder: str):
    """
    Draait in aparte thread: doet de conversie en update JOBS-status.
    """
    job = JOBS[job_id]
    job["status"] = "running"
    try:
        mp3_name = extract_audio_to_mp3(video_path, output_folder)
        job["status"] = "done"
        job["mp3_name"] = mp3_name
        job["output_folder"] = output_folder
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


# === HTML template met CyNiT theme ===
INDEX_HTML = """
<!doctype html>
<html lang="nl">
<head>
    <meta charset="utf-8">
    <title>CyNiT Video → MP3 Converter</title>
    <style>
        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background-color: #000000;
            color: #fefefe;
        }
        .page {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }
        .card {
            background: #111111;
            border-radius: 18px;
            padding: 2rem 2.5rem;
            max-width: 650px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
            border: 1px solid #333333;
        }
        .title-row {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1.5rem;
        }
        .badge {
            background: #FEF102;
            color: #000;
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        h1 {
            margin: 0;
            font-size: 1.6rem;
            letter-spacing: 0.03em;
        }
        .subtitle {
            margin-top: 0.25rem;
            color: #cccccc;
            font-size: 0.95rem;
        }
        label {
            font-size: 0.9rem;
            font-weight: 600;
        }
        input[type="text"],
        input[type="file"] {
            margin-top: 0.25rem;
            margin-bottom: 0.75rem;
            width: 100%;
            padding: 0.6rem 0.75rem;
            border-radius: 10px;
            border: 1px solid #333333;
            background: #181818;
            color: #fefefe;
            font-size: 0.9rem;
        }
        input[type="text"]:focus,
        input[type="file"]:focus {
            outline: none;
            border-color: #009844;
            box-shadow: 0 0 0 1px #00984455;
        }
        .hint {
            font-size: 0.8rem;
            color: #999999;
            margin-bottom: 0.75rem;
        }
        .btn-primary {
            background: linear-gradient(135deg, #FEF102, #FFCC00);
            border: none;
            color: #000000;
            padding: 0.7rem 1.25rem;
            border-radius: 999px;
            font-weight: 700;
            cursor: pointer;
            font-size: 0.95rem;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            box-shadow: 0 8px 18px rgba(254, 241, 2, 0.35);
        }
        .btn-primary:hover {
            filter: brightness(1.05);
        }
        .btn-primary:active {
            transform: translateY(1px);
            box-shadow: 0 4px 10px rgba(254, 241, 2, 0.25);
        }
        .icon-dot {
            width: 10px;
            height: 10px;
            border-radius: 999px;
            background: #009844;
            box-shadow: 0 0 12px rgba(0, 152, 68, 0.9);
        }
        .messages {
            margin-bottom: 0.75rem;
        }
        .messages ul {
            list-style: none;
            padding-left: 0;
            margin: 0;
        }
        .messages li {
            font-size: 0.8rem;
            color: #ff7777;
        }
        .status-info {
            margin-top: 1rem;
            font-size: 0.85rem;
            color: #aaaaaa;
        }
        .footer {
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: #777777;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .footer span.cynit {
            color: #FEF102;
            font-weight: 600;
        }

        /* Progress page */
        .progress-wrapper {
            margin-top: 1.5rem;
        }
        .progress-label-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.8rem;
            color: #bbbbbb;
            margin-bottom: 0.35rem;
        }
        .progress-bar-outer {
            width: 100%;
            height: 10px;
            border-radius: 999px;
            background: #222222;
            overflow: hidden;
        }
        .progress-bar-inner {
            width: 10%;
            height: 100%;
            background: linear-gradient(90deg, #009844, #FEF102);
            background-size: 200% 100%;
            animation: progress-move 1.2s linear infinite;
        }
        @keyframes progress-move {
            0% { transform: translateX(-50%); }
            100% { transform: translateX(50%); }
        }
        .status-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.75rem;
            background: #1c1c1c;
            border: 1px solid #333333;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: #FEF102;
        }
        .download-link {
            margin-top: 1.25rem;
        }
        .download-link a {
            color: #FEF102;
            text-decoration: none;
            font-weight: 600;
        }
        .download-link a:hover {
            text-decoration: underline;
        }
        .error-text {
            color: #ff7777;
            font-size: 0.85rem;
            margin-top: 0.75rem;
        }
    </style>
</head>
<body>
    <div class="page">
        <div class="card">
            {% if not job_id %}
                <div class="title-row">
                    <div class="badge">CyNiT Tools</div>
                    <div>
                        <h1>Video → MP3 Converter</h1>
                        <div class="subtitle">Upload een video, kies je output map, en krijg een MP3 terug.</div>
                    </div>
                </div>

                <div class="messages">
                    {% with messages = get_flashed_messages() %}
                      {% if messages %}
                        <ul>
                        {% for message in messages %}
                          <li>{{ message }}</li>
                        {% endfor %}
                        </ul>
                      {% endif %}
                    {% endwith %}
                </div>

                <form method="post" enctype="multipart/form-data" action="{{ url_for('convert') }}">
                    <label for="output_folder">Output map (op deze machine):</label>
                    <input type="text" id="output_folder" name="output_folder"
                           value="{{ default_output }}" placeholder="bv. D:\\Audio\\CyNiTExports">
                    <div class="hint">
                        Dit is een pad op de machine waar deze tool draait. Standaard: {{ default_output }}
                    </div>

                    <label for="file">Videobestand (mp4, mkv, mov, avi, webm, flv):</label>
                    <input type="file" id="file" name="file" required>

                    <button type="submit" class="btn-primary">
                        <span class="icon-dot"></span>
                        <span>Start conversie</span>
                    </button>
                </form>

                <div class="status-info">
                    De conversie gebeurt lokaal met ffmpeg. Afhankelijk van de lengte van de video kan dit even duren.
                </div>

                <div class="footer">
                    <span class="cynit">CyNiT</span>
                    <span>Focus. Automate. Repeat.</span>
                </div>
            {% else %}
                <div class="title-row">
                    <div class="badge">CyNiT Tools</div>
                    <div>
                        <h1>Conversie bezig…</h1>
                        <div class="subtitle">Je MP3 wordt klaargemaakt. Deze pagina ververst automatisch.</div>
                    </div>
                </div>

                <div class="progress-wrapper">
                    <div class="progress-label-row">
                        <span>Status</span>
                        <span id="status-label">Initialiseren…</span>
                    </div>
                    <div class="progress-bar-outer">
                        <div class="progress-bar-inner" id="progress-bar"></div>
                    </div>
                </div>

                <div id="result-block"></div>

                <div class="footer">
                    <span class="cynit">CyNiT</span>
                    <span>Laat dit tabblad open tot de conversie klaar is.</span>
                </div>

                <script>
                    const jobId = "{{ job_id }}";

                    async function pollStatus() {
                        try {
                            const resp = await fetch("{{ url_for('job_status', job_id='__JOBID__') }}".replace("__JOBID__", jobId), {
                                cache: "no-store"
                            });
                            if (!resp.ok) {
                                throw new Error("Status HTTP " + resp.status);
                            }
                            const data = await resp.json();
                            const statusLabel = document.getElementById("status-label");
                            const resultBlock = document.getElementById("result-block");

                            if (data.status === "running" || data.status === "pending") {
                                statusLabel.textContent = data.status === "running" ? "Bezig met conversie…" : "In wachtrij…";
                                setTimeout(pollStatus, 1000);
                            } else if (data.status === "done") {
                                statusLabel.textContent = "Klaar ✔";

                                const bar = document.getElementById("progress-bar");
                                bar.style.animation = "none";
                                bar.style.width = "100%";

                                resultBlock.innerHTML = `
                                    <div class="download-link">
                                        <div class="status-chip">
                                            <div class="status-dot"></div>
                                            <span>MP3 klaar</span>
                                        </div>
                                        <p>Je MP3 is geconverteerd. Klik hieronder om te downloaden:</p>
                                        <p><a href="${data.download_url}">Download MP3</a></p>
                                    </div>
                                `;
                            } else if (data.status === "error") {
                                statusLabel.textContent = "Fout ❌";
                                const bar = document.getElementById("progress-bar");
                                bar.style.animation = "none";
                                bar.style.width = "100%";
                                bar.style.background = "#ff4444";

                                resultBlock.innerHTML = `
                                    <div class="error-text">
                                        Er is een fout opgetreden tijdens de conversie:<br>
                                        <code>${data.error || "Onbekende fout"}</code>
                                    </div>
                                `;
                            } else {
                                statusLabel.textContent = "Onbekende status…";
                                setTimeout(pollStatus, 1500);
                            }

                        } catch (e) {
                            const statusLabel = document.getElementById("status-label");
                            statusLabel.textContent = "Verbindingsfout, opnieuw proberen…";
                            setTimeout(pollStatus, 2000);
                        }
                    }

                    // Start polling
                    pollStatus();
                </script>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


# === Routes ===
@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        INDEX_HTML,
        job_id=None,
        default_output=DEFAULT_OUTPUT_FOLDER,
    )


@app.route("/convert", methods=["POST"])
def convert():
    # Output folder
    output_folder = request.form.get("output_folder", "").strip()
    if not output_folder:
        output_folder = DEFAULT_OUTPUT_FOLDER

    # Relatief → absoluut
    if not os.path.isabs(output_folder):
        output_folder = os.path.join(BASE_DIR, output_folder)

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Geen videobestand geselecteerd.")
        return redirect(url_for("index"))

    filename = pathlib.Path(file.filename).name

    if not allowed_file(filename):
        flash("Bestandstype niet ondersteund. Gebruik mp4, mkv, mov, avi, webm of flv.")
        return redirect(url_for("index"))

    # Opslaan in uploads
    video_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(video_path)

    # Job aanmaken
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "pending",
        "video_path": video_path,
        "output_folder": output_folder,
        "mp3_name": None,
        "error": None,
    }

    # Thread starten
    t = threading.Thread(
        target=run_job,
        args=(job_id, video_path, output_folder),
        daemon=True,
    )
    t.start()

    # Render zelfde template maar in 'progress mode'
    return render_template_string(
        INDEX_HTML,
        job_id=job_id,
        default_output=DEFAULT_OUTPUT_FOLDER,
    )


@app.route("/status/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"status": "unknown", "error": "Job niet gevonden"}), 404

    # Als klaar en download_url nog niet teruggegeven → uitrekenen
    download_url = None
    if job["status"] == "done" and job.get("mp3_name"):
        download_url = url_for(
            "download_file",
            filename=job["mp3_name"],
            folder=job["output_folder"],
        )

    return jsonify(
        {
            "status": job["status"],
            "error": job.get("error"),
            "download_url": download_url,
        }
    )


@app.route("/download/<path:filename>")
def download_file(filename):
    folder = request.args.get("folder", DEFAULT_OUTPUT_FOLDER)

    if not os.path.isabs(folder):
        folder = os.path.join(BASE_DIR, folder)

    return send_from_directory(folder, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
