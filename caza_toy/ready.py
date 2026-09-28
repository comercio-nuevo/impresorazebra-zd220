"""Etiquetas listas para imprimir, sin el logo de la tienda."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from .config import LABEL_H, LABEL_W
from .logo import load_font
from .pipeline import image_to_zpl

READY = {
    "cuidado": "Manéjese con cuidado",
}


def ready_image(name: str) -> Image.Image:
    if name not in READY:
        raise ValueError("etiqueta desconocida")
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


def ready_png(name: str) -> bytes:
    buffer = io.BytesIO()
    ready_image(name).save(buffer, "PNG")
    return buffer.getvalue()


def ready_zpl(name: str) -> str:
    return image_to_zpl(ready_image(name))


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
