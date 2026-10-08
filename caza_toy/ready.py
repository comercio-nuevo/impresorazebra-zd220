"""Etiquetas listas de advertencia. Fondo negro, letras blancas."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from .config import LABEL_H, LABEL_W
from .logo import load_font
from .pipeline import image_to_zpl

ORDER = (
    ("cuidado", "Manéjese con cuidado"),
    ("arriba", "Este lado arriba"),
    ("apilar", "No apilar"),
    ("seco", "Mantener seco"),
    ("doblar", "No doblar"),
    ("liquido", "Contiene líquido"),
    ("navaja", "No usar navaja"),
    ("vidrio", "Vidrio"),
    ("voltear", "No voltear"),
    ("pesado", "Pesado"),
)
READY = dict(ORDER)


def catalog() -> list[dict]:
    return [{"id": key, "name": label} for key, label in ORDER]


def ready_image(name: str) -> Image.Image:
    if name not in READY:
        raise ValueError("etiqueta desconocida")
    if name == "cuidado":
        return _cuidado()
    image = Image.new("L", (LABEL_W, LABEL_H), 0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, LABEL_W - 17, LABEL_H - 17), outline=255, width=10)
    _ICONS[name](draw)
    _fit(draw, READY[name].upper(), 760, 1120, LABEL_W - 48)
    return image


def ready_png(name: str) -> bytes:
    buffer = io.BytesIO()
    ready_image(name).save(buffer, "PNG")
    return buffer.getvalue()


def ready_zpl(name: str) -> str:
    return image_to_zpl(ready_image(name))


def _cuidado() -> Image.Image:
    image = Image.new("L", (LABEL_W, LABEL_H), 0)
    draw = ImageDraw.Draw(image)
    top = 430
    bottom = 980
    draw.rectangle((0, top, LABEL_W, bottom), fill=255)
    draw.rectangle((0, top - 18, LABEL_W, top - 6), fill=255)
    draw.rectangle((0, bottom + 6, LABEL_W, bottom + 18), fill=255)
    _fit(draw, "POR FAVOR", 16, 230, LABEL_W - 40)
    _fit(draw, "MANÉJESE CON CUIDADO", 236, 412, LABEL_W - 8, width_only=True)
    _fit(draw, "FRÁGIL", 500, 900, LABEL_W - 36, fill=0)
    _fit(draw, "**GRACIAS**", 1020, 1160, LABEL_W - 80)
    return image


def _fit(draw: ImageDraw.ImageDraw, text: str, top: int, bottom: int, max_width: int, fill: int = 255, width_only: bool = False) -> None:
    size = 280
    font = load_font(size)
    limit_h = bottom - top
    while size > 20:
        box = draw.textbbox((0, 0), text, font=font)
        wide = box[2] - box[0] <= max_width
        tall = box[3] - box[1] <= limit_h
        if wide and (width_only or tall):
            break
        size -= 2
        font = load_font(size)
    box = draw.textbbox((0, 0), text, font=font)
    x = (LABEL_W - (box[2] - box[0])) // 2 - box[0]
    y = top + (limit_h - (box[3] - box[1])) // 2 - box[1]
    draw.text((x, y), text, fill=fill, font=font)


def _arrow(draw: ImageDraw.ImageDraw, cx: int) -> None:
    draw.polygon([(cx, 120), (cx - 78, 280), (cx - 30, 280), (cx - 30, 560), (cx + 30, 560), (cx + 30, 280), (cx + 78, 280)], fill=255)


def _arriba(draw: ImageDraw.ImageDraw) -> None:
    _arrow(draw, LABEL_W // 2 - 130)
    _arrow(draw, LABEL_W // 2 + 130)


def _apilar(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((230, 180, 560, 340), outline=255, width=14)
    draw.rectangle((270, 380, 600, 540), outline=255, width=14)
    draw.line((190, 600, 640, 140), fill=255, width=22)


def _seco(draw: ImageDraw.ImageDraw) -> None:
    cx, top = LABEL_W // 2, 130
    draw.arc((cx - 200, top, cx + 200, top + 300), 180, 360, fill=255, width=18)
    draw.line((cx - 200, top + 150, cx + 200, top + 150), fill=255, width=16)
    draw.line((cx, top + 150, cx, top + 430), fill=255, width=16)
    draw.arc((cx - 90, top + 390, cx + 10, top + 490), 0, 180, fill=255, width=14)
    for drop in (cx - 120, cx, cx + 120):
        draw.line((drop, top + 190, drop, top + 250), fill=255, width=8)


def _doblar(draw: ImageDraw.ImageDraw) -> None:
    draw.polygon([(220, 160), (520, 160), (620, 260), (620, 560), (220, 560)], outline=255)
    draw.line([(520, 160), (520, 260), (620, 260)], fill=255, width=12)
    draw.line((180, 600, 660, 140), fill=255, width=22)


def _liquido(draw: ImageDraw.ImageDraw) -> None:
    cx, top = LABEL_W // 2, 140
    draw.polygon([(cx, top), (cx - 150, top + 280), (cx - 80, top + 430), (cx + 80, top + 430), (cx + 150, top + 280)], outline=255)
    draw.line([(cx - 150, top + 280), (cx + 150, top + 280)], fill=255, width=12)


def _navaja(draw: ImageDraw.ImageDraw) -> None:
    draw.polygon([(210, 500), (530, 200), (590, 250), (270, 550)], outline=255)
    draw.rectangle((170, 500, 280, 560), outline=255, width=14)
    draw.ellipse((230, 180, 590, 540), outline=255, width=18)
    draw.line((250, 200, 570, 520), fill=255, width=18)


def _vidrio(draw: ImageDraw.ImageDraw) -> None:
    cx, top = LABEL_W // 2, 140
    draw.arc((cx - 150, top, cx + 150, top + 240), 200, 340, fill=255, width=16)
    draw.arc((cx - 150, top, cx + 150, top + 240), 20, 160, fill=255, width=16)
    draw.line((cx - 36, top + 36, cx + 24, top + 100, cx - 20, top + 160, cx + 40, top + 210), fill=255, width=10)
    draw.line((cx, top + 220, cx, top + 400), fill=255, width=16)
    draw.line((cx - 110, top + 410, cx + 110, top + 410), fill=255, width=16)


def _voltear(draw: ImageDraw.ImageDraw) -> None:
    cx, top = LABEL_W // 2, 180
    draw.arc((cx - 180, top, cx + 180, top + 360), 30, 300, fill=255, width=18)
    draw.polygon([(cx + 150, top + 40), (cx + 230, top + 20), (cx + 170, top + 120)], fill=255)
    draw.line((cx - 220, top + 80, cx + 220, top + 460), fill=255, width=22)


def _pesado(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((196, 220, 616, 520), outline=255, width=16)
    _fit(draw, "KG", 250, 500, 360)


_ICONS = {
    "arriba": _arriba,
    "apilar": _apilar,
    "seco": _seco,
    "doblar": _doblar,
    "liquido": _liquido,
    "navaja": _navaja,
    "vidrio": _vidrio,
    "voltear": _voltear,
    "pesado": _pesado,
}
