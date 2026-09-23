"""Rutas y medidas fijas de la etiqueta 4×6 a 203 dpi."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

DPI = 203
LABEL_W = 4 * DPI  # 812 puntos
LABEL_H = 6 * DPI  # 1218 puntos

APP_DIR = Path.home() / "Library/Application Support/CazaToy"
DOWNLOADS = Path.home() / "Downloads"
INBOX = APP_DIR / "inbox"
SPOOL = APP_DIR / "spool"
PRINTED = APP_DIR / "printed"
FAILED = APP_DIR / "failed"
CONFIG_PATH = APP_DIR / "config.json"
LAST_ZPL = APP_DIR / "last.zpl"
ICON_PATH = APP_DIR / "menubar.png"
LOG_PATH = Path.home() / "Library/Logs/CazaToy.log"
CACHE_DIRS = (INBOX, SPOOL, PRINTED, FAILED)

DEFAULTS = {
    "logo_text": "caza toy",
    "printer": "Zebra_ZD220",
    "ipp_port": 8631,
    "raw_port": 9100,
    "matrix": False,
}


def ensure_dirs() -> None:
    for path in (APP_DIR, DOWNLOADS, LOG_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)


def wipe_cache() -> None:
    """Borra copias viejas. Las etiquetas solo viven en Descargas hasta imprimirse."""
    for folder in CACHE_DIRS:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    if LAST_ZPL.exists():
        LAST_ZPL.unlink()


def load_config() -> dict:
    ensure_dirs()
    data: dict = {}
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    changed = False
    for key, value in DEFAULTS.items():
        if key not in data:
            data[key] = value
            changed = True
    if not data.get("uuid"):
        data["uuid"] = str(uuid.uuid4())
        changed = True
    if changed or not CONFIG_PATH.exists():
        save_config(data)
    return data


def save_config(data: dict) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
