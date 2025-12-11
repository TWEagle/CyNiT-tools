#!/usr/bin/env python3
"""
convert_to_ico.py

CyNiT Image → ICO Converter

- GUI-tool (Tkinter) met filepicker
- Web-UI via /ico, integreert met CyNiT layout & thema
"""

from __future__ import annotations

from pathlib import Path
from io import BytesIO
from typing import Optional, List, Dict, Any

import tkinter as tk
from tkinter import filedialog, messagebox

from flask import Flask, Blueprint, render_template_string, request, send_file, make_response

from PIL import Image

import cynit_theme
import cynit_layout


BASE_DIR = cynit_theme.BASE_DIR
LOGO_PATH = cynit_theme.LOGO_PATH


# =====================================
#  GUI
# =====================================

class IcoConverterGUI(tk.Tk):
    def __init__(self, settings: Dict[str, Any]):
        super().__init__()

        self.settings = settings
        colors = settings.get("colors", {})
        ui = settings.get("ui", {})

        self.bg = colors.get("background", "#000000")
        self.fg = colors.get("general_fg", "#00FA00")
        self.title_color = colors.get("title", "#00A2FF")

        self.font_main = ui.get("font_main", "Consolas")
        self.font_buttons = ui.get("font_buttons", "Segoe UI")

        self.image_path: Optional[Path] = None

        self.title("CyNiT Image → ICO Converter")
        self.geometry("580x220")
        self.configure(bg=self.bg)

        self._logo_img = None

        self._build_gui()

    def _build_gui(self) -> None:
        # Header met logo (zoals cert_viewer GUI doet)
        header = tk.Frame(self, bg=self.bg)
        header.pack(fill=tk.X, padx=10, pady=(10, 0))

        left = tk.Frame(header, bg=self.bg)
        left.pack(side=tk.LEFT, anchor="w")

        if LOGO_PATH.exists():
            try:
                from PIL import ImageTk
                img = Image.open(LOGO_PATH)
                max_h = self.settings.get("ui", {}).get("logo_max_height", 80)
                if img.height > 0:
                    scale = max_h / img.height
                else:
                    scale = 1.0
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(img_resized)
                logo_label = tk.Label(left, image=self._logo_img, bg=self.bg)
                logo_label.pack(side=tk.LEFT)
            except Exception:
                pass

        title_lbl = tk.Label(
            header,
            text="Image → ICO Converter",
            bg=self.bg,
            fg=self.title_color,
            font=(self.font_main, 16, "bold"),
        )
        title_lbl.pack(side=tk.LEFT, padx=10)

        frame = tk.Frame(self, bg=self.bg)
        frame.pack(padx=20, pady=10, fill=tk.BOTH, expand=True)

        btn_select = tk.Button(
            frame,
            text="📁 Afbeelding kiezen…",
            command=self.choose_image,
            bg=self.settings["colors"].get("button_bg", "#111111"),
            fg=self.settings["colors"].get("button_fg", "#00B7C3"),
            activebackground=self.settings["colors"].get("button_bg", "#111111"),
            activeforeground=self.settings["colors"].get("button_fg", "#00B7C3"),
            font=(self.font_buttons, 11, "bold"),
            relief=tk.RAISED,
            bd=3,
        )
        btn_select.pack(pady=5, anchor="w")

        self.lbl_file = tk.Label(
            frame,
            text="Geen afbeelding geselecteerd",
            bg=self.bg,
            fg=self.fg,
            font=(self.font_main, 10),
            anchor="w",
            justify="left",
        )
        self.lbl_file.pack(pady=5, fill=tk.X)

        btn_convert = tk.Button(
            frame,
            text="➡ Converteer naar ICO",
            command=self.convert,
            bg=self.settings["colors"].get("button_bg", "#111111"),
            fg=self.settings["colors"].get("button_fg", "#00B7C3"),
            activebackground=self.settings["colors"].get("button_bg", "#111111"),
            activeforeground=self.settings["colors"].get("button_fg", "#00B7C3"),
            font=(self.font_buttons, 11, "bold"),
            relief=tk.RAISED,
            bd=3,
        )
        btn_convert.pack(pady=(10, 5), anchor="w")

        hint = tk.Label(
            frame,
            text="Ondersteund: PNG, JPG, JPEG, GIF → ico (16–256 px).",
            bg=self.bg,
            fg=self.fg,
            font=(self.font_main, 9),
            anchor="w",
            justify="left",
        )
        hint.pack(pady=(5, 0), fill=tk.X)

    def choose_image(self) -> None:
        filetypes = [
            ("Afbeeldingen", "*.png *.jpg *.jpeg *.gif"),
            ("PNG", "*.png"),
            ("JPEG", "*.jpg *.jpeg"),
            ("GIF", "*.gif"),
            ("Alle bestanden", "*.*"),
        ]

        filename = filedialog.askopenfilename(
            title="Kies een afbeelding",
            filetypes=filetypes,
        )

        if filename:
            self.image_path = Path(filename)
            self.lbl_file.config(text=str(self.image_path))

    def convert(self) -> None:
        if not self.image_path:
            messagebox.showwarning("Geen afbeelding", "Kies eerst een afbeelding.")
            return

        try:
            img = Image.open(self.image_path)
        except Exception as e:
            messagebox.showerror("Fout", f"Fout bij openen afbeelding:\n{e}")
            return

        save_path = filedialog.asksaveasfilename(
            title="Opslaan als ICO",
            defaultextension=".ico",
            filetypes=[("ICO file", "*.ico")],
            initialfile=self.image_path.stem + ".ico",
        )

        if not save_path:
            return

        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

        try:
            img.save(save_path, format="ICO", sizes=sizes)
            messagebox.showinfo("Succes", f"ICO opgeslagen als:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon ICO niet opslaan:\n{e}")


