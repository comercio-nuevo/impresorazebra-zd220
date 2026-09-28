"""Busca un hueco en blanco y estampa el texto caza toy sin tapar códigos."""

from __future__ import annotations

import re
from array import array
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import LABEL_H, LABEL_W, logo_file

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "caza.png"

ZPL_FONT_H = 26
ZPL_FONT_W = 16

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def clean_logo(text: str) -> str:
    cleaned = [ch for ch in text if ch not in "^~" and 32 <= ord(ch) <= 126]
    return "".join(cleaned).strip() or "caza toy"


def threshold(image: Image.Image, level: int = 200) -> Image.Image:
    lut = [0 if value < level else 255 for value in range(256)]
    return image.convert("L").point(lut)


def load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_wordmark(text: str) -> Image.Image:
    text = clean_logo(text)
    size = 28
    font = load_font(size)
    bbox = _text_bbox(text, font)
    while size > 14:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= 340 and height <= 48:
            break
        size -= 2
        font = load_font(size)
        bbox = _text_bbox(text, font)
    width = max(1, bbox[2] - bbox[0] + 2)
    height = max(1, bbox[3] - bbox[1] + 2)
    image = Image.new("L", (width, height), 255)
    ImageDraw.Draw(image).text((1 - bbox[0], 1 - bbox[1]), text, fill=0, font=font)
    return threshold(image, level=128)


def _text_bbox(text: str, font: ImageFont.ImageFont) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(Image.new("L", (1, 1), 255))
    return draw.textbbox((0, 0), text, font=font)


def find_white_origin(
    image: Image.Image,
    box_w: int,
    box_h: int,
    margin: int = 8,
) -> tuple[int, int] | None:
    """Devuelve dónde cabe un rectángulo totalmente blanco, o None."""
    width, height = image.size
    need_w = box_w + margin * 2
    need_h = box_h + margin * 2
    if need_w > width or need_h > height or box_w < 1 or box_h < 1:
        return None
    pixels = image.tobytes()
    stride = width + 1
    integral = array("I", [0]) * (stride * (height + 1))
    for y in range(height):
        row = y * width
        running = 0
        below = (y + 1) * stride
        above = y * stride
        for x in range(width):
            running += 1 if pixels[row + x] < 128 else 0
            integral[below + x + 1] = integral[above + x + 1] + running

    def blacks(x: int, y: int, rect_w: int, rect_h: int) -> int:
        x2 = x + rect_w
        y2 = y + rect_h
        return (
            integral[y2 * stride + x2]
            - integral[y * stride + x2]
            - integral[y2 * stride + x]
            + integral[y * stride + x]
        )

    best: tuple[int, int] | None = None
    best_score = -1e9
    step = 4
    for y in range(0, height - need_h + 1, step):
        for x in range(0, width - need_w + 1, step):
            if blacks(x, y, need_w, need_h) != 0:
                continue
            origin_x = x + margin
            origin_y = y + margin
            penalty = -3 if origin_y + box_h > height * 0.82 else 0
            score = (origin_x / width) * 3 + (1 - origin_y / height) + penalty
            if score > best_score:
                best_score = score
                best = (origin_x, origin_y)
    return best


