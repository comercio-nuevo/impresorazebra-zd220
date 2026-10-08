"""Convierte PDF, ZPL, TXT, JPG, PNG y CSV a una etiqueta de 4×6 pulgadas."""

from __future__ import annotations

import csv
import io
import re
import subprocess
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageOps

from .config import LABEL_H, LABEL_W
from .logo import load_font, render_zpl_pages, stamp_bitmap, stamp_zpl

CELL_W = 16
CELL_H = 24

TEST_ZPL = """^XA
^PW812
^LL1218
^FO40,40^A0N,42,42^FDCazaToy prueba^FS
^FO40,100^A0N,28,28^FDEtiqueta 4x6^FS
^FO40,180^BY3^BCN,120,Y,N,N^FDTEST123^FS
^XZ
"""


class Prepared:
    def __init__(self, zpl: str, stamped: bool, kind: str, pages: int) -> None:
        self.zpl = zpl
        self.stamped = stamped
        self.kind = kind
        self.pages = pages


def sniff(data: bytes, name: str = "") -> str:
    stripped = data.lstrip(b"\xef\xbb\xbf \t\r\n\x00")
    if stripped.startswith(b"%PDF"):
        return "pdf"
    if stripped.startswith(b"\x89PNG") or stripped.startswith(b"\xff\xd8\xff"):
        return "image"
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        return "csv"
    head = stripped[:8000].decode("latin-1", errors="ignore")
    if "^XA" in head:
        return "zpl"
    if suffix in {".jpg", ".jpeg", ".png"}:
        return "image"
    if suffix == ".txt":
        return "text"
    return "unknown"


def prepare(
    data: bytes,
    logo_text: str,
    name: str = "",
    matrix: bool = False,
    placement: dict | None = None,
) -> Prepared:
    if not data or not data.strip(b"\x00 \t\r\n"):
        raise ValueError("El archivo está vacío")
    kind = sniff(data, name)
    if kind == "pdf":
        return _from_images(render_label_pages(data), logo_text, "pdf", matrix, placement)
    if kind == "image":
        return _from_images([render_picture(data)], logo_text, "image", matrix, placement)
    if kind == "text":
        text = data.decode("utf-8-sig", errors="replace").strip("\ufeff")
        return _from_images([render_text(text)], logo_text, "text", matrix, placement)
    if kind == "csv":
        return _from_csv(data, logo_text, matrix, placement)
    if kind == "zpl":
        zpl_text = data.decode("latin-1", errors="replace")
        if matrix:
            return _from_images(render_zpl_pages(zpl_text), logo_text, "zpl", True, placement)
        zpl, stamped = stamp_zpl(zpl_text, logo_text, placement)
        if not zpl.endswith("\n"):
            zpl += "\n"
        return Prepared(zpl, stamped, "zpl", max(zpl.count("^XA"), 1))
    raise ValueError("No es una etiqueta PDF, ZPL, TXT, JPG, PNG o CSV")


