#!/usr/bin/env python3
"""
cynit_notify.py

Eenvoudige notificatie-helper voor CyNiT Tools.
Momenteel:
- Signal-berichten versturen via signal-cli (alleen 'send', geen ontvangst).

Config:
- config/notify.json

Voorbeeld gebruik:

    from cynit_notify import send_signal_message

    send_signal_message("Testje vanuit CyNiT Tools")
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
NOTIFY_CFG_PATH = CONFIG_DIR / "notify.json"


# ==============================
# Config laden / initialiseren
# ==============================

def _default_notify_config() -> Dict[str, Any]:
    return {
        "signal": {
            "enabled": False,
            "binary": "signal-cli",
            "sender": "",
            "default_recipients": [],
            "timeout_sec": 15
        }
    }


def load_notify_config() -> Dict[str, Any]:
    """
    Leest config/notify.json.
    - Bestaat hij niet -> aanmaken met defaults (enabled = false).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not NOTIFY_CFG_PATH.exists():
        data = _default_notify_config()
        NOTIFY_CFG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return data

    try:
        raw = json.loads(NOTIFY_CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = _default_notify_config()
        NOTIFY_CFG_PATH.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # heel simpele merge, zodat nieuwe keys niet kapot gaan
    dflt = _default_notify_config()
    dflt.update(raw)
    if "signal" in raw and isinstance(raw["signal"], dict):
        sig = dict(dflt["signal"])
        sig.update(raw["signal"])
        dflt["signal"] = sig

    return dflt


_NOTIFY_CFG: Dict[str, Any] = load_notify_config()


def reload_notify_config() -> None:
    """
    Optioneel: callen als je notify.json via de config-editor aanpast.
    """
    global _NOTIFY_CFG
    _NOTIFY_CFG = load_notify_config()


# ==============================
# Signal helpers
# ==============================

class SignalError(RuntimeError):
    pass


def _get_signal_cfg() -> Dict[str, Any]:
    sig = _NOTIFY_CFG.get("signal") or {}
    if not isinstance(sig, dict):
        raise SignalError("Ongeldige 'signal' sectie in notify.json")
    return sig


def send_signal_message(
    message: str,
    recipients: Optional[Iterable[str]] = None,
) -> None:
    """
    Verstuur een Signal-bericht via signal-cli.

    - message: tekst van het bericht
    - recipients: iterable van telefoonnummers (inclusief landcode),
                  laat leeg om default_recipients uit config te gebruiken.

    Raises:
        SignalError bij misconfiguratie of falende signal-cli.
    """
    sig = _get_signal_cfg()

    if not sig.get("enabled", False):
        raise SignalError("Signal-notificaties zijn uitgeschakeld in notify.json.")

    sender = (sig.get("sender") or "").strip()
    if not sender:
        raise SignalError("Geen 'sender' ingesteld in notify.json (signal.sender).")

    default_recipients = sig.get("default_recipients") or []
    if recipients is None:
        recips: List[str] = list(default_recipients)
    else:
        recips = [r.strip() for r in recipients if str(r).strip()]

    if not recips:
        raise SignalError("Geen ontvangers opgegeven en geen default_recipients in notify.json.")

    binary = (sig.get("binary") or "signal-cli").strip()
    timeout_sec = int(sig.get("timeout_sec", 15))

    if not shutil.which(binary):
        raise SignalError(
            f"signal-cli binary '{binary}' niet gevonden in PATH. "
            "Controleer notify.json of installeer signal-cli."
        )

    cmd = [binary, "-u", sender, "send", "-m", message]
    cmd.extend(recips)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise SignalError(f"signal-cli timeout na {timeout_sec}s: {exc}") from exc
    except Exception as exc:
        raise SignalError(f"Kon signal-cli niet uitvoeren: {exc}") from exc

    if result.returncode != 0:
        raise SignalError(
            "signal-cli faalde "
            f"(exit {result.returncode}).\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