def load_logo_mark(width: int, source: Path | None = None, ascii_mode: bool = False) -> Image.Image:
    """El blanco y lo transparente no se imprimen; solo queda el trazo negro."""
    path = source if source is not None and source.exists() else LOGO_PATH
    source = Image.open(path).convert("RGBA")
    pixels = source.load()
    visited_min_x, visited_min_y = source.width, source.height
    max_x = max_y = -1
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 20 or (red > 245 and green > 245 and blue > 245):
                continue
            visited_min_x = min(visited_min_x, x)
            visited_min_y = min(visited_min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0:
        cropped = source.convert("L")
    else:
        cropped = source.crop((visited_min_x, visited_min_y, max_x + 1, max_y + 1)).convert("L")
    width = max(40, int(width))
    height = max(1, round(width * cropped.height / max(cropped.width, 1)))
    resized = cropped.resize((width, height), Image.Resampling.BOX)
    marked = threshold(resized, level=170)
    if not ascii_mode:
        return marked
    from .pipeline import digit_matrix

    return digit_matrix(marked)


def gfa_field(image: Image.Image, x: int, y: int) -> str:
    image = image.convert("L")
    width, height = image.size
    row_bytes = (width + 7) // 8
    pixels = image.tobytes()
    graphic = bytearray(row_bytes * height)
    for row_y in range(height):
        row = row_y * width
        offset = row_y * row_bytes
        for row_x in range(width):
            if pixels[row + row_x] < 128:
                graphic[offset + (row_x >> 3)] |= 0x80 >> (row_x & 7)
    total = row_bytes * height
    return f"^FO{int(x)},{int(y)}^GFA,{total},{total},{row_bytes},{graphic.hex().upper()}^FS"


def _paste_mark(image: Image.Image, mark: Image.Image, x: int, y: int) -> Image.Image:
    if x >= image.width or y >= image.height:
        return image
    visible = mark.crop((0, 0, min(mark.width, image.width - x), min(mark.height, image.height - y)))
    mask = visible.point([255 if value < 128 else 0 for value in range(256)])
    black = Image.new("L", visible.size, 0)
    image.paste(black, (max(0, x), max(0, y)), mask)
    return image


def _mark_placements(placement: dict) -> list[dict]:
    name = str(placement.get("name", ""))
    images = placement.get("images")
    if not isinstance(images, list) or not images:
        if placement.get("present") is False:
            return []
        return [{**placement, "name": name, "slot": int(placement.get("slot", 1))}]
    marks = []
    for item in images[:2]:
        if not isinstance(item, dict) or item.get("present") is False:
            continue
        marks.append({**item, "name": name, "slot": int(item.get("slot", len(marks) + 1))})
    return marks


def _logo_for(place: dict) -> Image.Image:
    custom = logo_file(str(place.get("name", "")), int(place.get("slot", 1)))
    legacy = logo_file(str(place.get("name", "")), 1)
    source = custom if custom.exists() else legacy if int(place.get("slot", 1)) == 1 and legacy.exists() else None
    return load_logo_mark(int(place["width"]), source if source is not None and source.exists() else None, bool(place.get("ascii")))


def stamp_bitmap(image: Image.Image, text: str, placement: dict | None = None) -> tuple[Image.Image, bool]:
    image = threshold(image)
    if placement:
        for place in _mark_placements(placement):
            _paste_mark(image, _logo_for(place), int(place["x"]), int(place["y"]))
        return image, True
    mark = render_wordmark(text)
    origin = find_white_origin(image, mark.width, mark.height)
    if origin is None:
        return image, False
    _paste_mark(image, mark, origin[0], origin[1])
    return image, True


def render_zpl_pages(zpl: str) -> list[Image.Image]:
    """Dibuja cada bloque ^XA como texto y rectángulos. Sirve para el modo matriz."""
    parts = re.split(r"(\^XA.*?\^XZ)", zpl, flags=re.S)
    pages = [_draw_zpl_label(part) for part in parts if part.startswith("^XA") and "^XZ" in part]
    if not pages:
        raise ValueError("El ZPL no tiene etiquetas")
    return pages


def _draw_zpl_label(zpl: str) -> Image.Image:
    width, height = LABEL_W, LABEL_H
    x = y = 0
    module = 2
    font_h, font_w = 28, 14
    field_kind = "text"
    field_h = font_h
    field_w: int | None = None
    marks: list[tuple] = []
    for name, params in _commands(zpl):
        if name == "PW":
            nums = _ints(params)
            if nums:
                width = max(1, nums[0])
        elif name == "LL":
            nums = _ints(params)
            if nums:
                height = max(1, nums[0])
        elif name in ("FO", "FT"):
            nums = _ints(params)
            if len(nums) >= 2:
                x, y = nums[0], nums[1]
            field_kind = "text"
            field_w = None
        elif name == "BY":
            nums = _ints(params)
            if nums:
                module = max(1, nums[0])
        elif name == "A":
            nums = _ints(params)
            if len(nums) >= 2:
                font_h, font_w = nums[-2], max(1, nums[-1])
            field_kind = "text"
            field_h = font_h
        elif name == "FB":
            nums = _ints(params)
            if nums:
                field_kind = "block"
                field_w = nums[0] or 100
                field_h = font_h * (nums[1] if len(nums) > 1 else 1)
        elif name == "GB":
            nums = _ints(params)
            if len(nums) >= 2:
                box_w = nums[0] or width
                box_h = nums[1] or (nums[2] if len(nums) > 2 else 1) or 1
                marks.append(("rect", x, y, box_w, box_h, 0))
        elif name == "BC":
            nums = _ints(params)
            field_kind = "barcode"
            field_h = nums[0] if nums else 100
        elif name in ("BQ", "BX"):
            nums = _ints(params)
            mag = nums[-1] if nums else 2
            size = max(48, mag * 25 * module)
            field_kind = "qr"
            field_h = size
            field_w = size
        elif name == "FD":
            data = params
            if field_kind in ("barcode", "qr", "block"):
                if field_kind == "qr":
                    box_w = field_w or 80
                    box_h = field_h
                elif field_kind == "barcode":
                    box_w = (11 * max(len(data), 1) + 45) * module
                    box_h = field_h
                else:
                    box_w = field_w or max(1, len(data)) * font_w
                    box_h = field_h
                marks.append(("rect", x, y, box_w, box_h, 0))
            else:
                marks.append(("text", x, y, data, font_h, font_w))
            field_kind = "text"
            field_w = None
    scale_x = LABEL_W / width
    scale_y = LABEL_H / height
    canvas = Image.new("L", (LABEL_W, LABEL_H), 255)
    draw = ImageDraw.Draw(canvas)
    for mark in marks:
        if mark[0] == "rect":
            _, left, top, box_w, box_h, _ = mark
            draw.rectangle(
                (
                    int(left * scale_x),
                    int(top * scale_y),
                    int((left + box_w) * scale_x),
                    int((top + box_h) * scale_y),
                ),
                fill=0,
            )
            continue
        _, left, top, data, size_h, _size_w = mark
        font = load_font(max(12, int(size_h * scale_y)))
        draw.text((int(left * scale_x), int(top * scale_y)), str(data)[:80], fill=0, font=font)
    return canvas


def stamp_zpl(zpl: str, text: str, placement: dict | None = None) -> tuple[str, bool]:
    """Sin posición, inserta el texto. Con posición de tienda, pega el logo ahí."""
    if placement:
        fields = "".join(
            gfa_field(_logo_for(place), int(place["x"]), int(place["y"]))
            for place in _mark_placements(placement)
        )
        parts = re.split(r"(\^XA.*?\^XZ)", zpl, flags=re.S)
        if not any(part.startswith("^XA") for part in parts):
            return zpl, False
        output = []
        for part in parts:
            if part.startswith("^XA") and "^XZ" in part:
                cut = part.rfind("^XZ")
                output.append(part[:cut] + fields + part[cut:])
            else:
                output.append(part)
        return "".join(output), True
    logo = clean_logo(text)
    parts = re.split(r"(\^XA.*?\^XZ)", zpl, flags=re.S)
    if not any(part.startswith("^XA") for part in parts):
        return zpl, False
    stamped = False
    output: list[str] = []
    need_w = max(1, len(logo)) * ZPL_FONT_W
    need_h = ZPL_FONT_H
    for part in parts:
        if not part.startswith("^XA") or "^XZ" not in part or "^GF" in part:
            output.append(part)
            continue
        width, height, boxes = _occupancy(part)
        origin = _find_gap(width, height, boxes, need_w, need_h)
        if origin is None:
            output.append(part)
            continue
        x, y = origin
        snippet = f"^FO{x},{y}^A0N,{ZPL_FONT_H},{ZPL_FONT_W}^FD{logo}^FS"
        cut = part.rfind("^XZ")
        output.append(part[:cut] + snippet + part[cut:])
        stamped = True
    return "".join(output), stamped


def _commands(zpl: str) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    index = 0
    length = len(zpl)
    while index < length:
        if zpl[index] not in "^~":
            index += 1
            continue
        cursor = index + 1
        name = ""
        while cursor < length and zpl[cursor].isalpha() and len(name) < 2:
            name += zpl[cursor]
            cursor += 1
        end = cursor
        while end < length and zpl[end] not in "^~":
            end += 1
        if name:
            commands.append((name, zpl[cursor:end]))
        index = end
    return commands


def _ints(params: str) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", params)]


def _occupancy(zpl: str) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    width, height = LABEL_W, LABEL_H
    x = y = 0
    module = 2
    font_h, font_w = 28, 14
    field_kind = "text"
    field_h = font_h
    field_w: int | None = None
    boxes: list[tuple[int, int, int, int]] = []
    for name, params in _commands(zpl):
        if name == "PW":
            nums = _ints(params)
            if nums:
                width = nums[0]
        elif name == "LL":
            nums = _ints(params)
            if nums:
                height = nums[0]
        elif name in ("FO", "FT"):
            nums = _ints(params)
            if len(nums) >= 2:
                x, y = nums[0], nums[1]
            field_kind = "text"
            field_w = None
        elif name == "BY":
            nums = _ints(params)
            if nums:
                module = max(1, nums[0])
        elif name == "A":
            nums = _ints(params)
            if len(nums) >= 2:
                font_h, font_w = nums[-2], max(1, nums[-1])
            field_kind = "text"
            field_h = font_h
        elif name == "FB":
            nums = _ints(params)
            if nums:
                field_kind = "block"
                field_w = nums[0] or 100
                field_h = font_h * (nums[1] if len(nums) > 1 else 1)
        elif name == "GB":
            nums = _ints(params)
            if len(nums) >= 2:
                box_w = nums[0] or width
                box_h = nums[1] or (nums[2] if len(nums) > 2 else 1) or 1
                boxes.append((x, y, box_w, box_h))
        elif name == "BC":
            nums = _ints(params)
            field_kind = "barcode"
            field_h = nums[0] if nums else 100
        elif name in ("BQ", "BX"):
            nums = _ints(params)
            mag = nums[-1] if nums else 2
            size = max(48, mag * 25 * module)
            field_kind = "qr"
            field_h = size
            field_w = size
        elif name == "FD":
            data = params
            if field_kind == "qr":
                box_w = field_w or 80
                box_h = field_h
            elif field_kind == "barcode":
                box_w = (11 * max(len(data), 1) + 45) * module
                box_h = field_h
            elif field_kind == "block":
                box_w = field_w or max(1, len(data)) * font_w
                box_h = field_h
            else:
                box_w = max(1, len(data)) * max(font_w, 1)
                box_h = font_h
            boxes.append((x, y, box_w, box_h))
            field_kind = "text"
            field_w = None
    return width, height, boxes


def _find_gap(
    width: int,
    height: int,
    boxes: list[tuple[int, int, int, int]],
    need_w: int,
    need_h: int,
    margin: int = 10,
) -> tuple[int, int] | None:
    cell = 8
    grid_w = max(1, (width + cell - 1) // cell)
    grid_h = max(1, (height + cell - 1) // cell)
    occupied = bytearray(grid_w * grid_h)
    pad = 12
    for box_x, box_y, box_w, box_h in boxes:
        x0 = max(0, (box_x - pad) // cell)
        y0 = max(0, (box_y - pad) // cell)
        x1 = min(grid_w, (box_x + box_w + pad + cell - 1) // cell)
        y1 = min(grid_h, (box_y + box_h + pad + cell - 1) // cell)
        for gy in range(y0, y1):
            row = gy * grid_w
            for gx in range(x0, x1):
                occupied[row + gx] = 1
    need_cw = max(1, (need_w + margin * 2 + cell - 1) // cell)
    need_ch = max(1, (need_h + margin * 2 + cell - 1) // cell)
    if need_cw > grid_w or need_ch > grid_h:
        return None
    best: tuple[int, int] | None = None
    best_score = -1e9
    for gy in range(0, grid_h - need_ch + 1):
        for gx in range(0, grid_w - need_cw + 1):
            blocked = False
            for yy in range(gy, gy + need_ch):
                row = yy * grid_w
                if any(occupied[row + xx] for xx in range(gx, gx + need_cw)):
                    blocked = True
                    break
            if blocked:
                continue
            origin_x = gx * cell + margin
            origin_y = gy * cell + margin
            penalty = -3 if origin_y + need_h > height * 0.82 else 0
            score = (origin_x / max(width, 1)) * 3 + (1 - origin_y / max(height, 1)) + penalty
            if score > best_score:
                best_score = score
                best = (origin_x, origin_y)
    return best