def digit_matrix(image: Image.Image) -> Image.Image:
    """Sustituye la tinta por dígitos. El blanco se queda en blanco."""
    image = threshold_l(image)
    width, height = image.size
    pixels = image.tobytes()
    canvas = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(canvas)
    font = load_font(14)
    total = CELL_W * CELL_H
    for top in range(0, height - CELL_H + 1, CELL_H):
        for left in range(0, width - CELL_W + 1, CELL_W):
            black = 0
            for y in range(top, top + CELL_H):
                row = y * width
                for x in range(left, left + CELL_W):
                    if pixels[row + x] < 128:
                        black += 1
            if black * 20 < total * 3:
                continue
            level = min(9, black * 10 // total)
            glyph = "0123456789"[level]
            bbox = draw.textbbox((0, 0), glyph, font=font)
            glyph_w = bbox[2] - bbox[0]
            glyph_h = bbox[3] - bbox[1]
            draw.text(
                (left + (CELL_W - glyph_w) / 2 - bbox[0], top + (CELL_H - glyph_h) / 2 - bbox[1]),
                glyph,
                fill=0,
                font=font,
            )
    return canvas


def threshold_l(image: Image.Image, level: int = 200) -> Image.Image:
    lut = [0 if value < level else 255 for value in range(256)]
    return image.convert("L").point(lut)


def _from_images(
    images: list[Image.Image],
    logo_text: str,
    kind: str,
    matrix: bool = False,
    placement: dict | None = None,
) -> Prepared:
    stamped = False
    parts: list[str] = []
    for image in images:
        image, placed = stamp_bitmap(image, logo_text, placement)
        stamped = stamped or placed
        if matrix:
            image = digit_matrix(image)
        parts.append(image_to_zpl(image))
    if not parts:
        raise ValueError("El archivo no tiene páginas")
    return Prepared("\n".join(parts) + "\n", stamped, kind, len(parts))


def render_picture(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image) or image
    except Exception as exc:
        raise ValueError(f"No se pudo leer la imagen: {exc}") from exc
    if image.mode in ("RGBA", "LA"):
        background = Image.new("L", image.size, 255)
        background.paste(image.convert("L"), mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("L")
    if image.width > image.height:
        image = image.transpose(Image.Transpose.ROTATE_90)
    return _place(image)


def render_text(text: str) -> Image.Image:
    body = text.strip()
    if not body:
        raise ValueError("El texto está vacío")
    canvas = Image.new("L", (LABEL_W, LABEL_H), 255)
    draw = ImageDraw.Draw(canvas)
    font = load_font(28)
    margin = 24
    line_height = 36
    y = margin
    for line in _wrap(body, font, LABEL_W - margin * 2):
        if y > LABEL_H - margin - line_height:
            break
        draw.text((margin, y), line, fill=0, font=font)
        y += line_height
    return canvas


def _wrap(text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for word in paragraph.split(" "):
            trial = word if not current else f"{current} {word}"
            if _text_width(font, trial) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
            current = word
        lines.append(current)
    return [line for line in lines if line]


def _text_width(font, text: str) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(text))
    return float(len(text) * 14)


def _from_csv(data: bytes, logo_text: str, matrix: bool = False, placement: dict | None = None) -> Prepared:
    table = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(table)))
    zpl_parts: list[str] = []
    images: list[Image.Image] = []
    stamped = False
    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        if not cells:
            continue
        zpl_cells = [cell for cell in cells if "^XA" in cell]
        if zpl_cells:
            if matrix:
                for cell in zpl_cells:
                    images.extend(render_zpl_pages(cell))
            else:
                for cell in zpl_cells:
                    zpl, placed = stamp_zpl(cell if cell.endswith("\n") else cell + "\n", logo_text, placement)
                    stamped = stamped or placed
                    zpl_parts.append(zpl if zpl.endswith("\n") else zpl + "\n")
            continue
        images.append(render_text("\n".join(cells)))
    image_job = _from_images(images, logo_text, "csv", matrix, placement) if images else None
    parts = list(zpl_parts)
    pages = len(zpl_parts)
    if image_job is not None:
        parts.append(image_job.zpl)
        pages += image_job.pages
        stamped = stamped or image_job.stamped
    if not parts:
        raise ValueError("El CSV no tiene filas")
    return Prepared("".join(parts), stamped, "csv", pages)


def render_label_pages(data: bytes) -> list[Image.Image]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"No se pudo leer el PDF: {exc}") from exc
    try:
        if document.needs_pass:
            raise ValueError("El PDF está protegido con contraseña")
        if document.page_count == 0:
            raise ValueError("El PDF no tiene páginas")
        return [_render_page(document[index]) for index in range(document.page_count)]
    finally:
        document.close()


def _render_page(page: pymupdf.Page) -> Image.Image:
    if page.rect.width > page.rect.height + 1:
        page.set_rotation((page.rotation + 90) % 360)
    rect = page.rect
    if _is_label_page(rect):
        return _place(_render_rect(page, rect))
    clip = _content_clip(page)
    if clip.width < 36 or clip.height < 36:
        clip = rect
    return _place(_render_rect(page, clip))


def _is_label_page(rect: pymupdf.Rect) -> bool:
    width_in = rect.width / 72
    height_in = rect.height / 72
    if width_in > height_in:
        width_in, height_in = height_in, width_in
    return 3.7 <= width_in <= 4.35 and 5.4 <= height_in <= 6.5


def pdf_has_label_page(data: bytes) -> bool:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return False
    try:
        return any(_is_label_page(page.rect) for page in document)
    finally:
        document.close()


def pdf_page_count(data: bytes) -> int:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        if document.needs_pass:
            raise ValueError("El PDF está protegido con contraseña")
        if document.page_count == 0:
            raise ValueError("El PDF no tiene páginas")
        return document.page_count
    finally:
        document.close()