def run_gui() -> None:
    settings = cynit_theme.load_settings()
    gui = IcoConverterGUI(settings)
    gui.mainloop()


# =====================================
#  WEB
# =====================================

bp = Blueprint("icoconverter", __name__)


@bp.route("/ico", methods=["GET", "POST"])
def ico_index():
    settings = cynit_theme.load_settings()
    colors = settings.get("colors", {})
    ui = settings.get("ui", {})

    base_css = cynit_layout.common_css(settings)
    common_js = cynit_layout.common_js()

    tools_cfg = cynit_theme.load_tools()
    tools = tools_cfg.get("tools", [])

    header_html = cynit_layout.header_html(
        settings,
        tools=tools,
        title="CyNiT Image → ICO Converter",
        right_html="",
    )
    footer_html = cynit_layout.footer_html()

    error: Optional[str] = None
    info: Optional[str] = None

    ico_bytes: Optional[bytes] = None
    ico_name: Optional[str] = None

    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            error = "Geen bestand geselecteerd."
        else:
            try:
                data = file.read()
                img = Image.open(BytesIO(data))
                out = BytesIO()

                sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
                img.save(out, format="ICO", sizes=sizes)
                out.seek(0)
                ico_bytes = out.read()
                ico_name = Path(file.filename).stem + ".ico"
                info = f"Afbeelding succesvol geconverteerd naar {ico_name}."
            except Exception as e:
                error = f"Fout bij converteren: {e}"

    template = f"""
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>CyNiT Image → ICO Converter</title>
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <style>
    {base_css}

    .card {{
      max-width: 700px;
      margin: 0 auto 20px auto;
      background: #1e1e1e;
      padding: 20px;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
    }}
    .muted {{ color:#aaa; font-size:0.9em; }}
    .flash-error {{
      background:#331111;
      border:1px solid #aa3333;
      color:#ffaaaa;
      padding:8px 12px;
      border-radius:8px;
      margin-bottom:10px;
    }}
    .flash-ok {{
      background:#112211;
      border:1px solid #22aa33;
      color:#aaffaa;
      padding:8px 12px;
      border-radius:8px;
      margin-bottom:10px;
    }}
  </style>
  <script>
    {common_js}
  </script>
</head>
<body>
  {header_html}
  <div class="page">
    <div class="card">
      <h1>Image → ICO Converter</h1>
      <p class="muted">
        Upload een afbeelding (PNG, JPG, JPEG, GIF) en download een .ico in meerdere formaten (16–256px).
      </p>

      {{% if error %}}
        <div class="flash-error">{{{{ error }}}}</div>
      {{% endif %}}

      {{% if info %}}
        <div class="flash-ok">{{{{ info }}}}</div>
      {{% endif %}}

      <form method="post" enctype="multipart/form-data">
        <label>Afbeelding uploaden:</label><br>
        <input type="file" name="file" accept=".png,.jpg,.jpeg,.gif" /><br><br>
        <button type="submit">Converteer naar ICO</button>
      </form>

      {{% if ico_available %}}
        <hr>
        <p>Download je ICO bestand:</p>
        <a href="{{{{ download_url }}}}">⬇ {{{{ ico_name }}}}</a>
      {{% endif %}}
    </div>
  </div>
  {footer_html}
</body>
</html>
"""

    download_url = ""
    ico_available = False

    if ico_bytes and ico_name:
        # We sturen het bestand direct terug als download-response
        # (geen aparte route; de POST-response is de download)
        buf = BytesIO(ico_bytes)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name=ico_name,
            mimetype="image/x-icon",
        )

    # Geen bestand (GET of fout) → gewone pagina tonen
    return render_template_string(
        template,
        error=error,
        info=info,
        ico_available=ico_available,
        download_url=download_url,
        ico_name=ico_name or "",
        tools=tools,
    )


def register_web_routes(app: Flask, settings: Dict[str, Any], tools: Optional[List[Dict[str, Any]]] = None) -> None:
    """
    Registert /ico in een bestaande Flask app (ctools).
    """
    app.register_blueprint(bp)


# =====================================
#  Standalone run
# =====================================

def run_web() -> None:
    settings = cynit_theme.load_settings()
    tools_cfg = cynit_theme.load_tools()
    tools = tools_cfg.get("tools", [])

    app = Flask(__name__)
    register_web_routes(app, settings, tools)
    app.run(host="127.0.0.1", port=5450, debug=True)


if __name__ == "__main__":
    import sys
    if "--gui" in sys.argv:
        run_gui()
    else:
        run_web()
