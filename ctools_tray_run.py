
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
from win10toast import ToastNotifier
from datetime import datetime


# === Instellingen ===
PROJECT_DIR = Path(r"C:\gh\CyNiT-tools\CyNiT-tools")
VENV_DIR = PROJECT_DIR / "venv"
PYTHONW = VENV_DIR / "Scripts" / "pythonw.exe"
SCRIPT = PROJECT_DIR / "ctools.py"
ICON_OK_PATH = PROJECT_DIR / "images" / "logo.png"
ICON_ERR_PATH = PROJECT_DIR / "images" / "logo_crash.png"
LOG_PATH = PROJECT_DIR / "ctools_watcher.log"

toaster = ToastNotifier()

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def make_red_icon(src_path, dest_path):
    """Maak een rode variant van het logo voor crash-status."""
    img = Image.open(src_path).convert("RGBA")
    r, g, b, a = img.split()
    # Maak alles rood, behoud alpha
    red_img = Image.new("RGBA", img.size, (255, 60, 60, 255))
    red_img.putalpha(a)
    red_img.save(dest_path)

if not ICON_ERR_PATH.exists():
    make_red_icon(ICON_OK_PATH, ICON_ERR_PATH)

def run_ctools(icon):
    """Start ctools.py in de achtergrond met pythonw.exe, bewaak crash."""
    while True:
        log("Start ctools.py")
        proc = subprocess.Popen([str(PYTHONW), str(SCRIPT)], cwd=str(PROJECT_DIR))
        icon.icon = Image.open(ICON_OK_PATH)
        icon.title = "CyNiT Tools draait"
        icon.visible = True
        proc.wait()
        # Bij crash: wissel icoon, notificatie, log
        log("ctools.py is gecrasht! Herstart over 3s.")
        icon.icon = Image.open(ICON_ERR_PATH)
        icon.title = "CyNiT Tools is gecrasht! Herstart over 3s."
        toaster.show_toast("CyNiT Tools", "ctools.py is gecrasht en wordt herstart!", duration=6, threaded=True)
        time.sleep(3)  # Backoff voor herstart

def on_quit(icon, item):
    log("Watcher afgesloten via menu")
    icon.stop()
    os._exit(0)

def on_restart(icon, item):
    log("Handmatige herstart via menu")
    os.system("taskkill /f /im pythonw.exe")
    time.sleep(1)
    Thread(target=run_ctools, args=(icon,), daemon=True).start()
    icon.icon = Image.open(ICON_OK_PATH)
    icon.title = "CyNiT Tools wordt herstart..."
    toaster.show_toast("CyNiT Tools", "ctools.py wordt herstart!", duration=4, threaded=True)

def main():
    # Tray-icoon
    image_ok = Image.open(ICON_OK_PATH)
    menu = Menu(
        MenuItem("Herstart CyNiT", on_restart),
        MenuItem("Afsluiten", on_quit)
    )
    icon = Icon("CyNiT Tools", image_ok, "CyNiT Tools draait", menu)
    # Start watcher in aparte thread
    Thread(target=run_ctools, args=(icon,), daemon=True).start()
    icon.run()

print("Script start")
log("Testlog")

if __name__ == "__main__":
    main()