def pdf_page_png(data: bytes, index: int) -> bytes:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[index]
        zoom = 640 / max(page.rect.width, 1)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def render_pdf_crop(data: bytes, index: int, x: float, y: float, w: float, h: float, turned: bool = False) -> Image.Image:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[index]
        rect = page.rect
        left = rect.x0 + _unit(x) * rect.width
        top = rect.y0 + _unit(y) * rect.height
        clip = pymupdf.Rect(
            left,
            top,
            left + min(max(float(w), 0.02), 1) * rect.width,
            top + min(max(float(h), 0.02), 1) * rect.height,
        ) & rect
        if clip.width < 4 or clip.height < 4:
            raise ValueError("el recorte está vacío")
        target_w, target_h = (LABEL_H, LABEL_W) if turned else (LABEL_W, LABEL_H)
        zoom = min(target_w / clip.width, target_h / clip.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
        image = _pixmap_image(pixmap)
        if turned:
            image = image.transpose(Image.Transpose.ROTATE_90)
        return _place(image)
    finally:
        document.close()


def _unit(value: float) -> float:
    return min(max(float(value), 0), 1)


def _content_clip(page: pymupdf.Page) -> pymupdf.Rect:
    probe = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY, alpha=False)
    bbox = _content_bbox(probe.samples, probe.width, probe.height)
    if bbox is None or _covers_page(bbox, probe.width, probe.height):
        return page.rect
    pad = 2
    clip = pymupdf.Rect(
        page.rect.x0 + bbox[0] - pad,
        page.rect.y0 + bbox[1] - pad,
        page.rect.x0 + bbox[2] + pad,
        page.rect.y0 + bbox[3] + pad,
    )
    return clip & page.rect


def _covers_page(bbox: tuple[int, int, int, int], width: int, height: int) -> bool:
    box_w = bbox[2] - bbox[0]
    box_h = bbox[3] - bbox[1]
    return box_w >= width * 0.92 and box_h >= height * 0.92


def _content_bbox(
    samples: bytes,
    width: int,
    height: int,
    level: int = 245,
) -> tuple[int, int, int, int] | None:
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        row = y * width
        for x in range(width):
            if samples[row + x] < level:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def _render_rect(page: pymupdf.Page, clip: pymupdf.Rect) -> Image.Image:
    zoom = min(LABEL_W / clip.width, LABEL_H / clip.height)
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(zoom, zoom),
        clip=clip,
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    return _pixmap_image(pixmap)


def _pixmap_image(pixmap: pymupdf.Pixmap) -> Image.Image:
    if pixmap.n == 1:
        return Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    mode = "RGBA" if pixmap.alpha else "RGB"
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples).convert("L")


def _place(image: Image.Image) -> Image.Image:
    if image.width > LABEL_W or image.height > LABEL_H:
        scale = min(LABEL_W / image.width, LABEL_H / image.height)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.NEAREST,
        )
    canvas = Image.new("L", (LABEL_W, LABEL_H), 255)
    canvas.paste(image, ((LABEL_W - image.width) // 2, (LABEL_H - image.height) // 2))
    return canvas


def image_to_zpl(image: Image.Image) -> str:
    """1 = negro en ZPL. El ancho de cada fila se rellena al byte."""
    image = image.convert("L")
    width, height = image.size
    row_bytes = (width + 7) // 8
    pixels = image.tobytes()
    graphic = bytearray(row_bytes * height)
    for y in range(height):
        row = y * width
        offset = y * row_bytes
        for x in range(width):
            if pixels[row + x] < 128:
                graphic[offset + (x >> 3)] |= 0x80 >> (x & 7)
    total = row_bytes * height
    return (
        f"^XA^PW{width}^LL{height}^LH0,0"
        f"^FO0,0^GFA,{total},{total},{row_bytes},{graphic.hex().upper()}^FS^XZ"
    )


def send_to_printer(zpl: str, printer: str) -> str:
    proc = subprocess.run(
        ["/usr/bin/lp", "-d", printer, "-o", "raw", "-t", "CazaToy"],
        input=zpl.encode("latin-1", errors="replace"),
        capture_output=True,
        timeout=60,
        check=False,
    )
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        detail = (err or out).strip() or f"lp terminó con código {proc.returncode}"
        raise RuntimeError(detail)
    match = re.search(r"([A-Za-z0-9_.-]+-\d+)", out)
    return match.group(1) if match else out.strip() or "enviado"


def sample_label_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=288, height=432)
    page.insert_text((30, 56), "CazaToy", fontsize=22)
    page.insert_text((30, 92), "Etiqueta de prueba 4x6", fontsize=12)
    x = 30.0
    for index, bar in enumerate((2, 1, 3, 1, 2, 4, 1, 2, 1, 3, 2, 1, 4, 2)):
        if index % 2 == 0:
            page.draw_rect(pymupdf.Rect(x, 140, x + bar * 3, 230), color=(0, 0, 0), fill=(0, 0, 0))
        x += bar * 3
    data = document.tobytes()
    document.close()
    return data
