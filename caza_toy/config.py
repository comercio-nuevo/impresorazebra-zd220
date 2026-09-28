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
IMPRIMIR = Path.home() / "Documents" / "imprimir"
INBOX = APP_DIR / "inbox"
SPOOL = APP_DIR / "spool"
PRINTED = APP_DIR / "printed"
FAILED = APP_DIR / "failed"
CONFIG_PATH = APP_DIR / "config.json"
LAST_ZPL = APP_DIR / "last.zpl"
ICON_PATH = APP_DIR / "menubar.png"
LOGOS_DIR = APP_DIR / "logos"
LOG_PATH = Path.home() / "Library/Logs/CazaToy.log"
CACHE_DIRS = (INBOX, SPOOL, PRINTED, FAILED)

DEFAULT_STORES = (
    {"name": "Mercado Libre", "x": 16, "y": 16, "width": 280},
    {"name": "TikTok Shop", "x": 516, "y": 16, "width": 280},
    {"name": "Shopify", "x": 16, "y": 1000, "width": 280},
    {"name": "Envíos Perros", "x": 516, "y": 1000, "width": 280},
)

DEFAULTS = {
    "logo_text": "caza toy",
    "printer": "Zebra_ZD220",
    "ipp_port": 8631,
    "raw_port": 9100,
    "matrix": False,
    "active_store": "Mercado Libre",
    "stores": [dict(store) for store in DEFAULT_STORES],
}


def ensure_dirs() -> None:
    for path in (APP_DIR, LOGOS_DIR, DOWNLOADS, IMPRIMIR, LOG_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)


def logo_file(name: str, slot: int = 1) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name).strip("._")[:40] or "logo"
    filename = f"{safe}.png" if int(slot) == 1 else f"{safe}-{int(slot)}.png"
    path = (LOGOS_DIR / filename).resolve()
    if path.parent != LOGOS_DIR.resolve():
        raise ValueError("nombre de tienda no válido")
    return path


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
            if key == "stores":
                data[key] = [dict(store) for store in value]
            else:
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


def clamp_store(item: dict) -> dict | None:
    name = " ".join(str(item.get("name", "")).split())[:40]
    if not name:
        return None
    try:
        x = int(item.get("x", 0))
        y = int(item.get("y", 0))
        width = int(item.get("width", 280))
    except (TypeError, ValueError):
        return None
    first = _clamp_image(item if not item.get("images") else item["images"][0], 1, x, y, width)
    second_raw = item["images"][1] if isinstance(item.get("images"), list) and len(item["images"]) > 1 else {
        "x": min(x + width + 24, LABEL_W - 80),
        "y": y,
        "width": min(width, 220),
        "ascii": False,
    }
    second = _clamp_image(second_raw, 2, second_raw.get("x", 420), second_raw.get("y", y), second_raw.get("width", 200))
    return {
        "name": name,
        "x": first["x"],
        "y": first["y"],
        "width": first["width"],
        "ascii": first["ascii"],
        "images": [first, second],
    }


def _clamp_image(item: dict, slot: int, x: int, y: int, width: int) -> dict:
    try:
        x = int(item.get("x", x))
        y = int(item.get("y", y))
        width = int(item.get("width", width))
    except (TypeError, ValueError):
        pass
    return {
        "slot": slot,
        "x": min(max(0, x), LABEL_W - 1),
        "y": min(max(0, y), LABEL_H - 1),
        "width": min(max(40, width), 760),
        "ascii": bool(item.get("ascii")),
        "present": item.get("present", True) is not False,
    }


def apply_stores(data: dict, stores: list, active: str) -> dict:
    clean = []
    seen = set()
    for item in stores:
        store = clamp_store(item)
        if store is None or store["name"] in seen:
            continue
        seen.add(store["name"])
        clean.append(store)
    if not clean:
        clean = [dict(store) for store in DEFAULT_STORES]
    if active not in seen:
        active = clean[0]["name"]
    data["stores"] = clean
    data["active_store"] = active
    return data


def active_placement(data: dict | None = None) -> dict | None:
    data = data or load_config()
    stores = data.get("stores") or []
    name = data.get("active_store")
    for store in stores:
        if store.get("name") == name:
            return store
    return stores[0] if stores else None
